#!/usr/bin/env python
"""
Unit tests for kbattlead.py
"""
import copy
import os
import json
import shutil
import tempfile
import time
import unittest
# from unittest import mock

from imports.kbattstats import CHARGE_STEPS, BT_LEAD, SECTOR_WIDTH
from imports.kbattlead import KBattLead, _volts_at_charge, _voltage_to_charge, _v_fatal, \
                       _v_float, _v_boost, _CS_NONE, _CS_BOOST, _CS_FLOAT


# test range
_test_range = [
    #0: -sector4disch, 1: v-beg, 2: v-end, 3: %-beg4disch, 4: %-end4disch, 5: %-beg4charge, 6: %-end4charge, 7: sector4charge
    ( 8, 11.95, 11.99, 40, 44, 40.3, 41.4, 8),
    ( 9, 12.00, 12.04, 45, 49, 41.7, 42.8, 8),
    (10, 12.05, 12.09, 50, 54, 43.1, 44.2, 8)
]
########################################
def _v_to_charge_linear(v: float) -> float:
    return round((v - _v_fatal) / (_v_boost - _v_fatal) * 100.0, 1)


########################################
class TestKBattLead(unittest.TestCase):
    """
    Test the KBattLead class. Base class tests are in the separate module.
    """

    def setUp(self):
        # Create a temporary directory to act as the save path
        self.tmpdir = tempfile.mkdtemp()
        # TEMPLATE: device data
        self.tpl_dev_data = {
            'dev_id': 'test123',
            'batt_type': 'pb',
            'batt_vnom': 48,
            'batt_cap': 230,
            'calc_charge_data': True,
            'power_rating': 2000,
            'power_rating_unit': 'va',
            'power_factor': 0.8,
            'load_reported_as': 'w',
        }
        # TEMPLATE: upsc data
        self.tpl_upsc_data = {
            'battery_charge': '-1',
            'battery_voltage': '-1.0',
            'ups_load': '-1',
        }


    ########################################
    def tearDown(self):
        # Remove the temporary directory
        shutil.rmtree(self.tmpdir)


    ########################################
    def _validate_structure(self, kb: KBattLead):
        # Basic sanity checks
        self.assertFalse(kb.invalid)
        self.assertEqual(len(kb._pdata['messages']), 0)

        self.assertEqual(kb.type, BT_LEAD)

        self.assertIn('main', kb._pdata['batteries'])
        for key in ['batt_type', 'batt_vnom', 'batt_cap']:
            self.assertIn(key, kb._pdata['batteries']['main'])


    ########################################
    def _get_stats_file_name(self, dd: dict) -> str:
        return os.path.join(self.tmpdir, 'mqtt-power.' + dd['dev_id'] + '.json')


    ########################################
    def test_init_no_old_data_load(self):
        """Test creating default data."""
        dd = copy.deepcopy(self.tpl_dev_data)
        kb = KBattLead(self.tmpdir, dd)

        self._validate_structure(kb)


    ########################################
    def test_init_with_old_data_load(self):
        """If a matching file exists it is loaded correctly."""
        # Create a matching file
        saved = {
            'dev_id': self.tpl_dev_data['dev_id'],
            'ts': 1_000_000,
            'started': 1_000_000,
            'messages': [],
            'batteries': {
                'main': {
                    'batt_type': self.tpl_dev_data['batt_type'],
                    'batt_vnom': self.tpl_dev_data['batt_vnom'],
                    'batt_cap': self.tpl_dev_data['batt_cap'],
                }
            },
            'weekly': {
                'start_ts': [123],
                'discharge_speed_avg': [[0.5] * CHARGE_STEPS],
                'discharge_speed_samples': [[1] * CHARGE_STEPS],
                'charge_speed_avg': [[1.5] * CHARGE_STEPS],
                'charge_speed_samples': [[1] * CHARGE_STEPS],
                'blackouts_count': [5],
                'blackouts_time': [2.5],
            },
            'hourly_load_avg': [[222] * 24],
            'hourly_load_samples': [[5] * 24],
        }

        file_name = self._get_stats_file_name(saved)
        with open(file_name, 'w', encoding='utf-8') as fh:
            json.dump(saved, fh)

        dd = copy.deepcopy(self.tpl_dev_data)
        kb = KBattLead(self.tmpdir, dd)
        self._validate_structure(kb)

        # for now KBattLead will not save additional things


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
    def test_get_charge_percent_no_calc(self):
        """Test of get_charge_percent() without 'calculate' option"""
        dd = copy.deepcopy(self.tpl_dev_data)
        # dd['calc_charge_data'] = 'False'
        del dd['calc_charge_data']
        kb = KBattLead(self.tmpdir, dd)
        self.assertEqual(kb._calc_charge, False)

        upsc_data = copy.deepcopy(self.tpl_upsc_data)
        upsc_data['battery_charge'] = '12.345'
        upsc_data['battery_voltage'] = '-1'

        self.assertEqual(kb._determine_charge(upsc_data, True), 12.3, 'No calc, rounding')

        upsc_data['battery_charge'] = '12.36'
        self.assertEqual(kb._determine_charge(upsc_data, True), 12.4, 'No calc, rounding')


    ########################################
    def test_get_charge_percent_with_calc_on_discharge(self):
        """Test of get_charge_percent(), calculating from voltage at DISCHARGE time.
        just see if this works at the top level. We already tested _voltage_to_charge()"""

        dd = copy.deepcopy(self.tpl_dev_data)
        dd['calc_charge_data'] = 'true'
        kb = KBattLead(self.tmpdir, dd)
        self.assertEqual(kb._calc_charge, True)

        kb._discharging = True
        upsc_data = copy.deepcopy(self.tpl_upsc_data)

        for tp in [ (11.15, 4.9), (12.05, 50.0), (13.0, 100.0) ]:
            upsc_data['battery_voltage'] = str(tp[0] * kb._pack_size)
            self.assertEqual(kb._determine_charge(upsc_data, True), tp[1], 'Calculated')


    ########################################
    def test_get_charge_percent_with_calc_on_charge(self):
        """Test of get_charge_percent(), calculating from voltage at CHARGING time.
        The plan is to chack if it correctly switches on voltage CA/CV/float transitions"""
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['calc_charge_data'] = 'true'
        kb = KBattLead(self.tmpdir, dd)
        self.assertEqual(kb._calc_charge, True)

        upsc_data = copy.deepcopy(self.tpl_upsc_data)

        # Checking w/o transition over boost
        kb._charge_state = _CS_BOOST
        kb._discharging = False
        kb._last_ob_v = 11.0
        for tp in [ (11.15, 18.1), (12.05, 43.1), (13.0, 69.4) ]:
            upsc_data['battery_voltage'] = str(tp[0] * kb._pack_size)
            self.assertEqual(kb._determine_charge(upsc_data, False), tp[1], 'Calculated-pre-boost')
            self.assertEqual(kb._charge_state, _CS_BOOST)

        kb._last_ob_v = 11.0
        v = 14.0  # _v_boost - 0.1 -> 14.0 == 97%
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        self.assertEqual(kb._determine_charge(upsc_data, False), _v_to_charge_linear(v), 'Calculated-before-boost')
        self.assertEqual(kb._charge_state, _CS_BOOST)

        kb._last_ob_v = 14.0
        v = _v_float  # should change to FLOAT/100%
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        self.assertEqual(kb._determine_charge(upsc_data, False), 100.0, 'Calculated-past-boost')
        self.assertEqual(kb._charge_state, _CS_FLOAT)

        kb._last_ob_v = _v_float
        v = _v_float - 0.5  # should change to BOOST
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        self.assertAlmostEqual(kb._determine_charge(upsc_data, False), _v_to_charge_linear(v), 1, 'Calc-ret-to-pre-boost')
        self.assertEqual(kb._charge_state, _CS_BOOST)


    ########################################
    def _initialize_stats(self, dd: dict, v: float, discharging: bool) -> KBattLead:
        """Initialize common things that are used to test stats_update()
        Keep it minimal, fool! Or universe will report strange numbers."""
        dd['sample_interval'] = 42
        kb = KBattLead(self.tmpdir, dd)
        dd['battery_voltage'] = v * kb._pack_size

        kb._discharging = discharging
        kb._last_ob_v = v  # last voltage we seen OB
        charge = kb._determine_charge(dd, discharging)
        kb._charge_sector = int(charge / SECTOR_WIDTH)
        kb._charge_sector_start = charge
        return kb


    ########################################
    def test_update_stats_voltage_jitter_discharge(self):
        """Tests for circumventing voltage jitter (up) on discharge"""
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['sample_interval'] = 42
        # set initial charge in the middle of 50-55%
        v_range = (_volts_at_charge[6] - _volts_at_charge[5]) / (10.0 / SECTOR_WIDTH)
        v = _volts_at_charge[5] + v_range / 2.0
        kb = self._initialize_stats(dd, v, True)
        sector = kb._charge_sector

        upsc_data = copy.deepcopy(self.tpl_upsc_data)
        upsc_data['ups_load'] = '23'
        upsc_data['ups_status'] = 'apparently ob'  # should detect OB
        upsc_data['battery_voltage'] = str((v - 0.01) * kb._pack_size)  # going down first
        kb._charge_state = _CS_NONE  # stub, doesn't matter

        kb.update_stats(upsc_data)  # making initial fix
        self.assertEqual(sector, kb._charge_sector)  # should remain in a same sector
        self.assertEqual(True, kb._discharging)  # no state transition
        self.assertEqual(23.0, kb._load_avg)

        # testing that there will be no transitions
        upsc_data['ups_load'] = '45'
        upsc_data['ups_status'] = 'as ob as can be'  # should detect OB
        # what matters is that it is higher than last
        upsc_data['battery_voltage'] = str(13.0 * kb._pack_size)

        kb.update_stats(upsc_data)  # recording surge

        # stats updated correctly?
        self.assertEqual(sector, kb._charge_sector)  # should remain in a same sector
        self.assertEqual(2 * dd['sample_interval'], kb._time_in_charge_sector)
        self.assertAlmostEqual((23 + 45) / 2, kb._load_avg, 2)
        self.assertEqual(2, kb._state_samples)


    ########################################
    def test_update_stats_voltage_jitter_charge(self):
        """Tests for circumventing voltage jitter (down) on CHARGE"""
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['sample_interval'] = 42
        # set charge to around 52.5% -> 12.05 + (12.15 - 12.05 / 4.0) -> 12.075
        v = 12.07
        kb = self._initialize_stats(dd, v, False)

        upsc_data = copy.deepcopy(self.tpl_upsc_data)
        upsc_data['ups_load'] = '23'
        upsc_data['ups_status'] = 'Obnoxious'  # should detect charging state
        upsc_data['battery_voltage'] = str((v + 0.01) * kb._pack_size)  # going UP first
        kb._charge_state = _CS_NONE  # stub, doesn't matter

        kb.update_stats(upsc_data)  # making initial fix
        sector = kb._charge_sector

        self.assertEqual(False, kb._discharging)  # no state transition
        self.assertEqual(23.0, kb._load_avg)

        # testing that there will be no transitions
        upsc_data['ups_load'] = '456'
        upsc_data['ups_status'] = 'NOOB'  # should NOT detect OB
        # what matters is that it is higher than last
        upsc_data['battery_voltage'] = str(10.0 * kb._pack_size)

        kb.update_stats(upsc_data)  # recording surge

        # stats updated correctly?
        self.assertEqual(sector, kb._charge_sector)  # should remain in a same sector
        self.assertEqual(2 * dd['sample_interval'], kb._time_in_charge_sector)
        self.assertAlmostEqual((23 + 456) / 2, kb._load_avg, 2)
        self.assertEqual(2, kb._state_samples)


    ########################################
    def test_update_stats_transit_sector_partial(self):
        """Tests that negligible amount of data from the old charge sector is not recorded
        Current approach is to throw away data where is less than 50% of sector range covered"""
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['sample_interval'] = 42

        # _test_range[N] is a tuple of (sector, V-begin, V-end, begin%, end%)
        tr_index = 2
        # set starting charge for this sector to 30%
        v = _test_range[tr_index][1] + (_test_range[tr_index][2] - _test_range[tr_index][1]) / 3.0
        kb = self._initialize_stats(dd, v, True)
        sector = kb._charge_sector
        w = kb._pdata['weekly']

        upsc_data = copy.deepcopy(self.tpl_upsc_data)
        upsc_data['ups_load'] = '12'
        upsc_data['ups_status'] = 'OB'

        v = _test_range[tr_index][1]  # get down to lower bound
        upsc_data['battery_voltage'] = str(v * kb._pack_size)

        kb.update_stats(upsc_data)  # making initial fix

        self.assertEqual(sector, kb._charge_sector)

        tr_index -= 1
        v = _test_range[tr_index][2]  # switch to other sector
        upsc_data['battery_voltage'] = str(v * kb._pack_size)

        kb.update_stats(upsc_data)

        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])
        # make sure there was no update of a partial sector
        for k in ['discharge_speed', 'charge_speed']:
            self.assertEqual(w[k + '_avg'][0][sector],0.0)
            self.assertEqual(w[k + '_samples'][0][sector], 0)


    ########################################
    def test_update_stats_transit_sector_full_on_discharge(self):
        """Tests transit through a whole sector"""
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['sample_interval'] = 42

        upsc_data = copy.deepcopy(self.tpl_upsc_data)
        upsc_data['ups_load'] = '17'
        upsc_data['ups_status'] = 'OB'

        # _test_range[N] is a tuple of
        # 0: -sector4disch, 1: v-beg, 2: v-end, 3: %-beg4disch, 4: %-end4disch, 5: %-beg4charge, 6: %-end4charge, 7: sector4charge
        tr_index = 2
        v = _test_range[tr_index][1] + 0.01  # start slightly above the lower bound
        kb = self._initialize_stats(dd, v, True)
        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])  # check if test data is still correct
        w = kb._pdata['weekly']

        v = _test_range[tr_index][1]  # continue in this sector
        upsc_data['battery_voltage'] = str(v * kb._pack_size)

        kb.update_stats(upsc_data)  # making initial fix

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
            kb.update_stats(upsc_data)
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
        kb.update_stats(upsc_data)
        self.assertEqual(kb._charge_sector, _test_range[tr_index][0])

        # make sure there have been update of a full sector
        self.assertEqual(0.0, w['charge_speed_avg'][0][prev_sector])
        self.assertEqual(0, w['charge_speed_samples'][0][prev_sector])

        # due to approximation of timings, there will be a slight difference
        self.assertAlmostEqual(float(upsc_data['ups_load']) * count * dd['sample_interval'] /
                         w['discharge_speed_avg'][0][prev_sector], 1.0, 1)
        self.assertEqual(1, w['discharge_speed_samples'][0][prev_sector])


    ########################################
    def test_update_stats_ob_ol_transits(self):
        """ Test for state transition from OB to OL and back """
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['sample_interval'] = 42

        upsc_data = copy.deepcopy(self.tpl_upsc_data)
        upsc_data['ups_load'] = '26'

        # test OB-OL-OB
        upsc_data['ups_status'] = 'OB'

        # _test_range[N] is a tuple of
        # 0: -sector4disch, 1: v-beg, 2: v-end, 3: %-beg4disch, 4: %-end4disch, 5: %-beg4charge, 6: %-end4charge, 7: sector4charge
        tr_index = 1
        v = _test_range[tr_index][2]  # start at the end of sector
        kb = self._initialize_stats(dd, v, True)
        self.assertEqual(_test_range[tr_index][0], kb._charge_sector)  # check if test data is still correct
        w = kb._pdata['weekly']

        # get down to 25%, so it will be recorded
        v = _test_range[tr_index][1] + (_test_range[tr_index][2] - _test_range[tr_index][1]) / 4.0
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.update_stats(upsc_data)  # making initial fix

        self.assertEqual(_test_range[tr_index][0], kb._charge_sector)
        self.assertEqual(kb._state_samples, 1)
        self.assertTrue(kb._discharging)
        prev_sector = kb._charge_sector

        # transit to OL
        upsc_data['ups_status'] = 'Got juice'
        v = _test_range[tr_index][1] + 0.01  # start at the bottom again
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.update_stats(upsc_data)
        self.assertEqual(_test_range[tr_index][7], kb._charge_sector)
        self.assertFalse(kb._discharging)
        # got initial OB records
        self.assertNotEqual(w['discharge_speed_avg'][0][prev_sector], 0.0)
        self.assertNotEqual(w['discharge_speed_samples'][0][prev_sector], 0)

        # 2nd update with full range
        v = _test_range[tr_index][2]
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.update_stats(upsc_data)
        prev_sector = kb._charge_sector

        # no record at this time
        self.assertEqual(w['charge_speed_avg'][0][kb._charge_sector], 0.0)
        self.assertEqual(w['charge_speed_samples'][0][kb._charge_sector], 0)

        # finally get back to OB again
        upsc_data['ups_status'] = 'OB-vious'
        v = _test_range[tr_index][2]
        upsc_data['battery_voltage'] = str(v * kb._pack_size)
        kb.update_stats(upsc_data)

        self.assertEqual(_test_range[tr_index][0], kb._charge_sector)
        self.assertTrue(kb._discharging)
        self.assertNotEqual(w['charge_speed_avg'][0][prev_sector], 0.0)
        self.assertNotEqual(w['charge_speed_samples'][0][prev_sector], 0)


    ########################################
    def test_calc_battery_health(self):
        """Test for calc_battery_health()"""

        # prepare common device data
        dd = copy.deepcopy(self.tpl_dev_data)
        dd['power_rating'] = 2000
        dd['power_rating_unit'] = 'va'
        dd['power_factor'] = 0.8
        dd['load_reported_as'] = 'p'

        # 1. Low samples
        kb = KBattLead(self.tmpdir, dd)
        bd = kb._pdata['batteries']['main']
        bd['health']['cycles'] = [150, 100, 50]  # 1-150/6000-100/3000-50/500 == 0.84
        bdh = kb.get_battery_health('')
        self.assertIn('OK', bdh['status'])

        bd['health']['cycles'] = [250, 200, 80]  # 1-250/6000-200/3000-80/500 == 0.73
        bdh = kb.get_battery_health('')
        self.assertIn('Aged', bdh['status'])

        bd['health']['cycles'] = [500, 500, 150]  # 1-500/6000-500/3000-150/500 == 0.45
        bdh = kb.get_battery_health('')
        self.assertIn('Fail', bdh['status'])

        bd['health']['cycles'] = [800, 800, 250]  # 1-800/6000-800/3000-250/500 == 0.1
        bdh = kb.get_battery_health('')
        self.assertIn('Trash', bdh['status'])

        # 2. From weekly data
        kb._weekly_shift()  # +1 week
        # reset cycles to more relaxed state
        bd['health']['cycles'] = [300, 200, 10]  # 1-300/6000-200/3000-10/500 == 0.86
        for week in range(2):
            # set 0% and 100% slot to a very low value that should be ignored
            kb._pdata['weekly']['discharge_speed_avg'][week][0] = 1
            kb._pdata['weekly']['discharge_speed_avg'][week][CHARGE_STEPS - 1] = 1
            for cs in range(1, CHARGE_STEPS - 1, 2 * (CHARGE_STEPS - 2) // 10):  # fill at least 10 slots
                kb._pdata['weekly']['discharge_speed_avg'][week][cs] = bd['ideal_sector_speed']

        bdh = kb.get_battery_health('')
        self.assertIn('OK', bdh['status'])

        # setting speeds to 75%
        isp = bd['ideal_sector_speed'] // 100
        for week in range(2):
            for cs in range(1, CHARGE_STEPS - 1, 2 * (CHARGE_STEPS - 2) // 10):  # fill at least 10 slots
                kb._pdata['weekly']['discharge_speed_avg'][week][cs] = isp * 75

        bdh = kb.get_battery_health('')
        self.assertIn('Aged', bdh['status'])

        # setting speeds to 38%
        for week in range(2):
            for cs in range(1, CHARGE_STEPS - 1, 2 * (CHARGE_STEPS - 2) // 10):  # fill at least 10 slots
                kb._pdata['weekly']['discharge_speed_avg'][week][cs] = isp * 38

        bdh = kb.get_battery_health('')
        self.assertIn('Fail', bdh['status'])


if __name__ == '_main_':
    unittest.main()
