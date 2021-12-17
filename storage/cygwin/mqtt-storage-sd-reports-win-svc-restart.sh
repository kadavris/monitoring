#!/bin/bash
svcname='mqtt-storage-sd-reports'

echo Stopping $svcname
cygrunsrv -V -E $svcname

suff=`date +'%Y%m%d_%H%M%S'`

(cygrunsrv -V -Q $svcname | grep -E 'std(out|err) path' | sed -e 's/^.*: *//') |
while read l
do
  [ -f "$l" ] || continue
  echo Rotating log file: $l
  mv "$l" "$l.$suff"
done

echo Starting $svcname
cygrunsrv -V -S $svcname
