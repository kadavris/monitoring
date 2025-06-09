# Hardware/software state reporting and analysis tools
Please consult README files within each directory for extended descriptions

Most of the tools are bound to produce output to the MQTT topic(s) that you specify in each tool configuration.

* [**boot-time**](boot-time/README.md) - miscellaneous, stuff to be run once at system boot time
* [**cron**](cron/README.md) - things that may go into CRON
* **hardware** - Hardware monitoring
  * [**mikrotik**](hardware/mikrotik/README.md) - MikroTik router data to MQTT tool set. Home Assistant helpers provided. 
  * [**power**](hardware/power/README.md) - Power appliances (UPS) monitoring using NUT tools. Many options to report.
  * [**storage**](hardware/storage/README.md) - Collecting S.M.A.R.T. data using nagios check_ide_smart and smartctl.

Majority of these utilities are intended to be used with [mqtt-tools](https://github.com/kadavris/mqtt-tools): MQTT interfacing tools, written in python

[This repo on github](https://github.com/kadavris/monitoring)
