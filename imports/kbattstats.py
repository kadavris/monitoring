"""
This module is a part of the hardware monitoring toolset from GitHub/kadavris/monitoring
The main feature is the KBattStats base class that provides simple statistical data processing
for the UPS-type device's battery health.
"""
import json
import os
import time
from dataclasses import dataclass
from typing import Any, cast

# time constants for relaxed estimations of a week-based accounting
_SECONDS_IN_A_WEEK: int = 604_800
_SECONDS_IN_A_MONTH: int = 2_588_544  # seconds_in_a_week * 4.28 -> 1 hour drift
_SECONDS_IN_YEAR: int = 31_449_600  # seconds_in_a_week * 52 -> 1 day drift
WEEKS_IN_A_MONTH: int = 4
WEEKS_IN_A_YEAR: int = 52

# we'll store and process battery charge states at 5% wide 'sectors' from 0 to 99.(9)% + 1 for 100%
# What I see is that upsc battery.voltage always have precision of 0.1V.
# With the range of Lead-acid voltage of 12.85 - 10.8 == 2.05V, there is no sense to divide it further
SECTOR_WIDTH: int = 5
CHARGE_STEPS: int = 100 // SECTOR_WIDTH + 1

BT_LEAD: int = 0
BT_LIFEPO: int = 1

@dataclass
class BData:
    """battery data for internal use"""
    charge: float = 0.0


########################################
def update_avg_int(old_avg: int, to_add: int, old_samples: int) -> tuple[int, int]:
    """update and return tuple: (avg, samples) for integer avg value"""
    return (old_avg * old_samples + to_add) // (old_samples + 1), old_samples + 1


def update_avg_float(old_avg: float, to_add: float, old_samples: int) -> tuple[float, int]:
    """update and return tuple: (avg, samples) for float avg value"""
    return (old_avg * old_samples + to_add) / (old_samples + 1), old_samples + 1


