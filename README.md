# Hardware/software state reporting and analysis tools
Please consult README files within each directory for extended descriptions

Practically, most of the tools are bound to produce output to the MQTT topics.

* **boot-time** - miscellaneous, small stuff to be run once at boot time
* **cron** - things that may go into CRON
* **hardware** - Hardware monitoring
  * **mikrotik** - MikroTik router data to MQTT tool set. Home Assistant helpers provided. 
  * **power** - Power appliances (UPS) monitoring using NUT tools. Many options to report.
  * **storage** - Collecting S.M.A.R.T. data using nagios check_ide_smart and smartctl.

Majority of these utilities are intended to be used with [mqtt-tools](https://github.com/kadavris/mqtt-tools) MQTT interface  

This repo is at: <https://github.com/kadavris/monitoring>
