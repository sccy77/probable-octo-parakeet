# -*- coding: utf-8 -*-
"""
data_filter.py —— 每个测点、温度和湿度分别做滑动平均滤波（纯算法，不依赖硬件）

写法兼容：标准 Python 3 与 MicroPython（用普通 list，不用 deque）。

核心规则：
1. 每个测点各有两个独立窗口（温度窗口、湿度窗口）。
2. 只有“读取成功且数值有效”的数据才会进入窗口。
3. 读取失败时：不入窗，并清空该测点窗口，输出 valid=False、数值 None，
   避免失败前的旧数据在传感器恢复后与新数据混在一起，更不会冒充新数据。
"""


def _is_number(value):
    """排除 None、字符串、布尔、NaN、无穷大。"""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value == value and (value - value) == 0


def create_filter_state(point_names, window_size):
    """
    创建滤波器状态（一个字典），整个系统只创建一次。
    point_names: 测点名称列表，如 ["point1", "point2", "point3"]
    window_size: 滑动窗口大小（正整数），由 config.py 提供，这里不设默认值。
    """
    if not isinstance(window_size, int) or window_size < 1:
        raise ValueError("window_size 必须是 >= 1 的整数")

    state = {"window_size": window_size, "points": {}}
    for name in point_names:
        state["points"][name] = {"temp": [], "hum": []}
    return state


def _push(window, value, window_size):
    """把新值放进窗口末尾；超过窗口大小就丢掉最老的。"""
    window.append(value)
    while len(window) > window_size:
        window.pop(0)


def _average(window):
    """窗口为空返回 None，否则返回平均值。"""
    if len(window) == 0:
        return None
    return sum(window) / len(window)


def filter_temperature(state, point_name):
    """返回某测点当前温度滑动平均值；窗口为空时返回 None。"""
    return _average(state["points"][point_name]["temp"])


def filter_humidity(state, point_name):
    """返回某测点当前湿度滑动平均值；窗口为空时返回 None。"""
    return _average(state["points"][point_name]["hum"])


def update_filter(state, point_name, temperature, humidity, valid):
    """
    用一次新读数更新某测点的滤波器，并返回滤波结果。

    返回字典：
        {"temperature": 滤波后温度或 None,
         "humidity":    滤波后湿度或 None,
         "valid":       True/False,
         "samples":     当前窗口内有效样本数}
    """
    point = state["points"][point_name]
    window_size = state["window_size"]

    reading_ok = valid is True and _is_number(temperature) and _is_number(humidity)

    if not reading_ok:
        # 失败：清空窗口，不保留任何旧数据
        point["temp"] = []
        point["hum"] = []
        return {"temperature": None, "humidity": None, "valid": False, "samples": 0}

    _push(point["temp"], temperature, window_size)
    _push(point["hum"], humidity, window_size)
    return {
        "temperature": filter_temperature(state, point_name),
        "humidity": filter_humidity(state, point_name),
        "valid": True,
        "samples": len(point["temp"]),
    }
