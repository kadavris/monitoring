# mqtt-power: UPS, and other power appliances monitoring
Uses [NUT](https://networkupstools.org)'s `upsc` command line interface.  
See `reporters.ini.sample` `[power]` section for configuration options  

Files in the package:
* mqtt-power.service.sample - For running as systemd service
* mqtt-power-test-run - much very internal for debugging
* reporters.ini.sample - Sample of .ini file

Basically it runs upsc in loop and logs and/or pushes the data to some aggregtor.  

Requires python3, NUT

Directories:
* home-assistant - YAML sample configuration for including into [Home-Assistant](https://hass.io)

## Slightly longer intro

### The .ini file
The default directory for .ini placement is `/etc/smarthome/reporters/`
and default config name is `/etc/smarthome/reporters/reporters.ini`

Please look into provided `reporters.ini.sample` file for description of configurable options.  
This script see the `[power]` section as its own, so you can use single .ini for all utilities in this package  

### Mode of operation and constraints
As this is all dependent on upsc's output and fundamentally on concrete UPS device willingless
to report or conceal some data, we assume that the basic report should contain this minimal list of attributes:
* device.mfr - Device manufacturer, e.g. "EATON"
* device.model: Device model, e.g. "5E 1500i"
* device.type: The type of the device, e.g. "ups"
* ups.status: The basic status, e.g. "OL", "BOOST", etc

### The MQTT hierarchy tree
See .ini file for options with actual names  
All things are nested under the .ini's `root_topic`. No data goes here. Just the start of hierarchy

Then the single drive's sub-topic is right under the root: `<dev_id>`  
This is derived from .ini `device_topic` template

Then there are topics dedicated to bear specific bits of data, that should be available without the need of parsing.  
You can configure the attributes to post and associated topic names using .ini `one_to_one` keyword.  
For example:
* `type` - device type as reported via upsc:`device_type`
* `batt_charge` - battery charge level as reported via upsc:`battery_charge` 
* `in_volt` - Input voltage as reported via upsc:`input_voltage`
* `out_load` - Output load as reported via upsc:`ups_load`
* `<updated_topic>` - When this device's hierarchy was last updated:
  `{ "date":"Human readable date/time", "timestamp":UNIX_timestamp }`

All other data is going direct to `device_topic` JSON packed.  
Note that the content of message may vary greatly depending on UPS status report.
See `bulk_report` keyword in .ini file  
*NOTE: If you accidently put non-existent attribute into this list, it will be simply skipped with a notification*  
Additionally, there are some statistics that you may find useful:
- `voltage_mean_minute` - Mean voltage this **minute**
- `frequency_mean_minute` - Mean frequency this **minute**
- `voltage_mean_hour` - Mean voltage this **hour**
- `frequency_mean_hour` - Mean frequency this **hour**
- `voltage_mean_day` - Mean voltage this **day**
- `frequency_mean_day` - Mean frequency this **day**