from configparser import ConfigParser
from kadpy.kbattstats import KBattStats
from kadpy.kbattlead import KBattLead
from kadpy.kpowerutils import KPowerDeviceCommons


class KBatteries:
    """
    Wrapper class for providing aggregate data from all connected batteries
    """
    def __init__(self, dev_commons: KPowerDeviceCommons, config: ConfigParser, old_stats: dict | None) -> None:
        self.capacity_wh: int = 0  # total capacity for all connected batteries
        self.commons = dev_commons
        self.messages: list[str] = []
        self._batteries: list[KBattStats] = []
        self._ids: list[str] = []  # valid battery ids for quick access

        dev_sect_name = 'power.' + self.commons.dev_id
        dev_conf = config[dev_sect_name]

        if old_stats is None:
            old_stats_batdict = None
        else:
            old_stats_batdict = old_stats.get('batteries', None)

        if 'batteries' in dev_conf:
            _ids = [ bname.strip() for bname in dev_conf['batteries'].split(',') ]
        else:
            _ids = [ 'main' ]

        for bid in _ids:
            batt_sect_name = 'battery.' + bid
            if batt_sect_name not in config:
                self.messages.append(f'ERROR: battery section {batt_sect_name} is not found in config')
                continue

            batt_conf = config[batt_sect_name]
            if 'type' not in batt_conf:
                self.messages.append(f'ERROR: battery section "{batt_sect_name}" have no battery information')
                continue

            btype = batt_conf['type'].strip()

            if old_stats_batdict is not None and bid not in old_stats_batdict:
                self.messages.append(f'WARNING: stats file is missing battery "{bid}" section')

            if btype == 'pb':
                self._batteries.append(KBattLead(bid, dev_commons, config, old_stats_batdict))
                self._ids.append(bid)
            # elif bt == 'lifepo':
            #         self.batteries.append(KBattLiFePO(bid, dev_defaults, config, old_stats_batteries))
            else:
                # KBattStats is a failsafe to be able to provide some basic services
                #self._batteries.append(KBattStats(bid, dev_commons, config, old_stats_batteries))
                self.messages.append(f'ERROR: config section "{batt_sect_name}" has invalid battery type')
                continue

            if self._batteries[-1].invalid:
                self.messages.extend(self._batteries[-1].messages)
            else:
                self.capacity_wh += self._batteries[-1].capacity_wh

        if old_stats is not None:  # purging our own info from old stats, while checking if there are extra data
            if old_stats_batdict is not None:
                for bid in old_stats_batdict.keys():
                    self.messages.append(f'NOTE: stats file has an extra batteries section: "{bid}"')
                del old_stats['batteries']
            else:
                self.messages.append('WARNING: stats file is missing "batteries" section')


    ########################################
    def __getitem__(self, index: str) -> KBattStats:
        return self.by_id(index)


    ########################################
    def by_id(self, _id: str) -> KBattStats | None:
        """Returns a battery object by its ID"""
        for b in self._batteries:
            if b.id == _id:
                return b

        return None


    ########################################
    def collect_messages(self) -> list[str]:
        to_ret = self.messages.copy()
        for b in self._batteries:
            to_ret.extend(b.messages)

        return to_ret


    ########################################
    def process_upsc_data(self, upsc_data: dict) -> None:
        """Will process new upsc data"""
        for b in self._batteries:
            b.process_upsc_data(upsc_data)


    ########################################
    def stats_file_append(self, file) -> None:
        """Append local info as JSON to the file being saved"""
        file.write('\n"batteries":{\n')
        add_comma = False
        for b in self._batteries:
            b.stats_file_append(file)
            if add_comma:
                file.write(',\n')
            else:
                add_comma = True

        file.write('}\n')


    ########################################
    def get_list(self) -> list[str]:
        """Returns a list of device-attached battery IDs"""
        return self._ids.copy()


    ########################################
    def get_remaining_power(self) -> tuple[int, float]:
        """Return a sum of batteries remaining capacity: tuple: (remaining Wh: int, remaining percentage: float)"""

        rwh: int = 0
        cap: int = 0
        for b in self._batteries:
            rwh += b.get_remaining_wh()
            cap += int(b.capacity_wh)

        return rwh, (0.0 if cap == 0 else round(100.0 * rwh / cap, 1))

