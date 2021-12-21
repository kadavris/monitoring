# mqtt-storage-sd-reports - Collecting data from SDD/HDD S.M.A.R.T
You can configure it to use nagios **check_ide_smart** and/or **smartctl**.  
Use of smartctl will provide much more comprehensive data to gaze upon and analyze.  

Tested under Fedora Linux and Windows 10  
Requires python3, smartctl and/or nagios's check_ide_smart plugin  

Directories:
* [cygwin](https://cygwin.com) - shell scripts for easy service manipulations
* home-assistant - YAML sample configuration for including into [Home-Assistant](https://hass.io)

## Slightly longer intro
This script produces reports on storage health [S.M.A.R.T.](https://en.wikipedia.org/wiki/S.M.A.R.T.)
and passes it to the [MQTT](https://en.wikipedia.org/wiki/MQTT) publishing agent.  
Specifically, the [mqtt-tool](https://github.com/kadavris/mqtt) was designed to be usable in this case.  
Although you can use any other program that does your own bidding.  
It can use [nagios](https://nagios.com) plugin to simply check if drive is OK
and [smartmontools's](https://www.smartmontools.org/) smartctl utility to acquire more comprehensive data,
suitable for analysis.

### The .ini file
The default directory for .ini placement is `/etc/smarthome/reporters/`
and default config name is `/etc/smarthome/reporters/reporters.ini`

Please look into provided `reporters.ini.sample` file for description of configurable options.  
This script see the `[storage]` section as its own, so you can use single .ini for all utilities in this package  

### The MQTT hierarchy tree
See .ini file for options with actual names  
All things are nested under the .ini's `root_topic`. No data goes here. Just the start of hierarchy

Then the single drive's sub-topic is right under the root:

    <sd?>

It is named after /dev/sd? block device name.
JSON, high-level analysis of drive's state going here:
```
{
     NOTE: these may go from smart or nagios plugin:
     "status":"OK or error message...",
     "checks run":count, - the number of different check procedure we ran (smart/nagios plugin/etc)
     "checks with errors":count - and how many are failed
     
     NOTE: these are from smartctl only:
     "model":"device model + S/N",
     "tests done":count, - how many smart test are in log
     "tests failed":count, - and how many failed
     "tests inconclusive":count, - mostly, the count of aborted tests
}
```
Then there are topics dedicated to bear specific bits of data, that should be available without the need of parsing:
* `<power_on_time>` - device lifetime hours (S.M.A.R.T)
* `<type>` - "SSD" or "HDD" (guess on S.M.A.R.T data)
* `<temperature>` - degrees of Celsius (S.M.A.R.T)
* `<state_topic>` - nagios-like: "OK", "WARNING", "CRITICAL"
* `<updated_topic>` - When this device's hierarchy was last updated:
  `{ "date":"Human readable date/time", "timestamp":UNIX_timestamp }`

You may also specify the names of topics in .ini that will be filled with raw S.M.A.R.T data:
* `<attributes_topic>` - Will contain JSON-packed attributes:
   `id:{ "name":"Human-readable name", "value":"S.M.A.R.T value", "raw":"S.M.A.R.T raw" }`
* `<error_log_topic>` - Also JSON of raw error log entries from S.M.A.R.T:
   `{ lifetime_hours:"error_description", ...  }`
* `<raw_smart_topic>` - unprocessed smart data as received from smartctl. JSON format.
* `<tests_log_topic>` - JSON of raw tests log entries from S.M.A.R.T:
  `{ lifetime_hours:"test status", ...  }`

The repo is in <https://github.com/kadavris/monitoring>  
Copyright by Andrej Pakhutin (pakhutin at gmail)  
See LICENSE file for licensing information
