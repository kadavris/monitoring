## Notes about permastats content
This is intended to be more of a notes to myself though

.ini options:
    - `perma_storage` - a path where to save stuff
    - `stats_topic` - with the current battery statistics json

## KBatt* classes
### What is monitored locally
1) Non-sequential data:
    - `load` - current load as reported in `upd_load`
    - `discharging` - bool - is battery discharging now? 

    - UPS itself (copies of .ini fields):
      - `power_rating`
      - `power_rating_unit`
      - `load_reported_as` - percent,va,w

### What is going into storage?
`{ "dev1_id": { <device data> }, ... "devN_id": { <device data> } }`
1) Non-sequential data:
    - battery settings (from .ini's `battery`):
      - `batt_type` - pb or lifepo
      - `batt_vnom` - Nominal voltage (in quanitites of 12V)
      - `batt_cap` - Nominal capacity in A/h
      - `pack_size` - computed from `vnom`... so set it right

    - battery health:
      - `cycles: [<nice>,<normal>,<worst>]` - counts of charge cycles detected of each kind depending on battery parameters
      - `health: {`
        - `"status":"<status msg>"`
        - `"cycles_left":<cycles est>` - IDK if this will be kept
        - `"tbf":<time before fail (weeks)>`

    - general data:
      - `ts` - current timestamp. Save-time in the file
      - `started` - time this device's stats began

2) Hourly data (non-moving, per-hour)
    - We'll use this for more precise prognostic calculations in blackout
      - `hourly_load_avg` - load average by hour for all times.
      - `hourly_load_samples` - number of samples collected so far

3) Weekly data. Up to 1 year: 52 weeks.  
   NOTE: a word 'weeks' here are used for convenience and simplicity of meatbags comprehension.
   It's not bound to calendar weeks, but denotes sequences of periods of _SECONDS_IN_A_WEEK.  
    - `start_ts` - start of the week
    - Average (dis-)charging speeds ( time / ups load). (See .ini's `power_rating`)  
      Breakdown by 5% charge sectors: 21-long arrays each week  
      - `discharge_speed_avg` - for discharge: timings
      - `discharge_speed_samples` - samples per percentage step for avg
      - `charge_speed_avg` - for charging
      - `charge_speed_samples`
    - Blackouts:
      - `blackouts_count` - # of events
      - `blackouts_time` - minutes
