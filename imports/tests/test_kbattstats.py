#!/usr/bin/env python
"""Unit tests for kbattstats.py"""
import copy
from configparser import ConfigParser
from imports.kbattstats import KBattStats
import imports.kpowerutils as kpu
from imports.kpowerutils import KPowerDeviceCommons
import time
from typing import Any
import unittest
from unittest import mock


################################################
# mock for test of file save/load
class MockFile:
    def __init__(self, content: str = ''):
        self.content: str = content

    def read(self):
        return self.content

    def write(self, content: str):
        self.content += content


################################################
def make_commons(dev_id: str) -> KPowerDeviceCommons:
    comm = KPowerDeviceCommons(dev_id)
    comm.charging_current = 12
    comm.last_load = 1
    comm.on_battery = False
    comm.power_factor = 0.82
    comm.sample_interval = 37
    return comm


################################################
class TestKBattStats(unittest.TestCase):
    """Test the KBattStats class."""

    def setUp(self):
        # Create a temporary directory to act as the save path
        # self.tmpdir = tempfile.mkdtemp()
        # Common device data
        self.tpl_dev_id: str = 'lead'
        self.tpl_dev_section: str = 'power.' + self.tpl_dev_id
        self.tpl_config: dict[str, Any] = {
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

        self.tpl_batt_id = 'bat1'
        self.tpl_config_battery: dict[str, str] = {
            'type': 'pb', 'vnom': '48', 'capacity_ah': '100',
        }

        # TEMPLATE: upsc data
        self.tpl_upsc_data = {
            'battery_charge': '-1',
            'battery_voltage': '-1.0',
            'ups_load': '-1',
        }


    ################################################
    def tearDown(self):
        # Remove the temporary directory
        # shutil.rmtree(self.tmpdir)
        pass


    ################################################
    def _validate_pdata_structure(self, kb: KBattStats, weeks_count: int):
        # Protocol sanity checks: tops
        struct_tpl = {
            'registered': [],
            'type': '',
            'vnom': 0,
            'capacity_ah': 0,
            'health': {
                'cycles': [0, 0, 0],
                'status': "OK",
                'tbf': -1,
                'wellness': 100,
            },
            'weekly': {
                'charge_speed_avg': [],
                'charge_speed_samples': [],
                'discharge_speed_avg': [],
                'discharge_speed_samples': [],
                'start_ts': [],
            }
        }

        # checking for the whole structure keys and types match
        mlist = kpu.validate_structure( struct_tpl, kb._pdata, '' )
        self.assertEqual(0, len(mlist), mlist )

        self.assertEqual( 2, len(kb._pdata['registered']) )
        self.assertIsInstance(kb._pdata['registered'][0], int )  # timestamp
        self.assertIsInstance(kb._pdata['registered'][1], str )  # string repr

        # The weekly structure sanity
        w = kb._pdata['weekly']
        for key in struct_tpl['weekly'].keys():
            self.assertEqual( len(w[key]), weeks_count )

        for name in ['discharge_speed', 'charge_speed']:
            key = name + '_avg'
            self.assertIsInstance( w[key][0], list )
            self.assertEqual( kpu.CHARGE_STEPS, len(w[key][0]) )
            self.assertIsInstance( w[key][0][0], float )  # weekly->key->week->sector
            key = name + '_samples'
            self.assertIsInstance( w[key][0], list )
            self.assertEqual( kpu.CHARGE_STEPS, len(w[key][0]) )
            self.assertIsInstance( w[key][0][0], int )

        # Check the timestamp that was inserted
        self.assertIsInstance( w['start_ts'][0], int )


    ################################################
    def test_init_without_old_stats(self):
        """No file exists - constructor should create default data."""
        t = int(time.time())
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.' + self.tpl_batt_id] = copy.deepcopy( self.tpl_config_battery )

        conf = ConfigParser()
        conf.read_dict(conf_init)
        comm = make_commons(self.tpl_dev_id)
        kb = KBattStats(self.tpl_batt_id, comm, conf, None)

        self.assertFalse(kb.invalid)

        # We need to make sure that initialization protocol hasn't changed
        self.assertEqual( int(100 * 48 * 0.82), kb.capacity_wh )
        self.assertEqual( 100, kb.capacity_ah )
        self.assertEqual( 100.0, kb.charge )
        self.assertEqual( 0, len(kb.messages), kb.messages )
        self.assertEqual( kpu.KBatteryTypes.BT_LEAD.value, kb.type.value)
        self.assertEqual( 48, kb.v_nom )

        # private:
        self.assertEqual( int(3600 * kb.capacity_wh // (kpu.CHARGE_STEPS - 1)), kb._ideal_sector_speed )
        self.assertEqual( -1, kb._charge_sector )
        self.assertEqual( 0, kb._time_in_charge_sector )
        self.assertEqual( -1.0, kb._charge_sector_start )
        self.assertEqual( 0.0, kb._load_avg )
        self.assertEqual( 0, kb._state_samples )
        self.assertFalse( kb._was_discharging )

        # weekly data should be initialized
        self.assertGreaterEqual( 10, kb._pdata['weekly']['start_ts'][0] - t )

        self._validate_pdata_structure(kb, 1)


    ################################################
    def test_init_with_matching_json(self):
        """If a matching JSON provided it is loaded correctly.
        Thorough validation is always performed by the descendant classes"""
        t = int(time.time())
        # Create a matching JSON item
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

        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.' + self.tpl_batt_id] = copy.deepcopy( self.tpl_config_battery )

        conf = ConfigParser()
        conf.read_dict( conf_init )
        comm = make_commons( self.tpl_dev_id )
        kb = KBattStats( self.tpl_batt_id, comm, conf, saved )

        self.assertFalse( kb.invalid )
        self.assertEqual( 0, len(kb._pdata['messages']) )
        self.assertEqual( 0, len(kb.messages), kb.messages )

        # undefined state is unchanged
        self.assertEqual( 100, kb.capacity_ah )
        self.assertEqual( kpu.KBatteryTypes.BT_LEAD.value, kb.type.value )
        self.assertEqual( 48, kb.v_nom )

        # Though JSON is imported
        self.assertGreaterEqual( t, kb._pdata['weekly']['start_ts'][0] )
        self.assertEqual( 123, kb._pdata['weekly']['start_ts'][1] )


    ################################################
    def test_init_with_invalid_json(self):
        """If the file has general structure problems, it is discarded."""
        t = int(time.time())
        saved_tpl = {  # KBatteries slip only the 'batteries' dict down to each KBatt* object
            self.tpl_batt_id: {
                'type': str(kpu.bt_from_str( self.tpl_config_battery['type'] )),  # check convs also
                'vnom': int(self.tpl_config_battery['vnom']),
                'capacity_ah': int(self.tpl_config_battery['capacity_ah']),
                'messages': [],
                'registered': [t - kpu.SECONDS_IN_A_WEEK, 'A week ago'],
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

        # 1.1 presence of messages: mild
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.' + self.tpl_batt_id] = copy.deepcopy( self.tpl_config_battery )

        conf = ConfigParser()
        conf.read_dict( conf_init )
        comm = make_commons( self.tpl_dev_id )

        saved = copy.deepcopy(saved_tpl)
        saved[self.tpl_batt_id]['messages'].append('not an error')
        kb = KBattStats( self.tpl_batt_id, comm, conf, saved )

        self.assertFalse( kb.invalid, kb.messages )

        # 1.2 presence of messages: error
        saved = copy.deepcopy(saved_tpl)
        saved[self.tpl_batt_id]['messages'].append('ERROR: oopsy!')
        kb = KBattStats( self.tpl_batt_id, comm, conf, saved )

        self.assertTrue( kb.invalid )
        self.assertEqual( 1, len(kb.messages), kb.messages )

        # 2.1 registered time: in future
        saved = copy.deepcopy(saved_tpl)
        saved[self.tpl_batt_id]['registered'][0] = t + 999999
        kb = KBattStats( self.tpl_batt_id, comm, conf, saved )

        self.assertFalse( kb.invalid )
        self.assertEqual( 1, len(kb.messages), kb.messages )
        self.assertGreaterEqual( 10, kb._pdata['registered'][0] - t )  # let's say this is now +- 10sec

        # 2.2 registered time: too old
        saved = copy.deepcopy(saved_tpl)
        saved[self.tpl_batt_id]['registered'][0] = -123
        kb = KBattStats( self.tpl_batt_id, comm, conf, saved )

        self.assertFalse( kb.invalid )
        self.assertEqual( 1, len(kb.messages), kb.messages )
        self.assertGreaterEqual(10, kb._pdata['registered'][0] - t)

        # 3.1 weekly series length - extra element
        saved = copy.deepcopy(saved_tpl)
        saved[self.tpl_batt_id]['weekly']['discharge_speed_avg'].append(123)
        kb = KBattStats( self.tpl_batt_id, comm, conf, saved )

        self.assertFalse( kb.invalid )
        self.assertEqual( 1, len(kb.messages), kb.messages )
        self.assertGreaterEqual( 10, kb._pdata['registered'][0] - t )


    ################################################
    def test_weekly_shift_init(self):
        """_weekly_shift try to insert a new week while still in same time range."""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.' + self.tpl_batt_id] = copy.deepcopy( self.tpl_config_battery )

        conf = ConfigParser()
        conf.read_dict( conf_init )
        comm = make_commons( self.tpl_dev_id )

        kb = KBattStats( self.tpl_batt_id, comm, conf, None )

        t = int(time.time())
        # try to insert two additional weeks - should still be one
        kb._weekly_shift()
        kb._weekly_shift()

        self.assertEqual(1, len(kb._pdata['weekly']['start_ts']))
        self.assertGreaterEqual(1, kb._pdata['weekly']['start_ts'][0] - t)

        # All other lists must also have the same length of 3 weeks
        for key, lst in kb._pdata['weekly'].items():
            self.assertEqual(1, len(lst))


    ################################################
    def test_weekly_shift_new(self):
        """_weekly_shift inserts a new week and keeps the list at max length."""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.' + self.tpl_batt_id] = copy.deepcopy( self.tpl_config_battery )

        conf = ConfigParser()
        conf.read_dict( conf_init )
        comm = make_commons( self.tpl_dev_id )

        kb = KBattStats( self.tpl_batt_id, comm, conf, None )

        t = int(time.time())

        # artificially shift week start
        kb._pdata['weekly']['start_ts'][0] -= 2 * (kpu.SECONDS_IN_A_WEEK + 1)
        # try to insert two additional weeks
        kb._weekly_shift()
        kb._pdata['weekly']['start_ts'][0] -= kpu.SECONDS_IN_A_WEEK + 1
        kb._weekly_shift()

        self.assertEqual(3, len(kb._pdata['weekly']['start_ts']))
        self.assertGreaterEqual(1, kb._pdata['weekly']['start_ts'][0] - t)

        # All other lists must also have the same length of 3 weeks
        for key, lst in kb._pdata['weekly'].items():
            self.assertEqual( 3, len(lst))

        # Verify that the weekly lists are truncated at WEEKS_IN_A_YEAR
        # We simulate many shifts to exceed that limit
        for _ in range(kpu.WEEKS_IN_A_YEAR + 5):
            kb._pdata['weekly']['start_ts'][0] -= 2 * kpu.SECONDS_IN_A_WEEK  # for it looks like old
            kb._weekly_shift()

        for key, lst in kb._pdata['weekly'].items():
            self.assertLessEqual( kpu.WEEKS_IN_A_YEAR, len(lst) )


    ################################################
    def test_weekly_avg_add(self):
        """Test that the average calculation updates correctly."""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.' + self.tpl_batt_id] = copy.deepcopy( self.tpl_config_battery )

        conf = ConfigParser()
        conf.read_dict( conf_init )
        comm = make_commons( self.tpl_dev_id )

        kb = KBattStats( self.tpl_batt_id, comm, conf, None )

        # Initialize a sector
        sector = 5
        # Start with known average and samples
        w = kb._pdata['weekly']
        w['discharge_speed_avg'][0][sector] = 0.0
        w['discharge_speed_samples'][0][sector] = 0

        # Add a single value
        kb._weekly_avg_add('discharge_speed', 10.0, sector)
        self.assertEqual(w['discharge_speed_samples'][0][sector], 1)
        self.assertAlmostEqual(w['discharge_speed_avg'][0][sector], 10.0)

        # Add a second value
        kb._weekly_avg_add('discharge_speed', 20.0, sector)
        self.assertEqual(w['discharge_speed_samples'][0][sector], 2)
        # Average should now be 15.0
        self.assertAlmostEqual(w['discharge_speed_avg'][0][sector], 15.0)


if __name__ == '__main__':
    unittest.main()
