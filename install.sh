#!/bin/bash
# This is the install script for kadavris/monitoring repo
# Run without arguments to get help

ENVFILE="./service-env"

if [ "$1" == "" ]; then
    echo "Use 'install.sh [-e <env file name>] <name> ... <name>'"
    echo "  '-e' option is to provide the existing environment variable list file with correct paths"
    echo "     by default $ENVFILE will be used"
    echo "For '<name>' - specify 'all' to install all of the utilities from this repo,"
    echo "or a combination of 'mikrotik', 'power' and 'storage' to install specific ones."
    echo "NOTE: This script will not overwrite existing .ini files."
    exit 0
fi

SYSTEMD="/etc/systemd/system"

USER="smarthome"
GROUP="smarthome"

/usr/bin/id "$USER" 2> /dev/null
if [ $? == 1 ]; then
    if [ -d "$CONFDIR" ]; then
        USER=$(/usr/bin/stat --printf %U "$CONFDIR")
        GROUP=$(/usr/bin/stat --printf %G "$CONFDIR")
        echo "I see that you use $USER:$GROUP credentials. Will obey."
    else
        echo "ERROR! Cannot determine what UID/GID to use."
        echo "You may want to add these by running:"
        echo "useradd -d '$CONFDIR' -s /sbin/nologin -g $GROUP $USER"
        exit 1
    fi
fi

OWNER="--owner=${USER} --group=${GROUP}"

EXEOPT="-v -C -D ${OWNER} --mode=0755"
SVCOPT="-v -C ${OWNER} --mode=0644"
INIOPT="-v -C -D ${OWNER} --mode=0640"

INST="/usr/bin/install"

while getopts "e:" OPT; do
    if [ "$OPT" = "e" ]; then
        ENVFILE=$OPTARG
    fi
done

# We'll use BINDIR, CONFDIR and PYTHONPATH from here:
. $ENVFILE
export BINDIR CONFDIR PYTHONPATH

# python's import dest
export py_namespace="$PYTHONPATH/kadpy"

# in: <src file> <dst dir> <new name or ''> <install params>
function install_to_dir_w_check() {
    src=$1; shift
    ddir=$1; shift
    nn=$1; shift
    [ "$nn" == "" ] && nn=$(basename "$src")
    nn="${ddir}/${nn}"

    # only if new file is newer we will copy it as .ini.sample for suggestions
    if [ "$src" -nt "$nn" ]; then
        [ -e "$nn" ] && nn="${nn}.new"
        echo "+ Will install $src ==> $nn"
        $INST $* "$src" "$nn"
    else
        echo "- Skipping older file: $src"
    fi
}

function install_deps() {
    install_to_dir_w_check "service-env" "$CONFDIR" "service-env" "$INIOPT"
    $INST $EXEOPT -t "$py_namespace" "imports/__init__.py"
    $INST $EXEOPT -t "$py_namespace" "imports/kmqtt.py"
    if [ -z "$1" ]; then
        return
    fi
    for d in $*; do
        $INST $EXEOPT -t "$py_namespace" "imports/$d"
    done
}

function install_mikrotik() {
    install_deps
    srcd="hardware/mikrotik"
    $INST $EXEOPT "${srcd}/mikrotik2mqtt" "$BINDIR"
    install_to_dir_w_check "${srcd}/mikrotik2mqtt.service.sample" "${SYSTEMD}" "mikrotik2mqtt.service" "$SVCOPT"
    install_to_dir_w_check "${srcd}/mikrotik2mqtt.ini.sample" "$CONFDIR" "mikrotik2mqtt.ini" "$INIOPT"
}

function install_power() {
    install_deps kbattstats.py kbattlead.py
    srcd="hardware/power"
    $INST $EXEOPT "${srcd}/mqtt-power" "$BINDIR"
    install_to_dir_w_check "${srcd}/mqtt-power.service.sample" "${SYSTEMD}" "mqtt-power.service" "$SVCOPT"
    install_to_dir_w_check "${srcd}/mqtt-power.sample.ini" "$CONFDIR" "mqtt-power.ini" "$INIOPT"
}

function install_storage() {
    install_deps
    srcd="hardware/storage"
    $INST $EXEOPT "${srcd}/mqtt-storage-sd-reports" "$BINDIR"
    install_to_dir_w_check "${srcd}/mqtt-storage-sd-reports.service.sample" "${SYSTEMD}" "mqtt-storage-sd-reports.service" "$SVCOPT"
    install_to_dir_w_check "${srcd}/mqtt-storage.sample.ini" "$CONFDIR" "mqtt-storage.ini" "$INIOPT"
}

########################
if [ "$1" == "all" ]; then
    list="mikrotik power storage"
else
    list="$1"
fi

if [ ! -d "$CONFDIR" ]; then
    /usr/bin/mkdir -p -m 0770 "$CONFDIR"
    /usr/bin/chown "$USER:$GROUP" "$CONFDIR"
fi

for opt in $list
do
    install_$opt
done

echo "You may need to check the permissons and ownership of intermediate directories:"
echo "  - $CONFDIR"
echo "  - $BINDIR"
echo "  - $PYTHONPATH"
echo "... due to 'install' utility not making it all the way up"