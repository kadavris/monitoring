#!/bin/bash
# This script is used to create a Windows service for running reporter in the background
# CygWin is assumed to be installed
svcname='mqtt-storage-sd-reports'
looptime=60  # how many secs to put in the --loop

if [ "$1" == "" ]
then
    echo 'Use with <path to log folder> argument'
    echo Run it from the folder where reporter scripts live
    echo example:
    echo $0 \"/cygdrive/d/log\"
    echo Or if you''re using non-cygwin python install, use windows path type:
    exit
fi

logdir="$1"
if [ ! -d "$1" ]; then
    echo log dir: $1 is not a directory!
    exit 1
fi

cwd=`pwd`

# We need to know where your python binary is,
# but cygwin tends to do a lot of nested symlinks to the most recent executable
pyexe=`which python3 2>/dev/null | head -1`

if [ "$pyexe" == "" ]; then
    # fallback to whatever will be
    pyexe=`which python | head -1`
fi

# resolve links if any
while [ -L "$pyexe" ]
do
    pyexe=`readlink "$pyexe"`
done

# not a full path yet?
if [ ! -f $pyexe ]
then
    pyexe=`which "$pyexe" | head -1`
fi

# querying python type
# Python 3.11.4 (tags/v3.11.4:d2340ef, Jun  7 2023, 05:45:37) [MSC v.1934 64 bit (AMD64)]
pver=`python -V -V`
if [[ $pver =~ 'cygwin' ]]; then
    ptype='cygwin'
    svccmd="$cwd/$svcname -l $looptime"
else
    ptype='native'
    cwd=$(/usr/bin/cygpath -w "$cwd/")
    svccmd="\"${cwd}$svcname\" -l $looptime -c \"$cwd\\reporters.ini\""
fi

echo 'Stopping.'
/usr/bin/cygrunsrv -V -E $svcname
echo 'Removing.'
/usr/bin/cygrunsrv -V -R $svcname
echo 'Installing:'
echo "$ptype python found at '$pyexe'"
/usr/bin/cygrunsrv -V -I $svcname -p "${pyexe}" -a "$svccmd" -1 "$logdir/$svcname.log" -2 "$logdir/$svcname.log"
/usr/bin/cygrunsrv -V -Q $svcname
#echo 'Running.'
#/usr/bin/cygrunsrv -V -S $svcname
