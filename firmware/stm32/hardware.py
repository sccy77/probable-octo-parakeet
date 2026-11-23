# hardware.py
"""
@brief 硬件底层驱动模块
@note 只负责GPIO输出、按键读取，不含业务判断
"""
from machine import Pin

from configy  import *


class HardwareDriver:
    def __init__(self):
        # 输出端口初始化，默认关闭
        
        self.relay_dev = Pin(PIN_RELAY, Pin.OUT, value=0)
        self.fan_dev   = Pin(PIN_FAN,   Pin.OUT, value=0)
        

    def set_relay(self, state: bool):
        self.relay_dev.value(1 if state else 0)

    def set_fan(self, state: bool):
        self.fan_dev.value(1 if state else 0)

    def all_output_off(self):
        self.set_relay(False)
        self.set_fan(False)
