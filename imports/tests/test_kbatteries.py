#!/usr/bin/env python
"""Unit tests for kpowerdevice.py"""
import copy
import unittest
from configparser import ConfigParser
from typing import Any
from imports.kbatteries import KBatteries
import imports.kpowerutils as kpu
from imports.kpowerutils import KPowerDeviceCommons


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
class TestKBatteries(unittest.TestCase):
    """Test the KBatteries class."""

    def setUp(self):
        # Config (.ini) template
        self.tpl_dev_id: str = 'lead'
        self.tpl_dev_section: str = 'power.' + self.tpl_dev_id
        self.tpl_config: dict[str, Any] = {
            'DEFAULT': {
                'standard_v': '230,10',
                'sample_interval': '37',
            },
            '' + self.tpl_dev_section: {
                '.mfr': 'Brutha and Co.',
                '.model': 'Om TTM001',
                'calc_charge_data': 'yes',
                'charging_current': '12',
                'load_reported_as': 'p',
                'load_zero': '120w',
                'power_rating': '2000,va',
                'power_factor': '0.82',
            }
        }


    ################################################
    def tearDown(self):
        # Remove the temporary directory
        # shutil.rmtree(self.tmpdir)
        pass


    ################################################
    def _perform_bad_battery_defs_checks(self, conf_init: dict):
        conf = ConfigParser()
        conf.read_dict(conf_init)
        comm = make_commons(self.tpl_dev_id)

        kb = KBatteries(comm, conf, None)
        self.assertEqual(1, len(kb.messages), kb.messages)
        self.assertEqual(0, len(kb._batteries))
        self.assertEqual(0, len(kb._ids))

        # test if methods are still working
        kb.process_upsc_data({})  # no return. shouldn't raise exceptions
        self.assertEqual(0, len(kb.get_list()))  # no ids
        self.assertEqual((0, 0.0, 0, -1), kb.get_remaining_power())


    ################################################
    def test_missing_battery_section(self):
        """Device has no battery section matching the list"""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init[self.tpl_dev_section]['batteries'] = 'missme'

        self._perform_bad_battery_defs_checks(conf_init)


    ################################################
    def test_bad_def_in_separate_section(self):
        """Device have invalid battery definition in its own section."""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init[self.tpl_dev_section]['batteries'] = 'badbat'
        conf_init['battery.badbat'] = { 'type': 'mess' }

        self._perform_bad_battery_defs_checks(conf_init)


    ################################################
    def _perform_good_battery_defs_checks(self, conf_init: dict, bnum: int):
        conf = ConfigParser()
        conf.read_dict(conf_init)
        comm = make_commons(self.tpl_dev_id)

        kb = KBatteries(comm, conf, None)
        self.assertEqual(0, len(kb.messages), kb.messages)
        self.assertEqual( bnum, len(kb._batteries))
        self.assertEqual( bnum, len(kb._ids))
        self.assertEqual( bnum, len(kb.get_list()))  # no ids

        for b in kb._batteries:
            self.assertFalse(b.invalid, b.id)

        rp = kb.get_remaining_power()
        self.assertNotEqual( 0, rp[0])
        self.assertEqual( 100.0, rp[1])


    ################################################
    def test_default_batt_name_section(self):
        """Device have invalid battery definition in its own section."""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init['battery.main'] = {'type': 'pb', 'vnom': '48', 'capacity_ah': '100'}

        self._perform_good_battery_defs_checks(conf_init, 1)


    ################################################
    def test_good_section(self):
        """Device have invalid battery definition in its own section."""
        conf_init = copy.deepcopy( self.tpl_config )
        conf_init[self.tpl_dev_section]['batteries'] = 'bat1'
        conf_init['battery.bat1'] = {'type': 'pb', 'vnom': '48', 'capacity_ah': '100'}

        self._perform_good_battery_defs_checks(conf_init, 1)

        conf_init[self.tpl_dev_section]['batteries'] = 'bat1, bat2'
        conf_init['battery.bat2'] = {'type': 'pb', 'vnom': '48', 'capacity_ah': '300'}

        self._perform_good_battery_defs_checks(conf_init, 2)


########################################
if __name__ == '__main__':
    unittest.main()
