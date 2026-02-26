import time
from typing import override

import kadpy.kbattstats as kbattstats
import re

# Lead-acid battery constants
_volts_at_charge: list[float] = [
    #  0     10     20     30     40     50     60    70    80     90    100
    10.8, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.85]

# volt lvl diff: 0->10 10->20 20->30 30->40 40->50 50->60 60->70 70->80 80->90 90->100
_v_charge_diff: list[float] = [0.71, 0.15, 0.15, 0.14, 0.1, 0.1, 0.15, 0.2, 0.25, 0.1]
_v_99: float = 12.80  # 99%. just in case
_v_float: float = 13.5  # 'float' charge
_v_boost: float = 14.1  # 'boost' charge
_v_fatal: float = 10.5  # potentially, fatally low

# charge states enum.
# need those to record when battery was actually charged to max and circuit switched to float charge
_CS_NONE: int = 0  # when we're discharging or not counting
_CS_BOOST: int = 1  # when charging and V_batt < _v_boost still
_CS_FLOAT: int = 2  # when charging and V_batt been around _v_boost (CC), but dropped to float (CV)


########################################
def _voltage_to_charge(v: float) -> float:
    """
    Approximates battery charge level from the current voltage of a single 12v element
    :param v: float: voltage
    :return: float: charge level in percents
    """
    if v >= _volts_at_charge[-1]: return 100.0
    if v >= _v_99: return 99.0
    if v <= _volts_at_charge[0]: return 0.0
    i = 1
    while i < 9:
        if v < _volts_at_charge[i]:
            break
        i += 1

    i -= 1
    charge = 10.0 * i
    return round(charge + 10.0 * (v - _volts_at_charge[i]) / _v_charge_diff[i], 1)


