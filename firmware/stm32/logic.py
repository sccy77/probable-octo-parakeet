# logic.py
"""
@brief 业务逻辑判断模块
@note 接收温湿度，输出控制动作，不直接操作硬件
"""
from configy import *


def condense_control_logic(temp: float, humi: float):
    """
    @brief 防凝露判断逻辑
    @param temp: 温度
    @param humi: 湿度
    @return dict: relay, fan
    """
    heat_en = False
    relay_en = False
    fan_en  = False
    if temp<RELAY_ON_TEMP:
       relay_en=True
    if temp<RELAY_OFF_TEMP:
        relay_en=False

    if temp > FAN_ON_TEMP:
        fan_en = True

    return {
        "relay": relay_en,
        "fan": fan_en
    }
