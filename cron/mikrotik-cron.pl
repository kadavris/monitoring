#!/bin/perl
# This script reports to stderr Mikrotik RouterOS device's bad health and if there are updates available.
# Copyright by Andrej Pakhutin (pakhutin <at> gmail)
# http://github.com/kadavris/smarthome
# License: see accompanying LICENSE file
# The parameters are: path to config file
# The 1st line of config is: <router's address> "<login>" "<password>"
use warnings;
use strict;
use Net::SSH::Perl;
use Getopt::Long;

my $verbose = 0; # only report out of range stuff
my $get_power = 0;
my $get_temp = 0;
my $get_upgrades = 0;

GetOptions(
  'p' => \$get_power,
  't' => \$get_temp,
  'u' => \$get_upgrades,
  'v' => \$verbose,
) or do_help();

$#ARGV == -1 and do_help();

if ( $get_power + $get_temp + $get_upgrades == 0 )
{
  $get_power = $get_temp = $get_upgrades = 1;
}

open CFG, $ARGV[0] or die "$ARGV[0]: $!";
$_ = <CFG>;
close CFG;

/^\s*(\S+)\s+"([^"]+)"\s+"([^"]+)"/ or die "Bad config format in $ARGV[0]";

my $addr = $1;
my $login = $2;
my $pass = $3;

$SIG{ALRM} = sub { exit(1) };
alarm 60; # device may be deadly busy

my $ssh = Net::SSH::Perl->new( $addr );
$ssh->login( $login, $pass );

my ($ssh_out, $ssh_err, $ssh_exit); # common output

if ( $get_power || $get_temp )
{
  ($ssh_out, $ssh_err, $ssh_exit) = $ssh->cmd( "/system health print" );
  #print '-'x30, $ssh_out, "\n\n";

  $ssh_out =~ /voltage:\s+([\d.]+)/s;
  my $v = int($1);

  if( $get_power )
  {
    if ( $v < 20 || $v > 28 ) # this is wild guess, really
    {
      print STDERR "$addr Mikrotik voltage is out of bounds: $v\n";
    }
    elsif ( $verbose )
    {
      print STDERR "$addr Mikrotik voltage is: $v\n";
    }
  }

  $ssh_out =~ /temperature:\s+([\d.]+)/s;
  my $t = int($1);

  if( $get_temp )
  {
    if ( $t > 60 )
    {
      print STDERR "$addr Mikrotik temperature is too high: $t\n";
    }
    elsif ( $verbose )
    {
      print STDERR "$addr Mikrotik temperature is: $t\n";
    }
  }
} # if ( $get_power || $get_temp )

if ( $get_upgrades )
{
  my $has_upgrades = 0;
  #---------------------------------------
  #/system routerboard print
  #       routerboard: yes
  #        board-name: hAP ac
  #             model: RB962UiGS-5HacT2HnT
  #          revision: r2
  #     serial-number: XXXXXXXXXX
  #     firmware-type: qca9550L
  #  factory-firmware: 6.44.6

  ($ssh_out, $ssh_err, $ssh_exit) = $ssh->cmd( "/system routerboard print" );
  #print '-'x30, $ssh_out, "\n\n";

  #  current-firmware: 6.48.3
  $ssh_out =~ /current-firmware:\s+(\S+)/s;
  my $current_ver = $1;

  #  upgrade-firmware: 6.48.3
  $ssh_out =~ /upgrade-firmware:\s+(\S+)/s;

  if( $current_ver ne $1 )
  {
    print STDERR "$addr Mikrotik firmware upgrade available: $current_ver -> $1\n";
    ++$has_upgrades;
  }

  #---------------------------------------
  # /system package update print  
  #            channel: stable
  #  installed-version: 6.48.3
  #     latest-version: 6.48.4
  #             status: New version is available
  ($ssh_out, $ssh_err, $ssh_exit) = $ssh->cmd( "/system package update print" );
  #print '-'x30, $ssh_out, "\n\n";

  $ssh_out =~ /installed-version:\s+(\S+)/s;
  $current_ver = $1;

  $ssh_out =~ /latest-version:\s+(\S+)/s;
  if( $current_ver ne $1 )
  {
    print STDERR "$addr Mikrotik packages upgrade available: $current_ver -> $1\n";
    ++$has_upgrades;
  }

  if ( $has_upgrades == 0 && $verbose )
  {
    print STDERR "$addr Mikrotik: no upgrades available\n";
  }
} # if ( $get_upgrades )

#---------------------------------------
($ssh_out, $ssh_err, $ssh_exit) = $ssh->cmd( "/quit" );

sleep 3;

###########################################
sub do_help
{
  print q~Use mikrotik-cron.pl [switches] <path to config file>
Switches:
	-p - show voltage
	-t - show temperature
	-u - check for upgrades
	-v - verbose operations. Report any values, not out-of-bounds only

By default it is to check all with non-verbose mode.

Config file has simple, 1 line format:
address "login" "password"
~;
  exit(0);
}
