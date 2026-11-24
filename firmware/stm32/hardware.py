# hardware.py
"""
@brief 硬件底层驱动模块
@note 只负责GPIO输出、按键读取，不含业务判断
"""
from machine import Pin,I2C
from configy import OLED_SDA,OLED_SCL

from configy  import *
from ssd1306 import SSD1306_I2C


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
oled = None

def oled_init():
    global oled
    i2c = I2C(1, sda=Pin(OLED_SDA), scl=Pin(OLED_SCL))
    oled = SSD1306_I2C(128, 64, i2c)
    oled.fill(0)
    oled.text("System Ready", 0, 0)
    oled.show()

def oled_update(temp: float, humi: float, fan_enable: bool):
    global oled
    if oled is None:
        return
    oled.fill(0)
    oled.text(f"Temp:{temp:.1f} C", 0, 0)
    oled.text(f"Humi:{humi:.1f} %", 0, 16)
    if fan_enable:
        oled.text("FAN: ON", 0, 32)
    else:
        oled.text("FAN: OFF", 0, 32)
    oled.show()
