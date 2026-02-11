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
        if self.invalid:
            return

        self.type: int = kbattstats.BT_LEAD

        self._pack_size = self._dev_data['pack_size'] = self._pdata['batt_vnom'] / 12.0

        self._calc_charge = bool(dev_data['calc_charge_data']) if 'calc_charge_data' in dev_data else False

        # these below are for extrapolating voltage on charge to a real charge level
        # when device reports 100% and/or Vbatt > 100% right after going on mains
        self._last_ob_v = -1.0  # last voltage in OB
        self._charge_state = _CS_NONE


    ########################################
    def _update_hourly_load(self, dd: dict) -> None:
        """
        Updates hourly load averages from device data
        :param dd: dict: device data as supplied by upsc
        :return: None
        """
        hour = time.localtime().tm_hour
        avg = self._pdata['hourly_load_avg']
        samp = self._pdata['hourly_load_samples']
        avg[hour], samp[hour] = kbattstats.update_avg_int(avg[hour], int(dd['ups_load']), samp[hour])


    ########################################
    def _get_charge_percent(self, upsc_data: dict, discharging: bool) -> float:
        """
        Based on device's configuration will return batterg charge level as reported by device
        or calculated by other means
        :param upsc_data: dict: data collected from device interface
        :param discharging: bool: True if discharging mode is detected in currfent data packet
        :return: int: charge level in percents
        """
        if self.invalid:  # make it a visible problem on a dashboard
            return -1.0

        # should we calculate?
        if not self._calc_charge:
            if 'battery_charge' in upsc_data:
                return round(float(upsc_data['battery_charge']), 1)

        # Is device lying to us? (probably we need a config option for this calculated item)
        v = float(upsc_data['battery_voltage']) / self._pack_size

        if discharging:
            self._charge_state = _CS_NONE
            return _voltage_to_charge(v)

        # before we'll call charge percent calculation, we need to figure out some state for charging
        if self._discharging:  # state change
            self._charge_state = _CS_BOOST

        if self._charge_state == _CS_BOOST:
            # if voltage dropped, assuming we're past boost and on the float support
            # 0.3 is a safe appr of boost v - float v minimal diff with a bit of jitter
            if self._last_ob_v > _v_float and self._last_ob_v - v >= 0.3:
                self._charge_state = _CS_FLOAT
        else:  # PAST_BOOST
            if abs(v - _v_float) > 0.1:  # safeguard in case we missed some discharge cycle(s)
                self._charge_state = _CS_BOOST

        if self._charge_state == _CS_BOOST:
            return round((v - _v_fatal) / (_v_boost - _v_fatal) * 100.0, 1)  # using linear scale for simplicity
        else:
            return 100.0


    ########################################
    def _init_for_new_sector(self, upsc_data: dict, discharging: bool, load: float, v: float) -> None:
        charge = self._get_charge_percent(upsc_data, discharging)
        self._charge_sector = int(charge / kbattstats.SECTOR_WIDTH)
        self._charge_sector_start = charge
        self._discharging = discharging
        self._time_in_charge_sector = 0
        self._load_avg = load
        self._state_samples = 1
        self._last_ob_v = v
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
        # dd = self._dev_data

        self._update_hourly_load(upsc_data)

        load = float(upsc_data['ups_load'])
        discharging = bool(re.search(r'\bob\b', upsc_data['ups_status'], re.IGNORECASE))
        v = float(upsc_data['battery_voltage']) / self._pack_size

        if self._charge_sector == -1:
            self._init_for_new_sector(upsc_data, discharging, load, v)
            return

        charge = self._get_charge_percent(upsc_data, discharging)
        charge_sector = int(charge / kbattstats.SECTOR_WIDTH)
        self._last_ob_v = v

        # Are there state transitions? important rule: no direction change
        # Jitter detection: may jolt up on discharge and down on a charge
        if discharging == self._discharging \
            and ( charge_sector == self._charge_sector
                or ( discharging and charge_sector > self._charge_sector )
                or ( not discharging and charge_sector < self._charge_sector)):
            # let's say it's still the same
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
                             self._time_in_charge_sector / self._load_avg, self._charge_sector)

        self._init_for_new_sector(upsc_data, discharging, load, v)

