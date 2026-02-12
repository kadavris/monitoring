#!/bin/bash
. /etc/smarthome/monitoring/service-env
#python3 ../mqtt-power --debug --config ./reporters.ini.test

python3 ../mqtt-power --debug

./kill_spawns.sh
