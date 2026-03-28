#!/usr/bin/env python
"""Unit tests for kbattlead.py"""
import copy
import time
import unittest
from configparser import ConfigParser
from typing import Any
import imports.kpowerutils as kpu
from imports.kbattlead import KBattLead, _volts_at_charge, _voltage_to_charge, _v_fatal, \
                       _v_float, _v_boost, _CS_NONE, _CS_BOOST, _CS_FLOAT

# test range: used in a sector traverse checking
_test_range = [
    #0: -sector4disch, 1: v-beg, 2: v-end, 3: %-beg4disch, 4: %-end4disch, 5: %-beg4charge, 6: %-end4charge, 7: sector4charge
    ( 8, 11.95, 11.99, 40, 44, 40.3, 41.4, 8),
    ( 9, 12.00, 12.04, 45, 49, 41.7, 42.8, 8),
    (10, 12.05, 12.09, 50, 54, 43.1, 44.2, 8)
]

########################################
def _v_to_charge_linear(v: float) -> float:
    return round((v - _v_fatal) / (_v_boost - _v_fatal) * 100.0, 1)


################################################
def make_commons(dev_id: str) -> kpu.KPowerDeviceCommons:
    comm = kpu.KPowerDeviceCommons(dev_id)
    comm.charging_current = 12
    comm.last_load = 1
    comm.on_battery = False
    comm.power_factor = 0.82
    comm.sample_interval = 37
    return comm


