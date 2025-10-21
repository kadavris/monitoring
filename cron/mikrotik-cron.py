import argparse
import paramiko
import re
import sys
import signal

# This script talks to Mikrotik RouterOS device via SSH and reports bad health and if there are updates available to stderr.
# Copyright by Andrej Pakhutin (pakhutin <at> gmail)
# http://github.com/kadavris/monitoring
# License: see accompanying LICENSE file

def do_help():
    print("""Use mikrotik_monitor.py [switches] <path to config file>
Switches:
    -p, --power     - show voltage
    -t, --temp      - show temperature
    -u, --upgrades  - check for upgrades
    -v, --verbose   - verbose operations. Report any values, not out-of-bounds only

By default, it checks all with non-verbose mode.

Config file has simple, 1 line format:
address "login" "password"
""")
    sys.exit(0)

# Set a timeout for the SSH connection and commands
def alarm_handler(signum, frame):
    raise TimeoutError("SSH connection or command timed out")

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('config_file', help='Path to the configuration file')
parser.add_argument('-p', '--power', action='store_true', help='Show voltage')
parser.add_argument('-t', '--temp', action='store_true', help='Show temperature')
parser.add_argument('-u', '--upgrades', action='store_true', help='Check for upgrades')
parser.add_argument('-v', '--verbose', action='store_true', help='Verbose operations')
parser.add_argument('-h', '--help', action='store_true', help='Show this help message and exit')

args = parser.parse_args()

if args.help:
    do_help()

# If no specific checks are requested, perform all checks by default
if not (args.power or args.temp or args.upgrades):
    args.power = True
    args.temp = True
    args.upgrades = True

try:
    with open(args.config_file, 'r') as f:
        config_line = f.readline().strip()
except FileNotFoundError:
    print(f"Error: Config file '{args.config_file}' not found.", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error reading config file: {e}", file=sys.stderr)
    sys.exit(1)

match = re.match(r'^\s*(\S+)\s+"([^"]+)"\s+"([^"]+)"', config_line)
if not match:
    print(f"Bad config format in {args.config_file}", file=sys.stderr)
    sys.exit(1)

addr, login, password = match.groups()

signal.signal(signal.SIGALRM, alarm_handler)
signal.alarm(60) # 60-second timeout

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(addr, username=login, password=password, timeout=10) # 10-second connection timeout
    signal.alarm(0) # Clear the alarm after successful connection
except TimeoutError as e:
    print(f"Error connecting to {addr}: {e}", file=sys.stderr)
    sys.exit(1)
except paramiko.AuthenticationException:
    print(f"Authentication failed for {login}@{addr}", file=sys.stderr)
    sys.exit(1)
except paramiko.SSHException as e:
    print(f"SSH error connecting to {addr}: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred while connecting to {addr}: {e}", file=sys.stderr)
    sys.exit(1)

try:
    if args.power or args.temp:
        stdin, stdout, stderr = ssh.exec_command("/system health print")
        ssh_out = stdout.read().decode().strip()
        # print('-' * 30, ssh_out, '\n\n')

        # Voltage check
        voltage_match = re.search(r'voltage:\s+([\d.]+)', ssh_out)
        if voltage_match:
            v = int(float(voltage_match.group(1))) # Convert to float first, then int
            if args.power:
                if v < 20 or v > 28:
                    print(f"{addr} Mikrotik voltage is out of bounds: {v}", file=sys.stderr)
                elif args.verbose:
                    print(f"{addr} Mikrotik voltage is: {v}", file=sys.stderr)

        # Temperature check
        temp_match = re.search(r'temperature:\s+([\d.]+)', ssh_out)
        if temp_match:
            t = int(float(temp_match.group(1))) # Convert to float first, then int
            if args.temp:
                if t > 60:
                    print(f"{addr} Mikrotik temperature is too high: {t}", file=sys.stderr)
                elif args.verbose:
                    print(f"{addr} Mikrotik temperature is: {t}", file=sys.stderr)

    if args.upgrades:
        has_upgrades = 0

        # Check Routerboard firmware updates
        stdin, stdout, stderr = ssh.exec_command("/system routerboard print")
        ssh_out = stdout.read().decode().strip()
        # print('-' * 30, ssh_out, '\n\n')

        current_firmware_match = re.search(r'current-firmware:\s+(\S+)', ssh_out)
        upgrade_firmware_match = re.search(r'upgrade-firmware:\s+(\S+)', ssh_out)

        if current_firmware_match and upgrade_firmware_match:
            current_ver = current_firmware_match.group(1)
            upgrade_ver = upgrade_firmware_match.group(1)
            if current_ver != upgrade_ver:
                print(f"{addr} Mikrotik firmware upgrade available: {current_ver} -> {upgrade_ver}", file=sys.stderr)
                has_upgrades += 1

        # Check system package updates
        stdin, stdout, stderr = ssh.exec_command("/system package update print")
        ssh_out = stdout.read().decode().strip()
        # print('-' * 30, ssh_out, '\n\n')

        installed_version_match = re.search(r'installed-version:\s+(\S+)', ssh_out)
        latest_version_match = re.search(r'latest-version:\s+(\S+)', ssh_out)

        if installed_version_match and latest_version_match:
            installed_ver = installed_version_match.group(1)
            latest_ver = latest_version_match.group(1)
            if installed_ver != latest_ver:
                print(f"{addr} Mikrotik packages upgrade available: {installed_ver} -> {latest_ver}", file=sys.stderr)
                has_upgrades += 1

        if has_upgrades == 0 and args.verbose:
            print(f"{addr} Mikrotik: no upgrades available", file=sys.stderr)

except TimeoutError as e:
    print(f"Error executing command on {addr}: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An error occurred during SSH command execution: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    ssh.close()
    signal.alarm(0) # Clear any pending alarm
