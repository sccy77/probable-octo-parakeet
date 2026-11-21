# -*- coding: utf-8 -*-
"""
dew_point.py —— 露点温度与露点温差计算（纯算法，不依赖任何硬件）

写法兼容：电脑上的标准 Python 3，以及 MicroPython（只用 math 模块，不用 f-string、不用类型标注）。

使用 Magnus 近似公式：
    gamma = ln(RH / 100) + (17.62 * T) / (243.12 + T)
    Td    = (243.12 * gamma) / (17.62 - gamma)
    delta_T（露点温差）= T - Td
"""

import math

# ---- Magnus 公式系数（算法本身的常数，不属于“用户可调参数”）----
MAGNUS_A = 17.62
MAGNUS_B = 243.12

# ---- SHT30 数据手册给出的测量范围，用来判断输入是否合理 ----
# 待办：第二阶段写 config.py 时，如团队希望统一管理，可把这两个范围移过去。
TEMP_MIN_C = -40.0
TEMP_MAX_C = 125.0


def _is_number(value):
    """判断 value 是不是一个正常的数字（排除 None、字符串、NaN、无穷大）。"""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    # NaN != NaN；inf 减自己得到 NaN，两种情况都会被这里挡住
    return value == value and (value - value) == 0


def is_input_valid(temperature, humidity):
    """
    检查温度、湿度是否可以用来算露点。
    湿度必须 > 0：RH = 0 时 ln(0) 没有意义，会报错。
    """
    if not _is_number(temperature) or not _is_number(humidity):
        return False
    if temperature < TEMP_MIN_C or temperature > TEMP_MAX_C:
        return False
    if humidity <= 0.0 or humidity > 100.0:
        return False
    return True


def calculate_dew_point(temperature, humidity):
    """
    计算单个测点的露点温度（摄氏度）。
    输入无效时返回 None，由调用方决定如何处理，绝不返回假数值。
    """
    if not is_input_valid(temperature, humidity):
        return None

    gamma = math.log(humidity / 100.0) + (MAGNUS_A * temperature) / (MAGNUS_B + temperature)
    denominator = MAGNUS_A - gamma
    if denominator == 0:  # 理论上在合法输入范围内不会出现，这里只是兜底
        return None
    return (MAGNUS_B * gamma) / denominator


def calculate_dew_margin(temperature, dew_point):
    """
    计算露点温差 = 空气温度 - 露点温度。
    数值越小，越接近凝露。任一输入无效时返回 None。
    """
    if not _is_number(temperature) or not _is_number(dew_point):
        return None
    return temperature - dew_point


def calculate_all_dew_points(sensor_data):
    """
    对每个测点分别计算露点和露点温差（不会把三个测点平均）。

    输入：字典，例如
        {"point1": {"temperature": 25.2, "humidity": 65.0, "valid": True},
         "point2": {...}, "point3": {...}}
    输出：新字典，每个测点增加 dew_point、dew_margin 两项；
          valid 为 False 或输入不合理的测点，两项都是 None，valid 置为 False。
    不会修改传入的原字典。
    """
    result = {}
    for point_name in sensor_data:
        point = sensor_data[point_name]
        temperature = point.get("temperature")
        humidity = point.get("humidity")

        dew_point = None
        dew_margin = None
        # 必须同时满足：上游标记有效 + 数值本身合理
        if point.get("valid") is True:
            dew_point = calculate_dew_point(temperature, humidity)
            if dew_point is not None:
                dew_margin = calculate_dew_margin(temperature, dew_point)

        result[point_name] = {
            "temperature": temperature,
            "humidity": humidity,
            "dew_point": dew_point,
            "dew_margin": dew_margin,
            "valid": dew_margin is not None,
        }
    return result