########################################
class KBattLead(kbattstats.KBattStats):
    """
    Class for managing statistics for Lead-Acid battery types
    """
    def __init__(self, save_path: str, dev_data: dict) -> None:
        super().__init__(save_path, dev_data)

        err_prefix = "KBattLead ERROR:"
        self.type: int = kbattstats.BT_LEAD

        self._calc_charge = dev_data['calc_charge_data']
        self._batteries['main'] = kbattstats.BData(100.0)

        # these below are for extrapolating voltage on charge to a real charge level
        # when device reports 100% and/or Vbatt > 100% right after going on mains
        self._last_v = -1.0  # last recirded voltage
        self._last_v_step_up_ts = 0.0  # timestamp of the last voltage change. Used on > float charge
        self._last_charge = -1.0  # the charge from the last update.
        self._charge_state = _CS_NONE

        if 'main' in self._pdata['batteries']:  # old file was loaded
            # checking if battery definition is the same
            oldbdata = self._pdata['batteries']['main']
            for item in ['batt_type', 'batt_vnom', 'batt_cap']:
                if not item in oldbdata:
                    self.invalid = True
                    self._pdata['messages'].append(err_prefix + "battery definition missing: " + item)
                else:
                    if dev_data[item] != oldbdata[item]:
                        self.invalid = True
                        self._pdata['messages'].append(err_prefix + \
                                                     "has different battery definition in " + item)
        else:
            ud = self._pdata['ups']
            batt_cap_wh = dev_data['batt_cap'] * ud['power_factor'] * dev_data['batt_vnom']
            self._pdata['batteries']['main'] = {
                'registered': [int(time.time()), time.asctime()],
                'batt_type': dev_data['batt_type'],
                'batt_vnom': dev_data['batt_vnom'],
                'batt_cap': dev_data['batt_cap'],
                'batt_cap_wh': batt_cap_wh,
                'ideal_sector_speed': 3600 * batt_cap_wh / (kbattstats.CHARGE_STEPS - 1),
                'health': {
                    'cycles': [0,0,0],
                    'status': "OK",
                    'tbf': -1,
                },
            }

        self._bdata = self._pdata['batteries']['main']
        self._pack_size = self._dev_data['pack_size'] = self._bdata['batt_vnom'] / 12.0

        if self.invalid:
            return


    ########################################
    def get_battery_charge(self, battery_id: str) -> float:
        """returns battery charge information"""
        return self._batteries['main'].charge


    ########################################
    def _determine_charge(self, upsc_data: dict, discharging: bool) -> float:
        """
        Based on device's configuration will return batterg charge level as reported by device
        or calculated by other means.
        WARNING! Should be called once from update_stats() because it records state changes internally!
        :param upsc_data: dict: data collected from device interface
        :param discharging: bool: True if discharging mode is detected in currfent data packet
        :return: int: charge level in percents
        """
        if self.invalid:  # make it a visible problem on a dashboard
            self._batteries['main'].charge = -1.0
            return -1.0

        # should we calculate?
        if not self._calc_charge:
            if 'battery_charge' in upsc_data:
                self._batteries['main'].charge = round(float(upsc_data['battery_charge']), 1)
                return self._batteries['main'].charge

        # Is device lying to us? (probably we need a config option for this calculated item)
        v = float(upsc_data['battery_voltage']) / self._pack_size

        if discharging:
            self._charge_state = _CS_NONE
            self._batteries['main'].charge = _voltage_to_charge(v)
            if v < self._last_v:
                self._last_v = v

            return self._batteries['main'].charge

        # Charging state
        # before we'll call charge percent calculation, we need to figure out some state for charging
        if self._discharging:  # state changed OB->OL
            self._charge_state = _CS_BOOST

        if v > self._last_v:
            self._last_v = v
            self._last_v_step_up_ts = time.time()

        if self._charge_state == _CS_BOOST:
            if self._last_v > _v_float:  # we need to be creative in this voltage zone
                # if voltage abruptly dropped, assuming we're past boost and on the float support
                # 0.3 is a safe appr of boost v - float v minimal diff with a bit of jitter
                if self._last_v - v >= 0.3:
                    self._charge_state = _CS_FLOAT
                    self._last_v = v

                # here, assume if battery has not gained > 0.2V (~5.5%) of charge
                # for the time it should have had with 10Amp current - it is in float state already.
                elif time.time() - self._last_v_step_up_ts > \
                        self._bdata['batt_cap'] / self._dev_data['charging_current'] * 3600:
                    self._charge_state = _CS_FLOAT

        else:  # PAST_BOOST
            if abs(v - _v_float) >= 0.2:  # safeguard in case we missed some discharge cycle(s)
                self._charge_state = _CS_BOOST

        if self._charge_state == _CS_BOOST:
            self._batteries['main'].charge = round((v - _v_fatal) / (_v_boost - _v_fatal) * 100.0, 1)  # using linear scale for simplicity
        else:
            self._batteries['main'].charge = 100.0

        return self._batteries['main'].charge


    ########################################
    def _init_for_new_sector(self, upsc_data: dict, discharging: bool, load: float,
                             v: float, charge: float) -> None:
        self._charge_sector = int(charge / kbattstats.SECTOR_WIDTH)
        self._charge_sector_start = charge
        self._discharging = discharging
        self._time_in_charge_sector = 0
        self._load_avg = load
        self._state_samples = 1
        self._charge_state = _CS_NONE


    ########################################
    @override
    def update_stats(self, upsc_data: dict) -> None:
        """
        Updates stats data breakdowns with new set from device
        :param upsc_data: dict: device's current state
        :return: None
        """
        super().update_stats(upsc_data)  # update common stuff

        if self.invalid:
            return

        if 'battery_voltage' not in upsc_data or 'ups_load' not in upsc_data:
            return

        # pd = self._pdata
        dd = self._dev_data

        self._update_hourly_load(upsc_data)

        load = self.get_load_in_watts(upsc_data)
        discharging = bool(re.search(r'\bob\b', upsc_data['ups_status'], re.IGNORECASE))
        v = float(upsc_data['battery_voltage']) / self._pack_size
        charge = self._determine_charge(upsc_data, discharging)

        if self._charge_sector == -1:
            self._init_for_new_sector(upsc_data, discharging, load, v, charge)
            return

        charge_sector = int(charge / kbattstats.SECTOR_WIDTH)

        # Are there state transitions? important rule: no direction change
        # Jitter detection: may jolt up on discharge and down on a charge
        if discharging == self._discharging \
            and ( charge_sector == self._charge_sector
                or ( discharging and charge_sector > self._charge_sector )
                or ( not discharging and charge_sector < self._charge_sector)):
            # let's say it's still the same
            self._last_charge = charge
            self._time_in_charge_sector += self._dev_data['sample_interval']
            self._load_avg, self._state_samples = kbattstats.update_avg_float(self._load_avg, load,
                                                                              self._state_samples)
            return

        # Something changed.
        # Check if we have enough time in a previous state to extrapolate if needed.
        # We want a recorded charge range to be more than 70%+ of this sector width
        ch_left: float
        if self._discharging:  # want to operate on a previous sector's bound
            ch_left = (self._charge_sector + 1) * kbattstats.SECTOR_WIDTH - self._charge_sector_start
        else:
            ch_left = self._charge_sector_start - self._charge_sector * kbattstats.SECTOR_WIDTH

        if ch_left / kbattstats.SECTOR_WIDTH <= 0.5:  # are there less than 50%+ of sector width left unaccounted?
            if ch_left > 0.0:  # need to extrapolate
                self._time_in_charge_sector += int(self._time_in_charge_sector * ch_left / kbattstats.SECTOR_WIDTH)

            # adding normalized. Week shift will be performed in avg_add if needed
            if self._load_avg > 0.0:
                self._weekly_avg_add('discharge_speed' if self._discharging else 'charge_speed',
                             self._load_avg * self._time_in_charge_sector, self._charge_sector)

        if not discharging and self._discharging:  # went OB->OL. Adding health stat
            if self._last_charge >= 80.0:
                self._bdata['health']['cycles'][0] += 1
            elif self._last_charge >= 50.0:
                self._bdata['health']['cycles'][1] += 1
            else:
                self._bdata['health']['cycles'][2] += 1

        self._init_for_new_sector(upsc_data, discharging, load, v, charge)
        self._last_charge = charge


    ########################################
    @override
    def get_battery_health(self, battery_id: str) -> dict:
        """Returns battery health information, the battery id is ignored"""
        bdata = self._bdata
        bdh = bdata['health']

        if self.invalid:
            bdh['status'] = "Invalid setup!"
            return bdh

        if self._dev_data['power_rating'] == -1:
            bdh['status'] = "No power rating in config"
            return bdh

        dspeed_avg = 0.0
        samples = 0
        # Look at the last month worth of data max, to not spoil average too much
        for week in range(min(4, len(self._pdata['weekly']['discharge_speed_avg']))):
            for cs in range(1, kbattstats.CHARGE_STEPS):  # not counting <10% and 100% zones
                v = self._pdata['weekly']['discharge_speed_avg'][week][cs]
                if v > 0.0:
                    dspeed_avg += v
                    samples += 1

            if samples >= 10:
                break

        status = []
        if samples >= 5:  # ensure there are some variety
            dspeed_avg /= samples
            wellness = round(dspeed_avg / bdata['ideal_sector_speed'], 2)
        else:
            wellness = 1.0
            # cycles: < nice >, < normal >, < worst >
            wellness -= bdh['cycles'][0] / 6000.0  # Theoretically 6k is possible in a pampered conditions
            wellness -= bdh['cycles'][1] / 3000.0  # more or less standard
            wellness -= bdh['cycles'][2] / 500.0

        if wellness >= 0.8:
            status.append('OK (>80%)')
            wellness = 10 * int(10.0 * wellness)
        else:
            if wellness >= 0.5:
                wellness = 10 * int(10.0 * wellness)
                status.append(f'Aged: {wellness}%')  # don't dive into small denominations
            else:
                if wellness < 0.0:
                    wellness = 0.0
                else:
                    wellness = int(100.0 * wellness)

                if wellness >= 20:
                    status.append(f'Failing: {wellness}%')
                else:
                    status.append(f'Trash it')

        bdh['status'] = ', '.join(status)
        bdh['wellness'] = int(wellness)
        return bdh


    ########################################
    @override
    def get_battery_runtime(self) -> tuple[int, int, int, int]:
        """Return battery runtime information:
        :return tuple(remaining Wh, secs to 80%, secs to 50%, secs to 10%)"""

        chlvl = self._batteries['main'].charge
        capprc = 3600 * self._bdata['batt_cap_wh'] / 100.0
        la = -1 if self._load_avg == 0.0 else self._load_avg
        to80 = 0 if chlvl <= 80.0 else int(capprc * (chlvl - 80) / la)
        to50 = 0 if chlvl <= 50.0 else int(capprc * (chlvl - 50) / la)
        to10 = 0 if chlvl <= 10.0 else int(capprc * (chlvl - 10) / la)

        return int(chlvl * capprc / 3600), to80, to50, to10

