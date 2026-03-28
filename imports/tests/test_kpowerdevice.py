#!/usr/bin/env python
"""Unit tests for kpowerdevice.py"""
import copy
import json
import os
import shutil
import tempfile
import time
import unittest
from configparser import ConfigParser
import imports.kpowerutils as kpu
from imports.kpowerdevice import KPowerDevice

class TestKPowerDevice(unittest.TestCase):
    """Test the KPowerDevice class."""

    def setUp(self):
        # Create a temporary directory to act as the save path
        self.tmpdir = tempfile.mkdtemp()
        # Config (.ini) template
        self.tpl_dev_id = 'lead'
        self.tpl_batt_id = 'bat1'

        self.tpl_config = {  # NOTE! KEEP CONSISTENT WITH self_tpl_dev_data
            'DEFAULT': {
                'one_to_one': 'attr1:topic1 attr2:topic2 attr3:topic3',
                'bulk_report': 'bulk_report1 bulk_report2 bulk_report3',
                'standard_v': '230,10',
                'sample_interval': '30',
                'perma_storage': self.tmpdir,
            },
            'power.' + self.tpl_dev_id: {
                '.mfr': 'Brutha and Co.',
                '.model': 'Om TTM001',
                'batteries': self.tpl_batt_id,
                'one_to_one': 'a1:t1 a2:t2 a3:t3 a4:t4',
                'bulk_report': 'br1 br2',
                'calc_charge_data': 'yes',
                'charging_current': '20',
                'load_reported_as': 'p',
                'load_zero': '50w',
                'power_rating': '2000,va',
                'power_factor': '0.85',
            },
            'battery.' + self.tpl_batt_id: {
                'type': 'pb',
                'vnom': '48',
                'capacity_ah': '100',
            }
        }
        self.file_name = os.path.join(self.tmpdir, 'mqtt-power.' + self.tpl_dev_id + '.json')


    ################################################
    def tearDown(self):
        # Remove the temporary directory
        shutil.rmtree(self.tmpdir)

    ################################################
    def test_minimal(self):
        """All settings with defaults should be filled in."""
        conf = ConfigParser()
        conf.read_dict({
            'DEFAULT': {},
            'power.blackbox': {
                'one_to_one': 'attr1:topic1 attr2:topic2 attr3:topic3',
                'bulk_report': 'bulk_report1 bulk_report2 bulk_report3',
                'perma_storage': self.tmpdir,
            }})
        kpd = KPowerDevice('blackbox', conf)
        self.assertEqual(3, len(kpd.bulk_report))
        self.assertEqual(0, len(kpd.log_items))
        # kpd._messages
        self.assertEqual(3, len(kpd.one_to_one))

        self.assertEqual(10, kpd.commons.charging_current)

        self.assertEqual(-1.0, kpd._load_to_w)
        self.assertEqual(0.0, kpd._load_zero)

        self.assertEqual(-1, kpd.power_rating)
        self.assertEqual(kpu.KPowerUnits.INVALID.value, kpd.power_rating_unit.value)
        self.assertEqual(0.8, kpd.commons.power_factor)

        self.assertEqual(60, kpd.commons.sample_interval)
        self.assertEqual(230, kpd.standard_v)
        self.assertFalse(kpd.commons.calc_charge_data)


    ################################################
    def test_no_defaults(self):
        """All setting are present and correct."""
        conf = ConfigParser()
        conf.read_dict( self.tpl_config )
        kpd = KPowerDevice('lead', conf)

        self.assertEqual(2, len(kpd.bulk_report))  # override
        self.assertEqual(0, len(kpd.log_items))
        # kpd._messages
        self.assertEqual(4, len(kpd.one_to_one))  # override

        self.assertEqual(20, kpd.commons.charging_current)

        self.assertEqual(16, kpd._load_to_w)  # 2000*0.8/100
        self.assertEqual(50.0, kpd._load_zero)

        self.assertEqual(1600, kpd.power_rating)
        self.assertEqual(kpu.KPowerUnits.W.value, kpd.power_rating_unit.value)
        self.assertEqual(0.85, kpd.commons.power_factor)

        self.assertEqual(30, kpd.commons.sample_interval)
        self.assertEqual(230, kpd.standard_v)
        self.assertTrue(kpd.commons.calc_charge_data)


    ################################################
    def test_bad_data(self):
        """Trying all kinds of bad data to produce messages."""
        conf_dict_def = { 'DEFAULT': {},  # settings here should be consistent, so later we may break some
            'power': {
                'standard_v': '183,7',
                'sample_interval': '37',
                'perma_storage': self.tmpdir,
            },
            'power.bad': {
                'battery': 'pb,48,100',
                'calc_charge_data': 'yes',
                'charging_current': '20',
                'load_reported_as': 'p',
                'load_zero': '50w',
                'power_rating': '2000,w',
                'power_factor': '0.85',
            }}

        def prep(item: str, val: str) -> KPowerDevice:
            """Preps new sub-test data. item:val is the broken data element"""
            conf = ConfigParser()
            conf_dict = copy.deepcopy(conf_dict_def)
            conf_dict['power.bad'][item] = val
            conf.read_dict(conf_dict)
            return KPowerDevice('bad', conf )

        # -------------------
        kpd = prep('load_reported_as', 'elephants')  # bad type
        self.assertEqual( -1, kpd._load_to_w )
        self.assertEqual( 1, len(kpd._messages) )

        # -------------------
        kpd = prep('load_zero', '42m')  # bad type
        self.assertEqual(0.0, kpd._load_zero )
        self.assertEqual( 1, len(kpd._messages) )

        # -------------------
        kpd = prep('power_rating', '2000,p' )  # percent is valid overall, but not here
        self.assertEqual( -1, kpd.power_rating )
        self.assertEqual( 1, len(kpd._messages) )

        # -------------------
        kpd = prep('power_rating', '200a' )  # bad type
        self.assertEqual( -1, kpd.power_rating )
        self.assertEqual( kpu.KPowerUnits.INVALID.value, kpd.power_rating_unit.value )
        self.assertEqual( 1, len(kpd._messages) )

        # -------------------
        kpd = prep('power_factor', '1.1' )
        self.assertEqual( -1.0, kpd.commons.power_factor )
        self.assertEqual( 1, len(kpd._messages) )


    ########################################
    def test_update_hourly_load(self):
        """Test of _update_hourly_load(), placing load averages in correct slots"""
        conf = ConfigParser()
        conf_dict = copy.deepcopy(self.tpl_config)
        conf.read_dict(conf_dict)

        dev = KPowerDevice('lead', conf )
        pd = dev._pdata
        t = time.localtime()
        if t.tm_min == 59 and t.tm_sec == 59:  # wait a bit so we won't get cpu hogged and miss the right number
            time.sleep(2)

        hour = time.localtime().tm_hour
        load = 123
        dev._update_hourly_load( load )
        self.assertEqual( 123, pd['hourly_load_avg'][hour] )  # initials are zero
        self.assertEqual( 1, pd['hourly_load_samples'][hour] )

        load = 64
        dev._update_hourly_load(load)
        self.assertEqual( 93, pd['hourly_load_avg'][hour] )  # 123 + 64 / 2
        self.assertEqual( 2, pd['hourly_load_samples'][hour] )


    ################################################
    # def test_file_save_and_load_back(self):
    #     """file_save should persist data and we can reload it."""
    #     todo: protocol check - match keys from load (is _validate_structure???)
    #     kb = KBattStats(self.tmpdir, self.tpl_dev_data)
    #     # Modify some data
    #     kb._pdata['weekly']['blackouts_count'][0] = 42
    #
    #     # Save
    #     self.assertTrue(kb.file_save())
    #
    #     # The file should exist
    #     file_name = os.path.join(self.tmpdir, 'mqtt-power.' + self.tpl_dev_id + '.json')
    #     self.assertTrue(os.path.exists(file_name))
    #
    #     # Load a brand-new instance from the file
    #     kb2 = KBattStats(self.tmpdir, self.tpl_dev_data)
    #     self._validate_structure(kb2, 1)
    #     self.assertEqual(kb2._pdata['weekly']['blackouts_count'][0], 42)


    ################################################
    def _validate_pdata_structure( self, pd: dict, weeks_count: int ):
        # protocol checks: Top-level and the presence of keys that mostly related to this class
        expect_keys = list(pd.keys())  # check if format hasn't changed
        if 'batteries' in expect_keys:
            expect_keys.remove('batteries')

        for key in ['dev_id', 'hourly_load_avg', 'hourly_load_samples',
                    'messages', 'started', 'ts', 'weekly', 'ups']:
            self.assertIn( key, pd )
            expect_keys.remove( key )

        self.assertEqual( 0, len(expect_keys), 'Extra pdata keys: ' + ', '.join(expect_keys) )

        for key in ['hourly_load_avg', 'hourly_load_samples']:
            self.assertIsInstance( pd[key], list )
            self.assertEqual( 24, len(pd[key]) )
            self.assertIsInstance( pd[key][0], int )
            self.assertEqual( 0, pd[key][0] )

        # The weekly structure must contain all keys
        wdict = pd['weekly']
        expect_keys = list(wdict.keys())  # check if format hasn't changed
        for key in ['start_ts', 'blackouts_count', 'blackouts_time']:
            self.assertIn( key, wdict )
            self.assertEqual( weeks_count, len(wdict[key]) )
            expect_keys.remove( key )

        self.assertEqual( 0, len(expect_keys), 'Extra week keys: ' + ', '.join(expect_keys) )

        self.assertIsInstance( wdict['blackouts_count'][0], int )
        self.assertIsInstance( wdict['blackouts_time'][0], float )


    ################################################
    def test_weekly_shift_init(self):
        """_weekly_shift try to insert a new week while still in same time range."""
        conf = ConfigParser()
        conf.read_dict(self.tpl_config)
        kpd = KPowerDevice(self.tpl_dev_id, conf)

        t = int(time.time())
        # try to insert two additional weeks - should still be one
        kpd._weekly_shift()
        kpd._weekly_shift()

        self.assertEqual(1, len(kpd._pdata['weekly']['start_ts']))
        self.assertGreaterEqual(1, kpd._pdata['weekly']['start_ts'][0] - t)

        # All other lists must also have the same length of 3 weeks
        for key, lst in kpd._pdata['weekly'].items():
            self.assertEqual(1, len(lst))


    ################################################
    def test_weekly_shift_new(self):
        """_weekly_shift inserts 2 new weeks and keeps the list at max length."""
        conf = ConfigParser()
        conf.read_dict(self.tpl_config)
        kpd = KPowerDevice(self.tpl_dev_id, conf)

        t = int(time.time())

        # artificially shift week start
        kpd._pdata['weekly']['start_ts'][0] -= 2 * (kpu.SECONDS_IN_A_WEEK + 1)
        # try to insert two additional weeks
        kpd._weekly_shift()
        kpd._pdata['weekly']['start_ts'][0] -= kpu.SECONDS_IN_A_WEEK + 1
        kpd._weekly_shift()

        self.assertEqual(3, len(kpd._pdata['weekly']['start_ts']))
        self.assertGreaterEqual(1, kpd._pdata['weekly']['start_ts'][0] - t)

        # All other lists must also have the same length of 3 weeks
        for key, lst in kpd._pdata['weekly'].items():
            self.assertEqual(3, len(lst))

        # Verify that the weekly lists are truncated at WEEKS_IN_A_YEAR
        # We simulate many shifts to exceed that limit
        for _ in range(kpu.WEEKS_IN_A_YEAR + 5):
            kpd._weekly_shift()
            kpd._pdata['weekly']['start_ts'][0] -= 2 * kpu.SECONDS_IN_A_WEEK  # for it looks like old

        for key, lst in kpd._pdata['weekly'].items():
            self.assertLessEqual(kpu.WEEKS_IN_A_YEAR, len(lst))


    ################################################
    def test_init_with_matching_file_loads(self):
        """If a matching file exists it is loaded correctly."""
        # Create a matching file. Here we prepare what it should be like previously saved data
        saved = {
            'dev_id': self.tpl_dev_id,
            'ts': 1_000_000,
            'started': 1_000_000,
            'messages': [],
            'ups': {},
            'batteries': {
                self.tpl_batt_id: {
                    'registered': [1, 'Somewhere in time'],
                    'type': 'bt_lead',
                    'vnom': 48,
                    'capacity_ah': 100,
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
                }
            },
            'hourly_load_avg': [0] * 24,
            'hourly_load_samples': [0] * 24,
            'weekly': {
                'start_ts': [123],
                'blackouts_count': [5],
                'blackouts_time': [2.5],
            },
        }

        t = int(time.time())
        #  check if we follow the same protocol everywhere
        self._validate_pdata_structure( saved, 1 )

        with open(self.file_name, 'w', encoding='utf-8') as fh:
            json.dump(saved, fh)

        conf = ConfigParser()
        conf.read_dict( self.tpl_config )

        kpd = KPowerDevice( self.tpl_dev_id, conf )

        self.assertEqual( 0, kpd.init_errors, kpd.collect_messages() )
        self.assertEqual( 0, kpd.init_warnings, kpd._messages )
        self.assertGreaterEqual( t, kpd._pdata['weekly']['start_ts'][0])
        self.assertEqual( 123, kpd._pdata['weekly']['start_ts'][1])
        self._validate_pdata_structure( kpd._pdata, 2 )


    ################################################
    def test_init_with_invalid_file_sets_stub(self):
        """If the file has a different dev_id or battery definition, it is discarded."""
        # File with mismatched dev_id
        mismatched = {
            'dev_id': 'other_device',
            'ts': 1_000_000,
            'started': 1_000_000,
            'messages': [],
            'ups': {},
            'batteries': {
                self.tpl_batt_id: {
                    'type': 'bt_lead',
                    'vnom': '48',
                    'capacity_ah': '100',
                }
            },
            'weekly': {},
            'hourly_load_avg': [],
            'hourly_load_samples': [],
        }

        with open(self.file_name, 'w', encoding='utf-8') as fh:
            json.dump(mismatched, fh)

        conf = ConfigParser()
        conf.read_dict(self.tpl_config)
        kpd = KPowerDevice( self.tpl_dev_id, conf )

        self.assertEqual( 1, kpd.init_warnings, kpd._messages )
        self.assertEqual("different device" in kpd._messages[0], True)


    ################################################
    def test_file_save_and_load_back(self):
        """file_save should persist data and we can reload it."""
        conf = ConfigParser()
        conf.read_dict(self.tpl_config)
        kpd1 = KPowerDevice( self.tpl_dev_id, conf )

        # Modify some data
        kpd1._pdata['weekly']['blackouts_count'][0] = 42

        # Save
        self.assertTrue( kpd1.stats_file_save(), kpd1._messages )

        # The file should exist
        self.assertTrue( os.path.exists(self.file_name) )
        try:
            with open(self.file_name, 'r', encoding='utf-8') as fh:
                jcont = fh.read()
                fdata = json.loads(jcont)
        except Exception as e:
            self.fail("JSON problem: {}\nContent: {}".format(e, jcont))

        self._validate_pdata_structure( fdata, 1 )
        self.assertEqual( 42, fdata['weekly']['blackouts_count'][0] )

        # Load a brand-new instance from the file
        conf = ConfigParser()
        conf.read_dict(self.tpl_config)
        kpd2 = KPowerDevice( self.tpl_dev_id, conf )
        self.assertEqual( 0, kpd2.init_errors, kpd2.collect_messages() )
        self.assertEqual( 0, kpd2.init_warnings, kpd2.collect_messages() )
        self._validate_pdata_structure( kpd2._pdata, 1 )
        self.assertEqual( 42, kpd2._pdata['weekly']['blackouts_count'][0] )


########################################
if __name__ == '__main__':
    unittest.main()
