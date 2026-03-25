#!/bin/bash
. /etc/smarthome/monitoring/service-env
export PYTHONPATH

#python3 ../mqtt-power --debug --config ./reporters.ini.test

python3 ../mqtt-power --debug

sh ./kill_spawns.sh
