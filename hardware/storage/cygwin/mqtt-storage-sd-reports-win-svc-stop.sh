#!/bin/bash
svcname='mqtt-storage-sd-reports'

echo Stopping $svcname
cygrunsrv -V -E $svcname
