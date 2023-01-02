#!/bin/perl
use warnings;
use strict;
use Config::Tiny;

# https://www.home-assistant.io/integrations/sensor.mqtt/#new_format
# Put this script into HA config folder.
# Use with the following configuration.yaml settings:
#mqtt:
#  sensor: !include_dir_merge_list inc/mqtt/sensor
#sensor: !include_dir_merge_list inc/sensor/

# Open the config
my $config = Config::Tiny->read( 'sensors-storage-yaml-generator.ini', 'utf8' );

my $hdd_overheat = 49;
my $ssd_overheat = 60;

if( exists( $config->{_} ) )
{
    exists( $config->{_}->{ 'hdd_overheat' } ) and $hdd_overheat = $config->{_}->{ 'hdd_overheat' };
    exists( $config->{_}->{ 'ssd_overheat' } ) and $ssd_overheat = $config->{_}->{ 'ssd_overheat' };
}

my $yaml_mqtt_file = 'inc/mqtt/sensor/mqtt-sensor-storage-autogen.yaml';
my $yaml_sensors_file = 'inc/sensor/sensor-storage-autogen.yaml';

if ( -f $yaml_mqtt_file )
{
  print "File $yaml_mqtt_file already exists. Overwrite (y/N)? ";

  my $a = <STDIN>;
  chomp $a;

  if ( lc($a) ne 'y' )
  {
    exit 0;
  }
}

open( my $yaml_mqtt_h, '>', $yaml_mqtt_file ) or die "$yaml_mqtt_file: $!";
open( my $yaml_sensors_h, '>', $yaml_sensors_file ) or die "$yaml_sensors_file: $!";

my $separator = "\n#------------------------------------------------\n";

print "Generating:";

for my $host ( keys( %$config ) )
{
  next if $host eq '_';

  print "\n$host: ";

  print $yaml_mqtt_h $separator, "# host: $host", $separator;
  print $yaml_sensors_h $separator, "# host: $host", $separator;

  next if ! exists( $config->{ $host }->{ 'last_letter' } );

  my $ll = $config->{ $host }->{ 'last_letter' };

  for my $drive ( 'a'..$ll )
  {
    print " $drive";

    my $d = 'sd' . $drive;

    print $yaml_mqtt_h qq~
# $d

- name: "${host}_sd${drive}_mqtt_state"
  state_topic: "sys/$host/hw/storage/$d/state"

- name: "${host}_$d"
  state_topic: "sys/$host/hw/storage/$d/state"
  json_attributes_topic: "sys/$host/hw/storage/$d"

# json of smart attr. may be not present
- name: "$host: $d attributes"
  state_topic: "sys/$host/hw/storage/$d/attributes"
  json_attributes_topic: "sys/$host/hw/storage/$d/attributes"

- name: "$host: $d id"
  state_topic: "sys/$host/hw/storage/$d"
  value_template: "{{ state_attr( 'sensor.${host}_${d}', 'id' ) }}"

- name: "$host: $d model"
  state_topic: "sys/$host/hw/storage/$d"
  value_template: "{{ state_attr( 'sensor.${host}_${d}', 'model' ) }}"

- name: "$host: $d type"
  state_topic: "sys/$host/hw/storage/$d"
  value_template: "{{ state_attr( 'sensor.${host}_${d}', 'type' ) }}"

- name: "$host: $d temperature"
  state_topic: "sys/$host/hw/storage/$d/temperature"
  unit_of_measurement: '°C'
  device_class: temperature

# data freshness
- name: "$host: $d last update"
  state_topic: "sys/$host/hw/storage/$d/updated"
  json_attributes_topic: "sys/$host/hw/storage/$d/updated"
  value_template: "{{ value_json.timestamp }}"
~;

# NOTE:
# There is expire_after <seconds> attribute for mqtt sensor
# that we can use to check if data is fresh: state will be 'unavailable' if stale
    print $yaml_sensors_h qq~
- platform: template
  sensors:
    ${host}_${d}_freshness:
      friendly_name: "$host: $d data freshness check"
      value_template: >-
        {% set topic_u = 'sensor.${host}_${d}_last_update' %}
        {% if states( topic_u )|int(default=0) == 0 or as_timestamp(now()) - ( states( topic_u )|float ) > 1800 %}
          OLD: {{ state_attr( topic_u, 'date' ) }}
        {% else %}
          OK
        {% endif %}
      icon_template: >-
        {% set topic_u = 'sensor.${host}_${d}_last_update' %}
        {% if states( topic_u )|int(default=0) == 0 or as_timestamp(now()) - ( states( topic_u )|float ) > 1800 %}
          mdi:disc-alert
        {% else %}
          mdi:harddisk
        {% endif %}

- platform: template
  sensors:
    ${host}_${d}_problems:
      friendly_name: "${host}: ${d} problems"
      value_template: >-
        {% if states( 'sensor.${host}_${d}_freshness' ) != "OK" %}
          {{ states( 'sensor.${host}_${d}_freshness' ) }}
        {% else %}
          {% if states( 'sensor.${host}_${d}_mqtt_state' ) != 'OK' %}
            {{ states( 'sensor.${host}_${d}_mqtt_state' ) }}
          {% endif %}
          {% if states( 'sensor.${host}_${d}_temperature' ) != 'UNKNOWN' %}
            {% if states( 'sensor.${host}_${d}_type' ) == 'HDD' %}
              {% if states( 'sensor.${host}_${d}_temperature' )|float > $hdd_overheat %}
                OVERHEATING: {{ states( 'sensor.${host}_${d}_temperature' ) }}
                ( {{ states( 'sensor.${host}_${d}_id' ) }} )
              {% endif %}
            {% else %}
              {% if states( 'sensor.${host}_${d}_temperature' )|float > $ssd_overheat %}
                OVERHEATING: {{ states( 'sensor.${host}_${d}_temperature' ) }}
                ( {{ states( 'sensor.${host}_${d}_id' ) }} )
              {% endif %}
            {% endif %}
          {% endif %}
        {% endif %}
~;
  }
}

close($yaml_mqtt_h);
close($yaml_sensors_h);

print "\n";
