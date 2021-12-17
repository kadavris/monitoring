## mqtt-storage-sd-reports - Collect data from SDD/HDD S.M.A.R.T
See reporters.ini.sample's [storage] section for configuration options  
You can configure it to use nagios check_ide_smart and/or smartctl.  
smartctl will provide much more comprehensive data to gaze upon and analyze  

Tested under Fedora Linux and Windows 10  

Requires python3, smartctl and/or nagios's check_ide_smart plugin  

Directories:
* cygwin - shell scripts for easy service manipulations
* home-assistant - YAML sample configuration for including into Home Assistant
