import kbattstats

class KBATTLIFEPO(kbattstats.KBattStats):
    def __init__(self, save_file: str, dev_data: dict):
        super().__init__(save_file, dev_data)
        self.type: int = kbattstats.BT_LIFEPO

    ########################################
    def get_charge_percent(self, data: dict) -> int:
        """
        Based on device's configuration will return batterg charge level as reported by device
        or calculated by other means
        :param data: dict: data collected from device interface
        :return: int: charge level in percents
        """
        return 100


    ########################################
    def update_stats(self, data: dict) -> None:
        if self.invalid:
            return
