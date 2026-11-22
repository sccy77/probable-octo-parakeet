# main yjh.py
"""
@brief 主调度入口
"""
import time
from config import *
from hardware import HardwareDriver
from logic import condense_control_logic


def main_task():
    hw = HardwareDriver()
    

    while True:
        

        # 后续对接C同学传感器，这里先模拟数据
        temp = 22.0
        humi = 80.0

        
        action = condense_control_logic(temp, humi)
            
        hw.set_fan(action["fan"])
        hw.set_relay(action["relay"])
        

        time.sleep_ms(200)


if __name__ == "__main__":
    main_task()
