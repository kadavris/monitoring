# mikrotik2mqtt - Collecting hardware state and net statistics from MikroTik router(s)
Tested under Fedora Linux  
Requires:
* python3
* SSH module (https://github.com/ParallelSSH/ssh-python)  

## Slightly longer intro
This script produces reports on a MikroTik brand router's:
1) Health: temperature and PSU voltage
2) Network statistics per interface specified

And passes it to the [MQTT](https://en.wikipedia.org/wiki/MQTT) publishing agent.  
Specifically, the [mqtt-tool](https://github.com/kadavris/mqtt) was designed to be usable in this case.  
Although you can use any other program that does your own bidding.  

### The .ini file
The default directory for .ini placement is `/etc/smarthome/reporters/`
and default config name is `/etc/smarthome/reporters/mikrotik.ini`

Please look into provided `mikrotik.ini.sample` file for the description of configurable options.  

### The MQTT hierarchy tree
See .ini file for options with actual names  
All things are nested under the .ini's `topic_root`.

**NOTE! You need to configure it to be different for each of monitored routers.**   

Information of available upgrades to hardware/packages can be put there
if you didn't configured `topic_upgrades`

Then there are topics dedicated to bear specific bits of data, that should be available without the need of parsing:
* `<topic_voltage>` - device's PSU voltage
* `<topic_temperature>` - degrees of Celsius
* `<topic_traffic>` - top of traffic statistics hierarchy
* `<root_topic/updated>` - When any of this device's hierarchy was last updated:
  `{ "date":"Human readable date/time", "timestamp":UNIX_timestamp }`

The repo is in <https://github.com/kadavris/monitoring>  
Copyright by Andrej Pakhutin (pakhutin at gmail)  
See LICENSE file for licensing information