########################################
class KBattStats():
    def __init__(self, save_path: str, dev_data: dict) -> None:
        """
        KBattStats constructor.
        :param save_path: str: a directory where the data is permanently stored.
        :param dev_data: dict: device info set from the main module  
        """
        self.invalid = False  # used to indicate that this instance has invalid setup or data
        self.dev_id: str = dev_data['dev_id']
        self._dev_data: dict = dev_data
        self._storage_path: str = save_path
        self._file_name = os.path.join(save_path, 'mqtt-power.' + self.dev_id + '.json')
        self._pdata: dict[str, Any] | None = None  # persistent data that will be saved into a file
        self._batteries: dict[str, BData] = {}

        # initial current states
        self._charge_sector: int = -1  # which charge percentage sector we are in (see CHARGE_STEPS)
        self._time_in_charge_sector: int = 0  # for how long battery transitioned to a current charge level
        self._charge_sector_start: float = -1.0  # when we switched to this sector what charge level was the 1st?
        self._load_avg: float = 0.0  # avg load level at this charge level
        self._state_samples: int = 0  # how many times update have been called while in this sector
        self._discharging: bool = False  # is battery discharging?
        self._in_blackout: bool = False  # is in blackout? Used for continuity

        # looking for old data
        saved_stats = None
        if save_path and os.path.exists(self._file_name) and os.path.getsize(self._file_name) > 0:
            try:
                with open(self._file_name, mode='r', encoding='utf-8') as infile:
                    saved_stats = json.load(infile)
            except Exception:
                pass

        # prep a fallback data. Also used to match current config against loaded JSON
        t = int(time.time())
        init_data: dict = {
            'dev_id': dev_data['dev_id'],
            'messages': [],  # if we want to save some thoughts for meatbags
            'ts': t,  # current timestamp
            'started': t,  # time this device's self._data began

            'ups': {},  # UPS-specific data
            'batteries': {},  # batteries info. Filled in by subclasses
        }

        if saved_stats:
            # validating
            err_prefix = "! ERROR: stats loaded from " + self._file_name + ":"
            if 'messages' in saved_stats and len(saved_stats['messages']) > 0:  # Oh. That was already broken
                self.invalid = True
                for m in saved_stats['messages']:
                    init_data['messages'].append(err_prefix + "have message: " + m)

            if self.dev_id != saved_stats['dev_id']:
                self.invalid = True
                init_data['messages'].append(err_prefix + "is from different device ID")

            # check for missing top-level keywords
            for item in [('batteries', dict), ('dev_id', str), ('started', int), ('ts', int)]:
                if not item[0] in saved_stats:
                    self.invalid = True
                    init_data['messages'].append(err_prefix + f"has no {item[0]} object")
                elif not isinstance(saved_stats[item[0]], item[1]):
                    self.invalid = True
                    init_data['messages'].append(err_prefix + f"keyword {item[0]} is different type")

            if self.invalid:  # init with a stub
                self._pdata = init_data
                return

            self._pdata = saved_stats

        else:  #  no saved data - performing initial setup
            self._pdata = init_data
            # normalizing UPS parameters for stats (to Watts)
            ud = init_data['ups']
            if dev_data['power_rating'] != -1:
                if dev_data['power_rating_unit'] == 'va':
                    ud['power_rating'] = dev_data['power_rating'] * 0.8
                else:
                    ud['power_rating'] = dev_data['power_rating']

                if dev_data['load_reported_as'] == 'p':
                    ud['load_to_w'] = ud['power_rating'] / 100.0
                elif dev_data['load_reported_as'] == 'w':
                    ud['load_to_w'] = 1.0
                else:  # v/a
                    ud['load_to_w'] = 0.8

            ud['power_factor'] = dev_data['power_factor']

            # there will be up to WEEKS_IN_A_YEAR sub-arrays for each of the elements inside 'weekly' key
            # for the last year. we'll initialize only the 1st element for starters
            self._pdata['weekly']: dict[str, list[Any]] = {
                'start_ts': [],  # starting timestamp of the week
                # charge and discharge speeds arrays. For initialization details see ._weekly_shift()
                # Each week is a list with CHARGE_STEPS items with _avg ones holding time divided by avg load
                # and _samples ones are the count of samples for continuous averaging
                'discharge_speed_avg': [],
                'discharge_speed_samples': [],
                'charge_speed_avg': [],
                'charge_speed_samples': [],

                # blackouts are simple integer  totals for this whole week
                'blackouts_count': [],
                'blackouts_time': [],  # hours
            }

            self._weekly_shift()  # add new week items to start with

            # We'll use this for more precise prognostic calculations in blackout
            # hourly_load is 24-element per-hour load average of device
            self._pdata['hourly_load_avg'] = [0] * 24
            self._pdata['hourly_load_samples'] = [0] * 24


    ########################################
    def _update_hourly_load(self, ud: dict) -> None:
        """
        Updates hourly load averages from device data
        :param ud: dict: upsc data as supplied by upsc
        :return: None
        """
        hour = time.localtime().tm_hour
        avg = self._pdata['hourly_load_avg']
        samp = self._pdata['hourly_load_samples']
        avg[hour], samp[hour] = update_avg_int(avg[hour], int(ud['ups_load']), samp[hour])


    ########################################
    def _weekly_shift(self) -> None:
        """
        Shifts old weekly data to the back of list and adds fresh (zeroes) items for a new week in the front
        :return: None
        """
        t = int(time.time())
        w = cast(dict[str, list[Any]], self._pdata['weekly'])  # to shut IDE up

        # if w['start_ts'][0] >= t - _SECONDS_IN_A_WEEK:
        #     raise Exception("KBattStats._weekly_shift(): trying to add new week while current still in progress")

        for k in w:
            while len(w[k]) >= WEEKS_IN_A_YEAR:
                w[k].pop()

        w['start_ts'].insert(0, t)

        # creating averages
        for k in ['discharge_speed', 'charge_speed']:
            w[k + '_avg'].insert(0, [0.0 for _ in range(CHARGE_STEPS)])
            w[k + '_samples'].insert(0, [0 for _ in range(CHARGE_STEPS)])

        # creating totals
        w['blackouts_count'].insert(0, 0)
        w['blackouts_time'].insert(0, 0.0)


    ########################################
    def _weekly_avg_add(self, name: str, val: float, sector: int) -> None:
        """
        Updates this week average value for specific item pair: <name>_avg and <name>_samples
        :param name: base name of the item
        :param val: value to add
        :param sector: charge percentage sector to use
        :return: None
        """
        w = cast(dict[str, list[list]], self._pdata['weekly'])
        if int(time.time()) - w['start_ts'][0] >= _SECONDS_IN_A_WEEK:
            self._weekly_shift()

        w[name + '_avg'][0][sector], w[name + '_samples'][0][sector] = \
            update_avg_float(w[name + '_avg'][0][sector], val, w[name + '_samples'][0][sector])


    ########################################
    def file_save(self) -> bool:
        """
        Safely saves statistics to a predefined file, creating backup. Invalid setup will not overwrite existing file
        :return: bool; success
        """
        if not self._storage_path or not os.path.exists(self._storage_path):
            return False

        bakfile = self._file_name + '.bak'
        try:
            if os.path.exists(self._file_name):
                if self.invalid:
                    return False

                if os.path.exists(bakfile):
                    os.remove(bakfile)

                os.rename(self._file_name, bakfile)

            self._pdata['ts'] = int(time.time())
            with open(self._file_name, mode='w', encoding='utf-8') as outfile:
                json.dump(self._pdata, outfile)
            return True
        except Exception as e:
            self._pdata['messages'].append("! ERROR saving statistics: " + str(e))

        # trying to revert failed save
        try:
            if not os.path.exists(self._file_name) and os.path.exists(bakfile):
                os.rename(bakfile, self._file_name)
        except Exception as e:  # shouldn't happen, but anyway
            self._pdata['messages'].append("! ERROR restoring original save: " + str(e))

        return False


    ########################################
    def update_stats(self, upsc_data: dict) -> None:
        """
        Updates very common stats data with a new set from device.
        This method should be overridden by subclasses, but it is a good idea to call original.
        :param upsc_data: dict: device's current state
        :return: None
        """

        w = cast(dict[str, list[list]], self._pdata['weekly'])

        if 'battery_charge' in upsc_data:
            self.battery_charge = round(float(upsc_data['battery_charge']), 1)
        else:
            self.battery_charge = -1.0

            # Managing blackouts info
        if self._discharging:
            # v = upsc_data['input_voltage']

            if not self._in_blackout:
                self._in_blackout = True
                w['blackouts_count'][0] += 1

            w['blackouts_time'][0] += round(self._dev_data['sample_interval'] / 3600.0, 4)  # counts hours
        else:
            self._in_blackout = False


    ########################################
    def messages(self) -> list[str]:
        """
        Get a list of messages about this instance state. Usually errors ends up there.
        :return: list[str]
        """
        return self._pdata['messages']


    ########################################
    def get_batteries_list(self) -> list[str]:
        """Returns a list of device-attached battery IDs"""
        return self._pdata['batteries'].keys()


    ########################################
    def get_battery_health(self, battery_id: str) -> dict:
        """STUB: overriding member should return battery health information"""
        return { "cycles": [0,0,0], "status": "This is stub!", "tbf": -1 }


    ########################################
    def get_battery_charge(self, battery_id: str) -> float:
        """STUB: overriding member should return battery charge information"""
        return 100.0


    ########################################
    def get_battery_runtime(self) -> tuple[float, float, float]:
        """STUB: overriding member should return battery runtime information:
        (to 80%, to 50%, to zero)"""
        return -1.0, -1.0, -1.0
