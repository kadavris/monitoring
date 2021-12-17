## mqtt-power: UPS (and maybe other power appliances) monitoring
Uses NUT's upsc command line interface.  
See reporters.ini.sample's [power] section for configuration options  
Basically it runc upsc in loop and logs and/or pushes the data to some aggregtor.  
Requires python3, NUT
