#!/usr/bin/env python
"""
Unit tests for kbattstats.py
"""
import os
import json
import shutil
import tempfile
import time
import unittest
from unittest import mock

import kadpy.kbattstats as kbattstats
from kadpy.kbattstats import KBattStats, CHARGE_STEPS, WEEKS_IN_A_YEAR

class TestKBattStats(unittest.TestCase):
    """Test the KBattStats class."""

    def setUp(self):
        # Create a temporary directory to act as the save path
        self.tmpdir = tempfile.mkdtemp()
        # Common device data
        self.dev_data = {
            'dev_id': 'test123',
            'batt_type': 0,
            'batt_vnom': 12,
            'batt_cap': 2000,
        }

    def tearDown(self):
        # Remove the temporary directory
        shutil.rmtree(self.tmpdir)


    ################################################
    def _validate_structure(self, kb: KBattStats, weeks_count: int):
        # Basic sanity checks
        for key in ['batt_type', 'batt_vnom', 'batt_cap', 'ts', 'started', 'messages',
                    'weekly', 'hourly_load_avg', 'hourly_load_samples']:
            self.assertIn(key, kb._pdata)

        for key in ['hourly_load_avg', 'hourly_load_samples']:
            self.assertIsInstance(kb._pdata[key], list)
            self.assertEqual(len(kb._pdata[key]), 24)
            self.assertIsInstance(kb._pdata[key][0], int)
            self.assertEqual(kb._pdata[key][0], 0)

        # The weekly structure must contain all keys
        w = kb._pdata['weekly']
        for key in ['start_ts', 'discharge_speed_avg', 'discharge_speed_samples',
            'charge_speed_avg', 'charge_speed_samples', 'blackouts_count', 'blackouts_time' ]:
            self.assertIn(key, w)
            self.assertEqual(len(w[key]), weeks_count)

        for name in ['discharge_speed', 'charge_speed']:
            key = name + '_avg'
            self.assertIsInstance(w[key][0], list)
            self.assertEqual(len(w[key][0]), CHARGE_STEPS)
            self.assertIsInstance(w[key][0][0], float)  # weekly->key->week->sector
            key = name + '_samples'
            self.assertIsInstance(w[key][0], list)
            self.assertEqual(len(w[key][0]), CHARGE_STEPS)
            self.assertIsInstance(w[key][0][0], int)

        self.assertIsInstance(w['blackouts_count'][0], int)
        self.assertIsInstance(w['blackouts_time'][0], float)

        # Check the timestamp that was inserted
        self.assertIsInstance(w['start_ts'][0], int)


    ################################################
    @mock.patch('time.time', return_value=1_000_000)
    def test_init_without_file_creates_default(self, mock_time):
        """No file exists - constructor should create default data."""
        kb = KBattStats(self.tmpdir, self.dev_data)
        self.assertFalse(kb.invalid)
        self.assertEqual(kb.dev_id, self.dev_data['dev_id'])
        self.assertEqual(kb._pdata['weekly']['start_ts'][0], 1_000_000)

        self._validate_structure(kb, 1)


    ################################################
    @mock.patch('time.time', return_value=1_000_000)
    def test_init_with_matching_file_loads(self, mock_time):
        """If a matching file exists it is loaded correctly."""
        # Create a matching file
        saved = {
            'dev_id': self.dev_data['dev_id'],
            'batt_type': self.dev_data['batt_type'],
            'batt_vnom': self.dev_data['batt_vnom'],
            'batt_cap': self.dev_data['batt_cap'],
            'ts': 1_000_000,
            'started': 1_000_000,
            'messages': [],
            'weekly': {
                'start_ts': [123],
                'discharge_speed_avg': [[0.5] * CHARGE_STEPS],
                'discharge_speed_samples': [[1] * CHARGE_STEPS],
                'charge_speed_avg': [[1.0] * CHARGE_STEPS],
                'charge_speed_samples': [[1] * CHARGE_STEPS],
                'blackouts_count': [5],
                'blackouts_time': [2.5],
            },
            'hourly_load_avg': [[0] * 24],
            'hourly_load_samples': [[0] * 24],
        }
        file_name = os.path.join(self.tmpdir, 'mqtt-power.' + self.dev_data['dev_id'] + '.json')
        with open(file_name, 'w', encoding='utf-8') as fh:
            json.dump(saved, fh)

        kb = KBattStats(self.tmpdir, self.dev_data)

        self.assertFalse(kb.invalid)
        self.assertEqual(len(kb._pdata['messages']), 0)
        self.assertEqual(kb._pdata['weekly']['start_ts'][0], 123)


    ################################################
    @mock.patch('time.time', return_value=1_000_000)
    def test_init_with_invalid_file_sets_stub(self, mock_time):
        """If the file has a different dev_id or battery definition, it is discarded."""
        # File with mismatched dev_id
        mismatched = {
            'dev_id': 'other_device',
            'batt_type': self.dev_data['batt_type'],
            'batt_vnom': self.dev_data['batt_vnom'],
            'batt_cap': self.dev_data['batt_cap'],
            'ts': 1_000_000,
            'started': 1_000_000,
            'messages': [],
            'weekly': {},
            'hourly_load_avg': [],
            'hourly_load_samples': [],
        }
        file_name = os.path.join(self.tmpdir, 'mqtt-power.' + self.dev_data['dev_id'] + '.json')
        with open(file_name, 'w', encoding='utf-8') as fh:
            json.dump(mismatched, fh)

        kb = KBattStats(self.tmpdir, self.dev_data)

        self.assertTrue(kb.invalid)
        # The _pdata should be the init_data stub
        self.assertEqual(kb._pdata['dev_id'], self.dev_data['dev_id'])
        self.assertEqual(len(kb._pdata['messages']), 1)
        self.assertEqual("different device" in kb.messages()[0], True)


    ################################################
    def test_weekly_shift(self):
        """_weekly_shift inserts a new week and keeps the list at max length."""
        kb = KBattStats(self.tmpdir, self.dev_data)

        t = int(time.time())
        # Insert two additional weeks (we have one already)
        kb._weekly_shift()  # 1st shift
        kb._weekly_shift()  # 2nd shift

        # The start_ts list should have two entries in front
        self.assertLessEqual(kb._pdata['weekly']['start_ts'][0] - t, 1)
        self.assertLessEqual(kb._pdata['weekly']['start_ts'][1] - t, 1)

        # All other lists must also have the same length of 3 weeks
        for key, lst in kb._pdata['weekly'].items():
            self.assertEqual(len(lst), 3)

        # Verify that the weekly lists are truncated at WEEKS_IN_A_YEAR
        # We simulate many shifts to exceed that limit
        for _ in range(WEEKS_IN_A_YEAR + 5):
            kb._weekly_shift()
        for key, lst in kb._pdata['weekly'].items():
            self.assertLessEqual(len(lst), WEEKS_IN_A_YEAR)


    ################################################
    def test_weekly_avg_add(self):
        """Test that the average calculation updates correctly."""
        kb = KBattStats(self.tmpdir, self.dev_data)

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


    ################################################
    def test_file_save_and_load_back(self):
        """file_save should persist data and we can reload it."""
        kb = KBattStats(self.tmpdir, self.dev_data)
        # Modify some data
        kb._pdata['weekly']['blackouts_count'][0] = 42

        # Save
        self.assertTrue(kb.file_save())

        # The file should exist
        file_name = os.path.join(self.tmpdir, 'mqtt-power.' + self.dev_data['dev_id'] + '.json')
        self.assertTrue(os.path.exists(file_name))

        # Load a brand-new instance from the file
        kb2 = KBattStats(self.tmpdir, self.dev_data)
        self._validate_structure(kb2, 1)
        self.assertEqual(kb2._pdata['weekly']['blackouts_count'][0], 42)


    ################################################
    def test_update_avg_int(self):
        """update_avg_int should perform integer average rounding down."""
        avg, samples = kbattstats.update_avg_int(5, 2, 3)  # avg=5, new val=2, samples=3 -> (5*3+2)//4 = 17//4 = 4
        self.assertEqual(avg, 4)
        self.assertEqual(samples, 4)


    ################################################
    def test_update_avg_float(self):
        """update_avg_float should perform float average."""
        avg, samples = kbattstats.update_avg_float(5.0, 2.0, 3)  # (5*3+2)/4 = 17/4 = 4.25
        self.assertAlmostEqual(avg, 4.25, places=2)
        self.assertEqual(samples, 4)


if __name__ == '__main__':
    unittest.main()
