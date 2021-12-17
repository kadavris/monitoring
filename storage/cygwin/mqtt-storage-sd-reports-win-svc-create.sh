#!/bin/bash
# This script is used to create a Windows service for running reporter in the background
# CygWin is assumed to be installed
svcname='mqtt-storage-sd-reports'

if [ "$1" == "" ]
then
  echo 'Use with <path to log folder> argument'
  echo Run it from the folder where reporter scripts live
  echo example:
  echo $0 \"/cygdrive/d/log\"
  exit
fi

logdir="$1"
b=`which bash | head -1`
cwd=`pwd`

# We need to know where your python binary is,
# but cygwin tends to do a lot of nested symlinks to the most recent executable
p=`which python3 | head -1`
while [ -L "$p" ]
do
  p=`readlink "$p"`
done

echo Stopping.
cygrunsrv -V -E $svcname
echo Removing.
cygrunsrv -V -R $svcname
echo Installing.
cygrunsrv -V -I $svcname -p "${p}.exe" -a "$cwd/$svcname -l 20" -1 "$logdir/$svcname.log" -2 "$logdir/$svcname.log"
echo Running.
cygrunsrv -V -S $svcname
