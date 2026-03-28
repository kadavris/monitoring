"""kadpy.kpowerutils: This module is a part of the hardware monitoring toolset from GitHub/kadavris/monitoring.
Miscellaneous utilities for dealing with electricity-related things.
Made by Andrej Pakhutin"""

from configparser import SectionProxy
from dataclasses import dataclass
from enum import Enum

# time constants for relaxed estimations of a week-based accounting
SECONDS_IN_A_WEEK: int = 604_800
SECONDS_IN_A_MONTH: int = 2_588_544  # seconds_in_a_week * 4.28 -> 1 hour drift
SECONDS_IN_YEAR: int = 31_449_600  # seconds_in_a_week * 52 -> 1 day drift
WEEKS_IN_A_MONTH: int = 4
WEEKS_IN_A_YEAR: int = 52

# we'll store and process battery charge states at 5% wide 'sectors' from 0 to 99.(9)% + 1 for 100%
# What I see is that upsc battery.voltage always have precision of 0.1V.
# With the range of Lead-acid voltage of 12.85 - 10.8 == 2.05V, there is no sense to divide it further
SECTOR_WIDTH: int = 5
CHARGE_STEPS: int = 100 // SECTOR_WIDTH + 1

########################################
@dataclass
class KPowerDeviceCommons:
    """
    Used to transfer common and default settings as well as the current state between power device classes.
    Usually from KPowerDevice down to battery ones.
    This way subclasses will not require to gat hold on o parent object ref.
    """
    dev_id: str  # device ID
    calc_charge_data: bool = True
    charging_current: int = -1
    last_load: int = 0  # latest registered load level
    on_battery: bool = False
    power_factor: float = -1.0  # dev's invertor power factor. used in battery runtime calculations
    sample_interval: int = -1


########################################
class KPowerUnits(Enum):
    """Enumerations for Units of Power"""
    INVALID = -1
    VA = 0
    W = 1
    PERCENT = 2
    def __str__(self):
        return self.name

    def __repr__(self):
        return f"'{self.name}'"

    #----------------------------
    @staticmethod
    def str_to_val(val: str):
        if val.lower() == 'w':
            return KPowerUnits.W
        if val.lower() == 'va':
            return KPowerUnits.VA
        if val.lower() == 'p' or val.lower() == '%':
            return KPowerUnits.PERCENT

        return KPowerUnits.INVALID


########################################
class KBatteryTypes(Enum):
    """Enumerations for Battery Types"""
    BT_UNKNOWN = -1
    BT_LEAD = 0
    BT_LIFEPO = 1

    def __str__(self):
        return self.name.title()

    def __repr__(self):
        return f"'{self.name}'"


########################################
def bt_from_str(val: str) -> KBatteryTypes:
    if val.lower().removeprefix('bt_') in [ 'pb', 'lead' ]:
        return KBatteryTypes.BT_LEAD

    if val.lower().removeprefix('bt_') == 'lifepo':
        return KBatteryTypes.BT_LIFEPO

    return KBatteryTypes.BT_UNKNOWN


########################################
def to_watts(val: float, val_unit: KPowerUnits | None, dev_rating: float, dev_rating_unit: KPowerUnits) -> float:
    """convert power-related value to watts"""
    if val_unit == KPowerUnits.W:
        return val

    if val_unit == KPowerUnits.VA:
        return val * 0.8

    if val_unit != KPowerUnits.PERCENT or dev_rating_unit == KPowerUnits.INVALID:
        return -1.0

    # val is in percents of dev_rating
    if dev_rating_unit == KPowerUnits.VA:
        dev_rating = dev_rating * 0.8

    return dev_rating / 100.0 * val


########################################
def config_parse_power_option(csect: SectionProxy, name: str,
                              def_unit: KPowerUnits) -> tuple[float | None, KPowerUnits ]:
    """Prosess options of the kind: value,unit_of_measurement
    :param csect: config section ref
    :param name: option's name
    :param def_unit: default unit to use if not specified
    :return: (value, unit): (None, INVALID) if no option in config, (-1, INV) if value is borked
    """
    if name not in csect:
        return None, KPowerUnits.INVALID

    if -1 == csect[name].find(','):
        if csect[name][-1].lower() in '%pvw':  # percent, volt, watt
            val = csect[name].rstrip('%pvw')
            unit = KPowerUnits.str_to_val(csect[name][-1].lower())
        elif csect[name][-2:].lower() == 'va':  # VoltAmp
                val = csect[name].rstrip('va')
                unit = KPowerUnits.VA
        else:
            val = csect[name]
            unit = def_unit
    else:
        val, unit = csect[name].split(',')
        unit = KPowerUnits.str_to_val(unit)

    if unit == KPowerUnits.INVALID:
        return -1.0, KPowerUnits.INVALID

    try:
        val = float(val)
    except ValueError:
        return -1.0, KPowerUnits.INVALID

    return val, unit


########################################
def update_avg_int(old_avg: int, to_add: int, old_samples: int) -> tuple[int, int]:
    """update and return tuple: (avg, samples) for integer avg value"""
    return (old_avg * old_samples + to_add) // (old_samples + 1), old_samples + 1


########################################
def update_avg_float(old_avg: float, to_add: float, old_samples: int) -> tuple[float, int]:
    """update and return tuple: (avg, samples) for float avg value"""
    return (old_avg * old_samples + to_add) / (old_samples + 1), old_samples + 1


########################################
def validate_structure(tpl: dict, test: dict, msg_prefix: str = '') -> list[str]:
    """Will compare tested dict structure to the template
    :param tpl: template dict
    :param test: tested dict
    :param msg_prefix: message prefix in reports
    :return: list[str] - list of error messages
    """
    if msg_prefix and not msg_prefix[-1].isspace():
        msg_prefix += ' '

    if len(test) == 0:
        return [f'{msg_prefix}no data']

    messages = []
    for item in tpl.keys():
        if not item in test:
            messages.append(f'{msg_prefix}no "{item}" item')
        elif not isinstance(test[item], type(tpl[item])):
            messages.append(f'{msg_prefix}keyword "{item}" is of different type')
        elif test[item] is dict:  # dive in
            messages.extend(validate_structure(tpl[item], test[item]))

    return messages