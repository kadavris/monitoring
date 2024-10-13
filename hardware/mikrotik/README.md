# mikrotik2mqtt - Collecting hardware state and network statistics from the MikroTik router(s)
Tested under Fedora Linux 40+   
Requires:
* python3
* SSH module (https://github.com/ParallelSSH/ssh-python)  

## Slightly longer intro
This script uses SSH to access the MikroTik brand router's and produces several kinds of reports:
1) Health: temperature and PSU voltage
2) Network statistics per interface specified
3) Firewall counts for the rules that have a special tag in comment
4) User-defined firewall queries

And passes it to the [MQTT](https://en.wikipedia.org/wiki/MQTT) publishing agent.  
Specifically, the [mqtt-tool](https://github.com/kadavris/mqtt) was designed to be usable in this case.  
Although you can use any other program that does your own bidding.  

### The .ini file
The default directory for .ini placement is `/etc/smarthome/reporters/`
and default config name is `/etc/smarthome/reporters/mikrotik.ini`

See the [.ini file sample](mikrotik2mqtt.ini.sample) for options with actual names and verbose description  

### The MQTT hierarchy tree

All things are nested under the .ini's `topic_root`.
**NOTE! You need to configure it to be different for each of the monitored routers.**
Or there be a mess. You've been warned.

Information of available upgrades for hardware/packages can be put there
if you configured `topic_upgrades`

Then there are topics dedicated to bear specific bits of data, that should be available without the need of JSON parsing:
* `<topic_voltage>` - device's PSU voltage
* `<topic_temperature>` - degrees of Celsius

The topics that provide networking stats:
* `<topic_traffic>` - top of the traffic statistics hierarchy
* `<get_firewall_by_id>` - JSON of tagged firewall rules
* `<get_firewall_whereXXX>` - user-defined queries

Additionally, there is special topic that lets you see if the data is fresh:
`<root_topic/updated>`  
The package format is:
`{ "date":"Human readable date/time", "timestamp":UNIX_timestamp }`

---
# [Home assistant integration](homeassistant)

The perl script is provided for automatic generation of Sensors/Entities
using it's own and of the main tool .ini files. 

---
The repo is in <https://github.com/kadavris/monitoring>  
Copyright by Andrej Pakhutin (pakhutin at gmail)  
See the LICENSE file for licensing information
