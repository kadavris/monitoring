## Notes about permastats content
This is intended to be more of a notes to myself though.

.ini options:
    - `perma_storage` - a path where to save stuff
    - `stats_topic` - with the current battery statistics json

## KBatt* classes
### What is monitored locally
1) Non-sequential data:
    - `load` - current load as reported in `upd_load`
    - `discharging` - bool - is battery discharging now?

    - UPS itself (copies of .ini fields):
      - `power_rating` - int
      - `power_rating_unit` - 'va'/'w'
      - `load_reported_as` - percent,va,w
      - `power_factor` - Effectiveness of conversion. default is 0.8

### What is going into storage?
Each device save file is separate. The file name scheme is:
`'mqtt-power.' + <device id> + '.json'`
The JSON items:
```JSON5
{
  "dev_id": "device ID from config",
  "messages": [],  // ERROR messages. Will mark instance as invalid on load
  "ts": 0, // int. current timestamp. Save-time in the file
  "started": 0, // int. time this device's stats collection has begun
  // Hourly UPS data (non-moving, accumulating)
  // We'll use this for a more precise prognostic calculations in blackout
  "hourly_load_avg": [], // [24 x float] load average by hour.
  "hourly_load_samples": [],// [24 x int] number of samples collected so far.

  // UPS data goes under `ups` object:
  "ups": {
    'power_rating': 0,  // normalized to Watts
    'load_factor': 1.0  // reported load to Watts conversion factor 
  },
  
  "batteries":
  {
    // Battery data goes in `batteries` object, each as objects with the name of `<battery id>`:
    "some battery ID": { // KBattLead will use "main"
      "registered": [0, "Human-readable date"], // when we started monitoring this one: timestamp + normal date
      // Settings (from .ini's `battery`):
      "batt_type": "pb or lifepo",
      "batt_vnom": 48, // Nominal voltage (in quantities of 12V)
      "batt_cap": 100, // Nominal capacity in A/h

      "health": 
      {
        "cycles": [10,20,30], //<nice>,<normal>,<worst> - counts of charge cycles detected of each kind
        "status": "<status msg>", // OK or whatever
        "wellness": 100, // Computed wellness index: 0-100%
        "tbf": -1, //time before fail (in weeks) or -1
      },

      // Weekly data. Up to 1 year: 52 weeks. Maybe more
      // NOTE: a word 'weeks' here are used for convenience and simplicity of meatbags comprehension.
      // It's not bound to calendar weeks, but denotes sequences of periods of _SECONDS_IN_A_WEEK.  
      "weekly": {
        "start_ts": [], // int start of the 'week' timestamp
        // average (dis-)charging speeds ( time / ups load). (See .ini's `power_rating`)  
        // Breakdown by 5% charge sectors: 21-long arrays each week  
        "discharge_speed_avg": [], // float. for discharge: timings
        "discharge_speed_samples": [], // int. samples per percentage step for avg
        "charge_speed_avg": [], // float. for charging: timings
        "charge_speed_samples": [], // int. for charging: samples,

        "blackouts_count": 0, // int. # of events
        "blackouts_time": 0.0 // float. hours
      },
    }, // end of some battery data
  }, // end of batteries object
}
```
