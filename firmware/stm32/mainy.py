# main yjh.py
"""
@brief 主调度入口
"""
import time
from config import*
from sensor_manager import get_data
from hardware import hardware_init,oled_init,set_fan,oled_update



def main():
    hardware_init()
    oled_init()

    while True:
        data = get_data()
        p1 = data["point1"]

        if not p1["valid"]:
            set_fan(False)
            oled_update(-99, -99, False)
        else:
            t = p1["temperature"]
            h = p1["humidity"]
            dew_margin = p1["dew_margin"]
            fan_need_on = dew_margin < config.DEW_MARGIN_DANGER_C
            set_fan(fan_need_on)
            oled_update(t, h, fan_need_on)

        time.sleep(config.SAMPLE_PERIOD_S)


if __name__ == "__main__":
    main()