########################################
class TestKBattLead(unittest.TestCase):
    """Test the KBattLead class. Base class KBattStats tests are in the separate module."""

    def setUp(self):
        # Create a temporary directory to act as the save path
        # TEMPLATE: device data
        self.tpl_dev_id: str = 'lead'
        self.tpl_dev_section: str = 'power.' + self.tpl_dev_id
        self.tpl_config: dict[str, Any] = {  # template .ini
            'DEFAULT': {
                'standard_v': '230,10',
                'sample_interval': '37',
            },
            self.tpl_dev_section: {
                '.mfr': 'Brutha and Co.',
                '.model': 'Om TTM001',
                'calc_charge_data': 'yes',
                'charging_current': '12',
                'load_reported_as': 'p',
                'load_zero': '120w',
                'power_rating': '2000,va',
                'power_factor': '0.82',
            },
        }

        # template battery section in .ini
        self.tpl_batt_id = 'bat1'
        self.tpl_config_battery: dict[str, str] = {
            'type': 'pb', 'vnom': '48', 'capacity_ah': '100',
        }

        # TEMPLATE: upsc data. Values will be overwritten on specific tests.
        # We need all keys to be present to pass sanity in methods
        self.tpl_upsc_data = {
            'battery_charge': '-1',
            'battery_voltage': '-1.0',
            'ups_load': '-1',
        }
    # end of setUp()

    ########################################
    def tearDown(self):
        # Remove the temporary directory
        # shutil.rmtree(self.tmpdir)
        pass


    ########################################
    def test_voltage_to_charge(self):
        """Test of _voltage_to_charge() function alone"""

        test_pairs: list[tuple[float, float]] = [  # (v, charge %)
            (10.0, 0.0), (11.51, 10.0), (11.66, 20.0), (11.81, 30.0), (11.95, 40.0), (12.05, 50.0),
            (12.15, 60.0), (12.3, 70.0), (12.5, 80.0), (12.75, 90.0), (12.8, 99.0), (12.85, 100.0),
            (13.0, 100.0)]

        for p in test_pairs:
            self.assertEqual(p[1], _voltage_to_charge(p[0]), f'{p[0]}V -> {p[1]}%: ')


    ########################################
    def _make_class(self, saved_stats: dict | None = None) -> KBattLead:
        """A helper to get all things pre-initialized for the majority of tests"""
        self.tpl_config['battery.' + self.tpl_batt_id] = self.tpl_config_battery

        conf = ConfigParser()
        conf.read_dict(self.tpl_config)
        return KBattLead(self.tpl_batt_id, make_commons(self.tpl_dev_id), conf, saved_stats)


    ########################################
    def test_init_no_old_data_load(self):
        """Test creating default data."""
        kb = self._make_class(None)

        self.assertFalse( kb.invalid )
        self.assertEqual(0, len(kb.messages) )
        self.assertEqual( 4, kb._pack_size )
        # most of the structural settings are tested in KBattStats


    ########################################
    def test_init_with_old_data_load(self):
        """If a matching file exists it is loaded correctly."""
        # Create a matching file
        t = int(time.time())
        saved = {  # KBatteries slip only the 'batteries' dict down to each KBatt* object
            self.tpl_batt_id: {
                'type': str(kpu.bt_from_str( self.tpl_config_battery['type'] )),
                'vnom': int(self.tpl_config_battery['vnom']),
                'capacity_ah': int(self.tpl_config_battery['capacity_ah']),
                'messages': [],
                'registered': [t - kpu.SECONDS_IN_A_WEEK, 'Once upon a time'],
                'health': {
                    'cycles': [0, 0, 0],
                    'status': "OK",
                    'tbf': -1,
                    'wellness': 100,
                },
                'weekly': {
                    'start_ts': [123],
                    'discharge_speed_avg': [[0.5] * kpu.CHARGE_STEPS],
                    'discharge_speed_samples': [[1] * kpu.CHARGE_STEPS],
                    'charge_speed_avg': [[1.0] * kpu.CHARGE_STEPS],
                    'charge_speed_samples': [[1] * kpu.CHARGE_STEPS],
                },
            },
        }

        kb = self._make_class(saved)

        self.assertFalse( kb.invalid )
        self.assertEqual( 0, len(kb.messages) )
        self.assertEqual( 4, kb._pack_size )


    ########################################
    def test_get_charge_percent_no_calc_on_discharge(self):
        """Test of get_charge_percent() without 'calculate' option"""
        self.tpl_config_battery['calc_charge_data'] = 'false'
        kb = self._make_class()

        self.assertFalse( kb._calc_charge_data )
        self.assertTrue(kb.commons.calc_charge_data)

        upsc_data = self.tpl_upsc_data.copy()

        upsc_data['battery_charge'] = '12.345'
        self.assertEqual( 12.3, kb._determine_charge(upsc_data, True), 'No calc, rounding')

        upsc_data['battery_charge'] = '12.36'
        self.assertEqual( 12.4, kb._determine_charge(upsc_data, True), 'No calc, rounding')


    ########################################
    def test_get_charge_percent_with_calc_on_discharge(self):
        """Test of get_charge_percent(), calculating from voltage at DISCHARGE time.
        just see if this works at the top level. We already tested _voltage_to_charge()"""

        kb = self._make_class()

        self.assertTrue( kb._calc_charge_data )
        self.assertTrue(kb.commons.calc_charge_data)

        kb._was_discharging = True

        for tp in [ (11.15, 4.9), (12.05, 50.0), (13.0, 100.0) ]:
            self.tpl_upsc_data['battery_voltage'] = str(tp[0] * kb._pack_size)
            self.assertEqual(kb._determine_charge(self.tpl_upsc_data, True), tp[1], 'Calculated')


    ########################################
    def test_get_charge_percent_with_calc_on_charge(self):
        """Test of get_charge_percent(), calculating from voltage at CHARGING time.
        The plan is to chack if it correctly switches on voltage CA/CV/float transitions"""
        kb = self._make_class()

        self.assertTrue( kb._calc_charge_data )
        self.assertTrue( kb.commons.calc_charge_data )

        # Checking w/o transition over boost
        kb._charge_state = _CS_BOOST
        kb._was_discharging = False
        kb._last_v = 11.0
        for tp in [ (11.15, 18.1), (12.05, 43.1), (13.0, 69.4) ]:
            self.tpl_upsc_data['battery_voltage'] = str(tp[0] * kb._pack_size)
            self.assertEqual(kb._determine_charge(self.tpl_upsc_data, False),
                             tp[1], 'Calculated-pre-boost')
            self.assertEqual(kb._charge_state, _CS_BOOST)

        kb._last_v = 11.0
        v = 14.0  # _v_boost - 0.1 -> 14.0 == 97%
        self.tpl_upsc_data['battery_voltage'] = str(v * kb._pack_size)
        self.assertEqual(kb._determine_charge(self.tpl_upsc_data, False),
                         _v_to_charge_linear(v), 'Calculated-before-boost')
        self.assertEqual(kb._charge_state, _CS_BOOST)

        kb._last_v = 14.0
        v = _v_float  # should change to FLOAT/100%
        self.tpl_upsc_data['battery_voltage'] = str(v * kb._pack_size)
        self.assertEqual(kb._determine_charge(self.tpl_upsc_data, False),
                         100.0, 'Calculated-past-boost')
        self.assertEqual(kb._charge_state, _CS_FLOAT)

        kb._last_v = _v_float
        v = _v_float - 0.5  # should change to BOOST
        self.tpl_upsc_data['battery_voltage'] = str(v * kb._pack_size)
        self.assertAlmostEqual(kb._determine_charge(self.tpl_upsc_data, False),
                               _v_to_charge_linear(v), 1, 'Calc-ret-to-pre-boost')
        self.assertEqual(kb._charge_state, _CS_BOOST)


    ########################################
    def _initialize_for_stats_update(self, upsc_data: dict, v: float, discharging: bool) -> KBattLead:
        """Initialize common things that are used to test stats_update()
        Keep it minimal, fool! Or universe will report strange numbers."""
        kb = self._make_class()
        kb._calc_charge_data = True
        kb.commons.sample_interval = 42
        upsc_data['battery_voltage'] = v * kb._pack_size

        kb._was_discharging = discharging
        kb._last_v = v  # last voltage we have seen when OB
        charge = kb._determine_charge(upsc_data, discharging)
        kb._charge_sector = int(charge / kpu.SECTOR_WIDTH)
        kb._charge_sector_start = charge
        return kb


    ########################################
    def test_update_stats_voltage_jitter_discharge(self):
        """Tests for circumventing voltage jitter (up) on discharge"""
        # set initial charge in the middle of 50-55%
        v_range = (_volts_at_charge[6] - _volts_at_charge[5]) / (10.0 / kpu.SECTOR_WIDTH)
        v = _volts_at_charge[5] + v_range / 2.0
        kb = self._initialize_for_stats_update(self.tpl_upsc_data.copy(), v, True)
        sector = kb._charge_sector

        upsc_data = self.tpl_upsc_data.copy()
        kb.commons.last_load = 23
        upsc_data['battery_voltage'] = str((v - 0.01) * kb._pack_size)  # going down first
        kb.commons.on_battery = True
        kb._charge_state = _CS_NONE  # stub, doesn't matter

        kb.process_upsc_data(upsc_data)  # making initial fix
        self.assertEqual(sector, kb._charge_sector)  # should remain in a same sector
        self.assertEqual(True, kb._was_discharging)  # no state transition
        self.assertEqual(23.0, kb._load_avg)

        # testing that there will be no transitions
        kb.commons.last_load = 45
        # what matters is that it is higher than last
        upsc_data['battery_voltage'] = str(13.0 * kb._pack_size)

        kb.process_upsc_data(upsc_data)  # recording surge
        # stats updated correctly?
        self.assertEqual(sector, kb._charge_sector)  # should remain in a same sector
        self.assertEqual(2 * kb.commons.sample_interval, kb._time_in_charge_sector)
        self.assertAlmostEqual((23 + 45) / 2, kb._load_avg, 2)
        self.assertEqual(2, kb._state_samples)


    ########################################
    def test_update_stats_voltage_jitter_charge(self):
        """Tests for circumventing voltage jitter (down) on CHARGE"""
        # set charge to around 52.5% -> 12.05 + (12.15 - 12.05 / 4.0) -> 12.075
        v = 12.07
        kb = self._initialize_for_stats_update(self.tpl_upsc_data.copy(), v, False)

        upsc_data = self.tpl_upsc_data.copy()
        kb.commons.last_load = 23
        upsc_data['battery_voltage'] = str((v + 0.01) * kb._pack_size)  # going UP first
        kb._charge_state = _CS_NONE  # stub, doesn't matter

        kb.process_upsc_data( upsc_data )  # making initial fix
        sector = kb._charge_sector

        self.assertFalse( kb._was_discharging )  # no state transition
        self.assertEqual( 23.0, kb._load_avg )

        # testing that there will be no transitions
        kb.commons.last_load = 456
        # what matters is that it is higher than last
        upsc_data['battery_voltage'] = str(10.0 * kb._pack_size)

        kb.process_upsc_data(upsc_data)  # recording surge

        # stats updated correctly?
        self.assertEqual(sector, kb._charge_sector)  # should remain in a same sector
        self.assertEqual(2 * kb.commons.sample_interval, kb._time_in_charge_sector)
        self.assertAlmostEqual((23 + 456) / 2, kb._load_avg, 2)
        self.assertEqual(2, kb._state_samples)


    ########################################
    def test_update_stats_transit_sector_partial(self):
        """Tests that negligible amount of data from the old charge sector is not recorded
        Current approach is to throw away data where is less than 50% of sector range covered"""
        # _test_range[N] is a tuple of (sector, V-begin, V-end, begin%, end%)
        tr_index = 2
        # set starting charge for this sector to 30%
        v = _test_range[tr_index][1] + (_test_range[tr_index][2] - _test_range[tr_index][1]) / 3.0
        kb = self._initialize_for_stats_update( self.tpl_upsc_data.copy(), v, True)
        sector = kb._charge_sector
        w = kb._pdata['weekly']

        upsc_data = self.tpl_upsc_data.copy()
        kb.commons.last_load = 12
        kb.commons.on_battery = True

        v = _test_range[tr_index][1]  # get down to lower bound
        upsc_data['battery_voltage'] = str(v * kb._pack_size)

        kb.process_upsc_data(upsc_data)  # making initial fix

        self.assertEqual(sector, kb._charge_sector)

        tr_index -= 1
        v = _test_range[tr_index][2]  # switch to other sector
        upsc_data['battery_voltage'] = str(v * kb._pack_size)

        kb.process_upsc_data(upsc_data)

        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])
        # make sure there was no update of a partial sector
        for k in ['discharge_speed', 'charge_speed']:
            self.assertEqual(w[k + '_avg'][0][sector],0.0)
            self.assertEqual(w[k + '_samples'][0][sector], 0)


    ########################################
    def test_update_stats_transit_sector_full_on_discharge(self):
        """Tests transit through a whole sector"""
        # _test_range[N] is a tuple of
        # 0: -sector4disch, 1: v-beg, 2: v-end, 3: %-beg4disch, 4: %-end4disch, 5: %-beg4charge, 6: %-end4charge, 7: sector4charge
        tr_index = 2
        v = _test_range[tr_index][1] + 0.01  # start slightly above the lower bound

        kb = self._initialize_for_stats_update( self.tpl_upsc_data.copy(), v, True)
        kb.commons.last_load = 17
        kb.commons.on_battery = True

        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])  # check if test data is still correct
        w = kb._pdata['weekly']

        v = _test_range[tr_index][1]  # continue in this sector
        upsc_data = self.tpl_upsc_data.copy()
        upsc_data['battery_voltage'] = str(v * kb._pack_size)

        kb.process_upsc_data(upsc_data)  # making initial fix

        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])
        self.assertEqual(1, kb._state_samples)
        prev_sector = kb._charge_sector

        # transit to a middle zone
        tr_index -= 1
        v = _test_range[tr_index][2]  # high limit
        count = 0
        while v >= _test_range[tr_index][1]:
            count += 1
            upsc_data['battery_voltage'] = str(v * kb._pack_size)
            kb.process_upsc_data(upsc_data)
            self.assertEqual(kb._charge_sector, _test_range[tr_index][0], f'Count: {count}')
            v -= 0.01

        self.assertEqual(count, kb._state_samples)
        for k in ['discharge_speed', 'charge_speed']:  # should be no stats recorded
            self.assertEqual(0.0, w[k + '_avg'][0][prev_sector])
            self.assertEqual(0, w[k + '_samples'][0][prev_sector])

        # transit to a final sector
        prev_sector = kb._charge_sector
        tr_index -= 1
        v = _test_range[tr_index][2]  # high limit
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.process_upsc_data(upsc_data)
        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])

        # make sure there have been update of a full sector
        self.assertEqual(0.0, w['charge_speed_avg'][0][prev_sector])
        self.assertEqual(0, w['charge_speed_samples'][0][prev_sector])

        # due to approximation of timings, there will be a slight difference
        self.assertAlmostEqual(float(kb.commons.last_load) * count * kb.commons.sample_interval /
                         w['discharge_speed_avg'][0][prev_sector], 1.0, 1)
        self.assertEqual(1, w['discharge_speed_samples'][0][prev_sector])


    ########################################
    def test_update_stats_ob_ol_transits(self):
        """ Test for state transition from OB to OL and back """
        # test OB-OL-OB

        # _test_range[N] is a tuple of
        # 0: -sector4disch, 1: v-beg, 2: v-end, 3: %-beg4disch, 4: %-end4disch, 5: %-beg4charge, 6: %-end4charge, 7: sector4charge
        tr_index = 1
        v = _test_range[tr_index][2]  # start at the end of sector

        kb = self._initialize_for_stats_update( self.tpl_upsc_data.copy(), v, True)
        kb.commons.last_load = 26
        kb.commons.on_battery = True

        self.assertEqual(_test_range[tr_index][0], kb._charge_sector)  # check if test data is still correct
        w = kb._pdata['weekly']

        # get down to 25%, so it will be recorded
        v = _test_range[tr_index][1] + (_test_range[tr_index][2] - _test_range[tr_index][1]) / 4.0
        upsc_data = self.tpl_upsc_data.copy()
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.process_upsc_data(upsc_data)  # making initial fix

        self.assertEqual( _test_range[tr_index][0], kb._charge_sector )
        self.assertEqual( 1, kb._state_samples )
        self.assertTrue( kb._was_discharging )
        prev_sector = kb._charge_sector

        # transit to OL
        kb.commons.on_battery = False
        v = _test_range[tr_index][1] + 0.01  # start at the bottom again
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.process_upsc_data(upsc_data)
        self.assertEqual(_test_range[tr_index][7], kb._charge_sector)
        self.assertFalse(kb._was_discharging)
        # got initial OB records
        self.assertNotEqual(w['discharge_speed_avg'][0][prev_sector], 0.0)
        self.assertNotEqual(w['discharge_speed_samples'][0][prev_sector], 0)

        # 2nd update with full range
        v = _test_range[tr_index][2]
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.process_upsc_data(upsc_data)
        prev_sector = kb._charge_sector

        # no record at this time
        self.assertEqual(w['charge_speed_avg'][0][kb._charge_sector], 0.0)
        self.assertEqual(w['charge_speed_samples'][0][kb._charge_sector], 0)

        # finally get back to OB again
        kb.commons.on_battery = True
        v = _test_range[tr_index][2]
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.process_upsc_data(upsc_data)

        self.assertEqual(_test_range[tr_index][0], kb._charge_sector)
        self.assertTrue(kb._was_discharging)
        self.assertNotEqual(w['charge_speed_avg'][0][prev_sector], 0.0)
        self.assertNotEqual(w['charge_speed_samples'][0][prev_sector], 0)


    ########################################
    def test_calc_battery_health(self):
        """Test for calc_battery_health()"""

        comm = kpu.KPowerDeviceCommons(self.tpl_dev_id)
        comm.charging_current = 20
        comm.last_load = 1
        comm.on_battery = False
        comm.power_factor = 0.8
        comm.sample_interval = 37

        conf_init = copy.deepcopy(self.tpl_config)
        conf_init['battery.' + self.tpl_batt_id] = self.tpl_config_battery
        conf = ConfigParser()
        conf.read_dict(conf_init)

        kb = KBattLead(self.tpl_batt_id, comm, conf, None)

        # 1. Low samples

        pd = kb._pdata
        pd['health']['cycles'] = [150, 100, 50]  # 1-150/6000-100/3000-50/500 == 0.84
        bdh = kb.get_battery_health()
        self.assertIn('OK', bdh['status'])

        pd['health']['cycles'] = [250, 200, 80]  # 1-250/6000-200/3000-80/500 == 0.73
        bdh = kb.get_battery_health()
        self.assertIn('Aged', bdh['status'])

        pd['health']['cycles'] = [500, 500, 150]  # 1-500/6000-500/3000-150/500 == 0.45
        bdh = kb.get_battery_health()
        self.assertIn('Fail', bdh['status'])

        pd['health']['cycles'] = [800, 800, 250]  # 1-800/6000-800/3000-250/500 == 0.1
        bdh = kb.get_battery_health()
        self.assertIn('Trash', bdh['status'])

        # 2. From weekly data
        kb._pdata['weekly']['start_ts'][0] -= kpu.SECONDS_IN_A_WEEK + 1
        kb._weekly_shift()  # +1 week
        # reset cycles to more relaxed state
        pd['health']['cycles'] = [300, 200, 10]  # 1-300/6000-200/3000-10/500 == 0.86
        for week in range(2):
            # set 0% and 100% slot to a very low value that should be ignored
            kb._pdata['weekly']['discharge_speed_avg'][week][0] = 1
            kb._pdata['weekly']['discharge_speed_avg'][week][kpu.CHARGE_STEPS - 1] = 1
            for cs in range(1, kpu.CHARGE_STEPS - 1, 2 * (kpu.CHARGE_STEPS - 2) // 10):  # fill at least 10 slots
                kb._pdata['weekly']['discharge_speed_avg'][week][cs] = kb._ideal_sector_speed

        bdh = kb.get_battery_health()
        self.assertIn('OK', bdh['status'])

        # setting speeds to 75%
        isp = kb._ideal_sector_speed // 100
        for week in range(2):
            for cs in range(1, kpu.CHARGE_STEPS - 1, 2 * (kpu.CHARGE_STEPS - 2) // 10):  # fill at least 10 slots
                kb._pdata['weekly']['discharge_speed_avg'][week][cs] = isp * 75

        bdh = kb.get_battery_health()
        self.assertIn('Aged', bdh['status'])

        # setting speeds to 38%
        for week in range(2):
            for cs in range(1, kpu.CHARGE_STEPS - 1, 2 * (kpu.CHARGE_STEPS - 2) // 10):  # fill at least 10 slots
                kb._pdata['weekly']['discharge_speed_avg'][week][cs] = isp * 38

        bdh = kb.get_battery_health()
        self.assertIn('Fail', bdh['status'])


########################################
if __name__ == '_main_':
    unittest.main()
