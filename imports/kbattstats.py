"""
This module is a part of the hardware monitoring toolset from GitHub/kadavris/monitoring
The main feature is the KBattStats base class that provides simple statistical data processing
for the UPS-type device's battery health.
"""
from configparser import ConfigParser
import copy
import json
import kadpy.kpowerutils as kpu
from kadpy.kpowerutils import KBatteryTypes
from kadpy.kpowerutils import KPowerDeviceCommons
import time
from typing import Any, cast


########################################
class KBattStats:
    def __init__(self, batt_id: str, dev_commons: KPowerDeviceCommons, config: ConfigParser,
                 saved_stats: dict | None) -> None:
        """
        KBattStats constructor.
        :param batt_id: unique id of the battery
        :param dev_commons: KPowerDeviceCommons: device info set from the main module
        :param config: ConfigParser - .ini file configuration
        :param saved_stats: dict: JSON 'batteries' dict from permastorage or None
        """
        dev_conf = config['power.' + dev_commons.dev_id]
        batt_conf_name = 'battery.' + batt_id
        batt_conf = config[batt_conf_name]

        # public:
        self.charge: float = 100.0  # percentage
        self.commons = dev_commons
        self.id = batt_id
        self.invalid = False  # used to indicate that this instance has invalid setup or data
        self.messages: list[str] = []

        self.capacity_ah: int = batt_conf.getint('capacity_ah', -1 )
        self.type: KBatteryTypes = kpu.bt_from_str(batt_conf.get('type', '' ))
        self.v_nom: int = batt_conf.getint( 'vnom', -1 )  # nominal Voltage
        self.capacity_wh: int = int(self.capacity_ah * self.v_nom * dev_commons.power_factor)

        # private:
        self._calc_charge_data = batt_conf.getboolean('calc_charge_data', dev_commons.calc_charge_data)
        self._ideal_sector_speed: int = 3600 * self.capacity_wh // (kpu.CHARGE_STEPS - 1)
        self._pdata: dict[str, Any] | None = None  # persistent data that may be saved into a file

        # initial current states
        self._charge_sector: int = -1  # which charge percentage sector we are in (see CHARGE_STEPS)
        self._time_in_charge_sector: int = 0  # for how long battery transitioned to a current charge level
        self._charge_sector_start: float = -1.0  # when we switched to this sector what charge level was the 1st?
        self._load_avg: float = 0.0  # avg load level at this charge level
        self._state_samples: int = 0  # how many times update have been called while in this sector
        self._was_discharging: bool = False  # is battery discharging?

        # prep a fallback data. Also used to match current config against loaded JSON
        init_data: dict = {
            'registered': [int(time.time()), time.asctime()],
            'messages': [],
            'type': str(self.type),
            'vnom': self.v_nom,
            'capacity_ah': self.capacity_ah,
            'health': {
                'cycles': [0, 0, 0],
                'status': "OK",
                'tbf': -1,
                'wellness': 100,
            },
            # there will be up to WEEKS_IN_A_YEAR sub-arrays for each of the elements inside 'weekly' key
            # for the last year. we'll initialize only the 1st element for starters
            'weekly': {
                'start_ts': [],  # starting timestamp of the week
                # charge and discharge speeds arrays. For initialization details see ._weekly_shift()
                # Each week is a list with CHARGE_STEPS items with _avg ones holding time divided by avg load
                # and _samples ones are the count of samples for continuous averaging
                'discharge_speed_avg': [],
                'discharge_speed_samples': [],
                'charge_speed_avg': [],
                'charge_speed_samples': [],
            }
        }

        if saved_stats and (batt_id in saved_stats):  # is there are smth inside 'batteries': {} ?
            my_old_stats = saved_stats[batt_id]
            # validating
            err_prefix = f'ERROR: {batt_id} old stats: '
            warn_prefix = f'WARNING: {batt_id} old stats: '
            discard_stats = False

            m = kpu.validate_structure(init_data, my_old_stats, err_prefix)
            if m:
                self.invalid = True
                self.messages.extend(m)

            if len(my_old_stats['messages']) > 0:  # Oh. That was already broken
                for m in my_old_stats['messages']:
                    if 'have OLD message' not in m and (m.startswith('ERROR') or m.startswith('WARNING')):
                        self.invalid = m.startswith('ERROR')
                        self.messages.append(err_prefix + "have OLD message: " + m)

            t = int(time.time())
            rt = my_old_stats['registered']
            if (len(rt) != 2 or type(rt[0]) is not int
                    or rt[0] < t - kpu.SECONDS_IN_YEAR or rt[0] >= t):
                discard_stats = True
                self.messages.append(warn_prefix + "registration time is suspicious: " + str(rt) )

            w = my_old_stats['weekly']
            wlen = len(w['start_ts'])
            if (wlen != len(w['discharge_speed_avg'])
                    or wlen != len(w['discharge_speed_samples'])
                    or wlen != len(w['charge_speed_avg'])
                    or wlen != len(w['charge_speed_samples'])):
                discard_stats = True
                self.messages.append(warn_prefix + "weekly series lengths are inconsistent" )

            if kpu.bt_from_str(my_old_stats['type']) is not self.type:
                self.invalid = True
                self.messages.append(err_prefix + " battery type is not the same")

            if self.invalid or discard_stats:  # init with a stub
                del saved_stats[batt_id]
                self._pdata = init_data
                return

            self._pdata = copy.deepcopy(my_old_stats)
            del saved_stats[batt_id]

        else:  #  no saved data - performing initial setup
            self._pdata = init_data

            self._weekly_shift()  # add new week items to start with


    ########################################
    def _weekly_shift(self) -> None:
        """
        Shifts old weekly data towards the back of list and adds fresh (zeroes) items for a new week in the front
        :return: None
        """
        t = int(time.time())
        w = cast(dict[str, list[Any]], self._pdata['weekly'])  # to shut IDE up

        for k in w:
            while len(w[k]) >= kpu.WEEKS_IN_A_YEAR:
                w[k].pop()

        w['start_ts'].insert(0, t)

        # creating averages
        for k in ['discharge_speed', 'charge_speed']:
            w[k + '_avg'].insert(0, [0.0 for _ in range(kpu.CHARGE_STEPS)])
            w[k + '_samples'].insert(0, [0 for _ in range(kpu.CHARGE_STEPS)])


    ########################################
    def _weekly_avg_add(self, name: str, val: float, sector: int) -> None:
        """
        Updates this week average value for a specific item pair: <name>_avg and <name>_samples
        :param name: base name of the item
        :param val: value to add
        :param sector: charge percentage sector to use
        :return: None
        """
        w = cast(dict[str, list[Any]], self._pdata['weekly'])
        if int(time.time()) - w['start_ts'][0] >= kpu.SECONDS_IN_A_WEEK:
            self._weekly_shift()

        w[name + '_avg'][0][sector], w[name + '_samples'][0][sector] = \
            kpu.update_avg_float(w[name + '_avg'][0][sector], val, w[name + '_samples'][0][sector])


    ########################################
    def stats_file_append(self, file) -> None:
        """Append local info as JSON to the file being saved"""
        self._pdata['messages'] = self.messages.copy()
        file.write('"' + self.id + '":\n')
        file.write(json.dumps(self._pdata))
        # file.write('}')


    ########################################
    def process_upsc_data(self, upsc_data: dict) -> None:
        """
        Updates very common stats data with a new set from device.
        This method should be overridden by subclasses, but it is a good idea to call the base.
        :param upsc_data: dict: device's current state as reported by upsc
        :return: None
        """


    ########################################
    def get_battery_health(self) -> dict:
        """Abstract: overriding method should return battery health information
        within a dict: {"cycles": [<soft>,<norm>,<bad>], "status": "Whatever", "tbf": <weeks berfore a failure>}
        """
        return { "cycles": [0,0,0], "status": "This is a stub!", "tbf": -1, "wellness": 100 }


    ########################################
    def get_remaining_wh(self) -> int:
        """Return battery remainig capacity in Wh:
        :return int: remaining Wh"""

        return int(self.charge / 100.0 * self.capacity_wh)
