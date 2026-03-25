import json
import os
import re
import time
from configparser import ConfigParser, SectionProxy
from typing import Any, cast
from kadpy.kbatteries import KBatteries
import kadpy.kpowerutils as kpu
from kadpy.kpowerutils import KPowerUnits
from kadpy.kpowerutils import KPowerDeviceCommons


class KPowerDevice:
    """UPS device class for use in mqtt-power daemon"""
    def __init__(self, device_id: str, config: ConfigParser) -> None:
        # init the bare minimum first in case of severe errors
        self.id: str = device_id
        self.init_errors = 0
        self.init_warnings = 0
        self._messages: list[str] = []  # filled with problem reports like if setup is invalid

        dev_sect_name = 'power.' + device_id  # this stuff existence should be checked before this obj even created
        dev_sect = config[dev_sect_name]

        # properties based on config values
        self.commons = KPowerDeviceCommons(device_id)
        self.commons.charging_current = dev_sect.getint('charging_current', 10)
        self.commons.sample_interval = dev_sect.getint('sample_interval', 60)
        # batteries charging current (Amps) for estimations
        self.commons.calc_charge_data = dev_sect.getboolean('calc_charge_data', False)

        self.bulk_report: list[str] | None = None # upsc attributes that will be posted in the main topic in bulk
        self.in_blackout: bool = False  # we have been on battery for more than 1 status check cycle
        self.next_stats_save: float = time.time()
        self.load_samples: list[int] = [0]  # load levels for the last hour
        self.log_items: list[str] | None = None # list of items that will be put on log
        self.one_to_one: list[str] | None = None # upsc attribute -> topic for putting out most important entities
        self.power_rating: int  # normalized to Watts
        self.power_rating_unit: KPowerUnits = KPowerUnits.VA  # default pre-normalized
        self.standard_v: float

        # private:
        self._pdata: dict[str, Any]  # permanent storage data
        self._load_to_w: float = 1.0  # reported load to Watts conversion factor
        self._load_zero: float = 0.0  # for devices that cannot precisely report load less than this value
        self._storage_path = dev_sect.get('perma_storage', '')
        if self._storage_path == '':
            self._file_name = ''
        else:
            self._file_name = os.path.join(self._storage_path, 'mqtt-power.' + device_id + '.json')

        saved_data = self.stats_file_load()

        # -------------------------------
        if 'load_reported_as' in dev_sect:
            load_reported_as = KPowerUnits.str_to_val(dev_sect['load_reported_as'].lower())
            if load_reported_as == KPowerUnits.INVALID:
                self._messages.append("ERROR: Invalid load_reported_as def")
                self.init_errors += 1
                load_reported_as = KPowerUnits.INVALID
        else:
            load_reported_as = KPowerUnits.PERCENT

        # -------------------------------
        val, lzunit = kpu.config_parse_power_option(dev_sect, 'load_zero', KPowerUnits.W)
        if val == -1.0:
            self._messages.append("WARNING: Invalid load_zero def")
            self.init_warnings += 1
            self._load_zero = 0.0
        elif val is None:  # not in config
            self._load_zero = 0.0
        else:
            self._load_zero = val

        # -------------------------------
        val, unit = kpu.config_parse_power_option(dev_sect, 'power_rating', KPowerUnits.VA)
        if val is None:  # not in config
            self._messages.append("ERROR: power_rating is not defined")
            self.init_errors += 1
            self.power_rating = -1
            self.power_rating_unit = KPowerUnits.INVALID
        elif val == -1.0 or unit not in [KPowerUnits.VA, KPowerUnits.W]:
            self._messages.append("ERROR: Invalid power_rating def")
            self.init_errors += 1
            self.power_rating = -1
            self.power_rating_unit = KPowerUnits.INVALID
        else:
            self.power_rating = int(kpu.to_watts(val, unit, 0, unit))
            self.power_rating_unit = KPowerUnits.W

        # -------------------------------
        if 'power_factor' in dev_sect:
            try:
                self.commons.power_factor = dev_sect.getfloat('power_factor', 0.8)
                if self.commons.power_factor < 0.5 or self.commons.power_factor >= 1.0:
                    raise ValueError
            except ValueError:
                self._messages.append("WARNING: Invalid power_factor def")
                self.init_warnings += 1
                self.commons.power_factor = -1.0
        else:
            self.commons.power_factor = 0.8

        # -------------------------------
        if 'standard_v' in dev_sect:
            sv = dev_sect['standard_v'].split(',')  # format is V,tolerance%

            try:
                self.standard_v = float(sv[0])
                if self.standard_v < 100 or self.standard_v > 300:
                    raise ValueError
            except ValueError:
                self._messages.append("WARNING: Invalid standard_v def")
                self.init_warnings += 1
                self.standard_v = -1
        else:
            self.standard_v = 230.0

        # -------------------------------
        for report_items in ['one_to_one', 'bulk_report', 'log_items']:
            if report_items in dev_sect:
                setattr(self, report_items, dev_sect[report_items].split())

        # post-fixes
        if self._load_zero > 0.0 and self.power_rating != -1:
            self._load_zero = kpu.to_watts(self._load_zero, lzunit, self.power_rating, self.power_rating_unit)

        if load_reported_as != KPowerUnits.INVALID or self.power_rating == -1:
            self._load_to_w = kpu.to_watts(1.0, load_reported_as, self.power_rating, self.power_rating_unit)
        else:
            self._load_to_w = -1.0

        # NOTE: should come after all .commons were initialized:
        self.batteries = KBatteries(self.commons, config, saved_data)
        if len(self.batteries.messages) != 0:
            self.init_errors += 1

        # every class down the chain will look up its own saved data, process and erase it from the original package
        # So in the end there will be only this class data left or stray garbage
        if saved_data:
            self._pdata = saved_data


    ########################################
    def _update_hourly_load(self, load: int) -> None:
        """
        Updates hourly load averages from device data
        :param load: int: load in Watts
        :return: None
        """
        hour = time.localtime().tm_hour
        avg = self._pdata['hourly_load_avg']
        samp = self._pdata['hourly_load_samples']
        avg[hour], samp[hour] = kpu.update_avg_int(avg[hour], load, samp[hour])

        # update local stats for tha last hour
        lsamp = self.load_samples
        maxnum = 3600 // self.commons.sample_interval
        while len(lsamp) > maxnum:
            lsamp.pop()
        lsamp.insert(0, load)


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

        # creating totals
        w['blackouts_count'].insert(0, 0)
        w['blackouts_time'].insert(0, 0.0)


    ########################################
    def collect_messages(self) -> list[str]:
        to_ret = self._messages.copy()
        if self.batteries:
            to_ret.extend(self.batteries.collect_messages())

        return to_ret


    ########################################
    def stats_file_load(self) -> dict[str, Any] | None:
        """
        Will try to load old stats file and minimally validate it
        :return: if loaded OK then file JSON content as dict, in all other cases - None
        """
        # prep a fallback data. Also used to match current config against loaded JSON
        t = int(time.time())
        init_data: dict = {  # Init for a new set if there was no saved dada or it is invalid
            'dev_id': self.id,
            'messages': [],  # if we want to save some thoughts for meatbags
            'ts': t,  # current timestamp
            'started': t,  # time this device's data collection has begun
            'ups': {},  # UPS-specific data

            # We'll use this for more precise prognostic calculations in blackout
            # hourly_load is 24-element per-hour load average of device
            'hourly_load_avg': [0] * 24,
            'hourly_load_samples': [0] * 24,
            # there will be up to WEEKS_IN_A_YEAR sub-arrays for each of the elements inside 'weekly' key
            # for the last year. we'll initialize only the 1st element for starters
            'weekly': {
                'start_ts': [],  # starting timestamp of the week
                # blackouts are simple integer  totals for this whole week
                'blackouts_count': [],
                'blackouts_time': [],  # hours
            }
        }

        try:
            with open(self._file_name, 'r') as f:
                saved_stats = json.load(f)
        except Exception:
            saved_stats = None

        invalid = False
        if saved_stats:
            # validating
            m = kpu.validate_structure(init_data, saved_stats, 'WARNING: stats file')
            if len(m) > 0:
                invalid = True
                self._messages.extend(m)
                self.init_warnings += 1

            if len(saved_stats['messages']) > 0:  # Oh. That was already broken
                for m in saved_stats['messages']:
                    if m.startswith('ERROR') or m.startswith('WARNING'):
                        invalid = True
                        self._messages.append('WARNING: stats file have message: ' + m)
                        self.init_warnings += 1

            if self.id != saved_stats['dev_id']:
                self._messages.append('WARNING: stats file is from different device ID')
                invalid = True
                self.init_warnings += 1

            if invalid:  # init with a stub
                self._pdata = init_data
                return None

            return saved_stats

        #  no saved data - performing initial setup
        self._pdata = init_data

        self._weekly_shift()  # add new week items to start with

        return None


    ########################################
    def stats_file_save(self) -> bool:
        """
        Safely saves statistics to a predefined file, creating backup. Invalid setup will not overwrite existing file
        :return: bool; success
        """
        if not self._storage_path or not os.path.exists(self._storage_path):
            return False

        bakfile = self._file_name + '.bak'
        try:
            if os.path.exists(self._file_name):
                if os.path.exists(bakfile):
                    os.remove(bakfile)

                os.rename(self._file_name, bakfile)

            self._pdata['ts'] = int(time.time())
            with open(self._file_name, mode='w', encoding='utf-8') as outfile:
                dump = json.dumps(self._pdata)[:-1] + ','
                outfile.write(dump)
                self.batteries.stats_file_append(outfile)
                outfile.write('}')
            return True
        except Exception as e:
            self._messages.append("ERROR saving statistics: " + str(e))

        # trying to revert a failed save
        try:
            if not os.path.exists(self._file_name) and os.path.exists(bakfile):
                os.rename(bakfile, self._file_name)
        except Exception as e:  # shouldn't happen, but anyway
            self._messages.append("ERROR restoring original save: " + str(e))

        return False


    ########################################
    def process_upsc_data(self, upsc_data: dict) -> None:
        """Will process new upsc data"""
        self.commons.last_load = int(upsc_data['ups_load'])
        if self.commons.last_load == 0.0 and self._load_zero > 0.0:
            self.commons.last_load = int(self._load_zero)
        else:
            self.commons.last_load = int(self.commons.last_load * self._load_to_w)

        self._update_hourly_load(self.commons.last_load)

        self.commons.on_battery = bool(re.search(r'\bob\b', upsc_data['ups_status'], re.IGNORECASE))

        # Managing blackouts info
        if self.commons.on_battery:
            if not self.in_blackout:
                self.in_blackout = True
                self._pdata['weekly']['blackouts_count'][0] += 1

            self._pdata['weekly']['blackouts_time'][0] += self.commons.sample_interval
        else:
            self.in_blackout = False

        self.batteries.process_upsc_data(upsc_data)


    ########################################
    @property
    def power_load(self) -> int:
        """Returns device's load value in Watts"""
        return int(self.commons.last_load)


    ########################################
    def get_battery_runtime(self) -> tuple[int, int, int, int]:
        """Return battery runtime information:
        :return tuple(remaining Wh, secs to 80%, secs to 50%, secs to 10%)"""

        wh, prc = self.batteries.get_remaining_power()
        whprc = 3600 * wh / 100.0  # 1% of remaining Watts/seconds
        la = -1 if self.commons.last_load == 0.0 else self.commons.last_load
        # todo: Use self.load_samples to approximate if its differ significantly from the .last_load
        to80 = 0 if prc <= 80.0 else int(whprc * (prc - 80.0) / la)
        to50 = 0 if prc <= 50.0 else int(whprc * (prc - 50.0) / la)
        to10 = 0 if prc <= 10.0 else int(whprc * (prc - 10.0) / la)

        return int(prc * whprc / 3600), to80, to50, to10

