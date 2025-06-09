# mqtt-power: UPS (Uninterruptible Power Supply) monitoring
Uses [NUT's](https://networkupstools.org) `upsc` command line interface to query UPS status.  
See [reporters.ini.power_sample]() `[power]` section for configuration options  

Files in the package:
* mqtt-power.service.sample - For running as systemd service
* [testing]() - So very internal stuff for debugging
* reporters.ini.power_sample - An .ini file sample
* [home-assistant]() - Home Assistant <https://hass.io> integration helpers

Basically it runs upsc in a loop and logs and pushes the data into MQTT.  

Requires python3, NUT

## Slightly longer intro

### The .ini file
The default directory for .ini placement is `/etc/smarthome/reporters/`
and default config name is `/etc/smarthome/reporters/reporters.ini`

Please look into provided `reporters.ini.power_sample` file for description of the configurable options.  
This script sees the `[power]` section as its own, so you can use single .ini for all utilities in this monitoring package  

### Mode of operation and constraints
As this is all dependent on upsc's output, and fundamentally on a concrete UPS device willingless to report or conceal some data, we assume that the basic report should contain this minimal list of attributes:
* device.mfr - Device manufacturer, e.g. "SomeVendor"
* device.model: Device model, e.g. "UPSUS Giganticus 9000"
* device.type: The type of the device, e.g. "ups"
* ups.status: The basic status, e.g. "OL", "BOOST", etc

Other attributes can be marked as required in .ini

### The MQTT hierarchy tree
For a complete list of options with actual names see .ini file  
All things are nested under the .ini's `root_topic`. No data goes here. Just the top of the hierarchy

Then the single device's sub-topic is right under the root: `<dev_id>`  
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

All other data is going directly to the `device_topic`, JSON packed.  
Note that the content of message may vary greatly depending on UPS status report.
See `bulk_report` keyword in .ini file  
*NOTE: If you accidently put non-existent attribute into this list, it will be simply skipped with a notification*  
Additionally, there are some statistics that you may find useful:
- Daily:
  - `voltage_mean_day` - Mean voltage
  - `frequency_mean_day` - Mean 
- Hourly:
  - `voltage_mean_hour` - mean voltage
  - `frequency_mean_hour` - mean frequency
- Last minute:
  - `voltage_mean_minute` - mean voltage
  - `frequency_mean_minute` - mean frequency
