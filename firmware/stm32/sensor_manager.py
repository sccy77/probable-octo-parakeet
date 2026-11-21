# -*- coding: utf-8 -*-
"""
sensor_manager.py —— 传感器系统管理（把“采集 → 滤波 → 露点计算 → 汇总”串起来）

这个文件本身不做任何底层工作，它只负责“指挥”其他模块，各模块分工如下：

    sensor.py        负责：通过 I2C 读 SHT30，得到每个测点的温度、湿度
    data_filter.py   负责：对每个测点的温度、湿度分别做滑动平均
    dew_point.py     负责：计算每个测点的露点温度和露点温差
    sensor_manager   负责：按顺序调用上面三个模块，再算“全箱汇总”，输出统一的数据字典

数据流向（每个采样周期走一遍）：

    read_all_sensors()  ->  update_filter()  ->  calculate_all_dew_points()  ->  汇总
       原始读数              滤波后的数值           露点 / 露点温差              最大温差等

对外只需要用 3 个函数：
    initialize_sensor_system()          开机时调用一次
    get_environment_data()              每次调用就“现在采集一次并返回结果”
    get_environment_data_if_due()       不阻塞版本：没到采样时间就返回 None（给主循环用）

写法兼容：电脑上的标准 Python 3 和 MicroPython。
状态：算法和数据流已在电脑上用模拟总线测试；真实硬件上的运行【待上板验证】。
"""

import time
import config
import sensor
import data_filter
import dew_point

# ---------------------------------------------------------------
# 模块内部状态（只在本文件内使用，外部不要直接改）
# ---------------------------------------------------------------
# 滤波器的状态（由 data_filter.create_filter_state 创建）。None 表示还没初始化。
_filter_state = None

# 输出数据的序号，每输出一次加 1。云端可以用它发现“丢包”或“重复数据”。
# 不用时间戳是因为不确定设备上的时间是否已经同步。
_seq = 0

# 上一次采样的时间（毫秒），用于判断“到没到采样时间”。None 表示从没采样过。
_last_sample_ms = None

# 输出数值保留的小数位数。SHT30 的分辨率约 0.01，多了没有意义。
_DECIMALS = 2


# ---------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------
def _round(value):
    """四舍五入到 2 位小数；None 原样返回（None 表示“没有有效数据”）。"""
    if value is None:
        return None
    return round(value, _DECIMALS)


def _now_ms():
    """
    取当前时间（毫秒）。
    MicroPython 用 time.ticks_ms()；标准 Python 没有它，改用 time.monotonic()。
    测试时可以直接替换这个函数，来“假装时间在流逝”。
    """
    ticks = getattr(time, "ticks_ms", None)
    if ticks is not None:
        return ticks()
    return int(time.monotonic() * 1000)


def _elapsed_ms(now, before):
    """
    计算 now 比 before 晚了多少毫秒。
    MicroPython 的 ticks_ms 会“绕圈”（到最大值后回 0），必须用 time.ticks_diff 计算，
    直接相减在绕圈时会得到错误的结果。
    """
    diff = getattr(time, "ticks_diff", None)
    if diff is not None:
        return diff(now, before)
    return now - before


def _empty_point(status):
    """
    生成一个“没有有效数据”的测点结果。
    所有数值都是 None，valid 为 False，status 说明原因。
    """
    return {
        "temperature": None,
        "humidity": None,
        "dew_point": None,
        "dew_margin": None,
        "valid": False,
        "status": status,
        "samples": 0,
    }


def _summarize(points):
    """
    根据各测点的结果，计算“全箱汇总”信息。

    参数 points：{测点名: 测点结果字典}，其中“数值”用的是未取整的原始浮点数。
    返回字典，包含：
      max_temp_diff   有效测点之间的最大温差（至少 2 个有效测点才有意义，否则 None）
      min_dew_margin  所有有效测点中最小的露点温差（没有有效测点则 None）
      risk_point      露点温差最小的测点编号（从 1 开始，和 point1/point2/point3 对应）
      valid_count     有效测点数量
      faulty_points   无效测点的名称列表
      data_valid      是否“所有测点都有效”
      system_status   "ok" / "partial" / "all_failed"
    """
    names = config.POINT_NAMES

    # 只挑“有效”的测点参与计算。
    # 无效测点（故障、没配置、校验失败……）的数据一律不参与，也不会用它的旧数据。
    valid_names = [n for n in names if points[n]["valid"]]
    faulty_names = [n for n in names if not points[n]["valid"]]

    # 1) 最大温差 = 最高温度 - 最低温度。只有 1 个测点时谈不上“差”，所以要求至少 2 个。
    max_temp_diff = None
    if len(valid_names) >= 2:
        temps = [points[n]["temperature"] for n in valid_names]
        max_temp_diff = max(temps) - min(temps)

    # 2) 最小露点温差，以及它属于哪个测点。露点温差越小，越接近凝露，所以重点盯它。
    min_dew_margin = None
    risk_point = None
    for n in valid_names:
        margin = points[n]["dew_margin"]
        if min_dew_margin is None or margin < min_dew_margin:
            min_dew_margin = margin
            risk_point = names.index(n) + 1  # 转成从 1 开始的编号，和输出格式约定一致

    # 3) 系统整体状态
    valid_count = len(valid_names)
    if valid_count == 0:
        system_status = "all_failed"      # 所有测点都没有有效数据：明确的系统错误状态
    elif valid_count < len(names):
        system_status = "partial"         # 数据不完整：只有一部分测点有效
    else:
        system_status = "ok"

    return {
        "max_temp_diff": max_temp_diff,
        "min_dew_margin": min_dew_margin,
        "risk_point": risk_point,
        "valid_count": valid_count,
        "faulty_points": faulty_names,
        "data_valid": valid_count == len(names),
        "system_status": system_status,
    }


def _build_output(points, summary):
    """
    把各测点结果和汇总信息合成最终输出字典，并统一取整。
    输出格式在你的文档示例的基础上，增加了几个字段（见下方“新增字段”），
    需要和 B、C 同学确认后再正式定稿。
    """
    global _seq
    _seq += 1

    output = {}
    for name in config.POINT_NAMES:
        p = points[name]
        output[name] = {
            "temperature": _round(p["temperature"]),
            "humidity": _round(p["humidity"]),
            "dew_point": _round(p["dew_point"]),
            "dew_margin": _round(p["dew_margin"]),
            "valid": p["valid"],
            "status": p["status"],      # 新增字段：失败原因，方便排查
            "samples": p["samples"],    # 新增字段：滤波窗口里目前有几个有效样本
        }

    output["max_temp_diff"] = _round(summary["max_temp_diff"])
    output["min_dew_margin"] = _round(summary["min_dew_margin"])
    output["risk_point"] = summary["risk_point"]
    output["data_valid"] = summary["data_valid"]
    output["system_status"] = summary["system_status"]    # 新增字段
    output["valid_count"] = summary["valid_count"]        # 新增字段
    output["faulty_points"] = summary["faulty_points"]    # 新增字段
    output["seq"] = _seq                                  # 新增字段
    return output


# ---------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------
def initialize_sensor_system(i2c=None):
    """
    初始化整个传感器系统，开机时调用一次。
      1) 初始化 I2C 并检查传感器是否在线（sensor.init_sensors）
      2) 创建滤波器（每个测点独立的滑动窗口）
      3) 清零序号和采样计时

    参数 i2c：可传入已有的 I2C 对象（电脑测试时传模拟对象）；板子上不用传。
    返回：各测点的在线检查结果，例如 {"point1": "ok", "point2": "not_found", ...}。
    注意：某个传感器没找到并不会让初始化失败，系统会继续运行，
          该测点之后会被标记为无效；这样一个传感器坏了不会拖垮整个系统。
    """
    global _filter_state, _seq, _last_sample_ms

    report = sensor.init_sensors(i2c)
    _filter_state = data_filter.create_filter_state(config.POINT_NAMES,
                                                    config.FILTER_WINDOW_SIZE)
    _seq = 0
    _last_sample_ms = None
    return report


def collect_sensor_data():
    """
    只做“采集”：读一遍所有测点的原始数据，不滤波、不计算。
    返回 {测点名: 读取结果字典}，格式见 sensor.read_sensor。
    """
    return sensor.read_all_sensors()


def process_sensor_data(raw):
    """
    对原始数据做“滤波 → 露点计算 → 汇总”，返回统一的数据字典。

    参数 raw：collect_sensor_data() 的返回值。

    关键点（对应“不让旧数据冒充新数据”的要求）：
      - 读取失败的测点，data_filter 会清空它的窗口，输出 None，
        不会把失败前的旧数值再拿出来用。
      - 无效测点不参与最大温差和最小露点温差的计算。
    """
    # 如果还没调用 initialize_sensor_system()，没有滤波器可用，
    # 就明确告诉调用方“系统未初始化”，而不是悄悄返回空数据或报一个看不懂的错误。
    if _filter_state is None:
        points = {n: _empty_point("not_initialized") for n in config.POINT_NAMES}
        summary = _summarize(points)
        summary["system_status"] = "not_initialized"   # 比 all_failed 更准确地说明原因
        return _build_output(points, summary)

    # ---- 第 1 步：对每个测点滤波 ----
    # dew_point 模块需要的输入格式：{测点名: {"temperature", "humidity", "valid"}}
    filtered_input = {}
    samples = {}
    raw_status = {}
    for name in config.POINT_NAMES:
        reading = raw.get(name)
        if reading is None:
            # 理论上不会发生（read_all_sensors 会给每个测点一个结果），这里只是防御
            reading = {"temperature": None, "humidity": None, "valid": False, "status": "missing"}

        result = data_filter.update_filter(_filter_state, name,
                                           reading["temperature"],
                                           reading["humidity"],
                                           reading["valid"])
        filtered_input[name] = {
            "temperature": result["temperature"],
            "humidity": result["humidity"],
            "valid": result["valid"],
        }
        samples[name] = result["samples"]
        raw_status[name] = reading["status"]

    # ---- 第 2 步：对每个测点分别计算露点和露点温差（绝不把三个点平均）----
    dew_results = dew_point.calculate_all_dew_points(filtered_input)

    # ---- 第 3 步：整理每个测点的结果 ----
    points = {}
    for name in config.POINT_NAMES:
        d = dew_results[name]
        status = raw_status[name]
        # 传感器读数没问题，但露点算不出来（例如湿度恰好是 0）：单独标出这种原因
        if status == "ok" and not d["valid"]:
            status = "dew_invalid"
        points[name] = {
            "temperature": d["temperature"] if d["valid"] else None,
            "humidity": d["humidity"] if d["valid"] else None,
            "dew_point": d["dew_point"],
            "dew_margin": d["dew_margin"],
            "valid": d["valid"],
            "status": status,
            "samples": samples[name],
        }

    # ---- 第 4 步：汇总（最大温差、最小露点温差、风险测点、整体状态）----
    return _build_output(points, _summarize(points))


def get_environment_data():
    """
    现在就采集一次，并返回完整的环境数据字典。
    这是给其他模块（控制、通信）用的主要接口。

    返回字典示例（数值仅为说明格式，不是实测结果）：
      {
        "point1": {"temperature": 25.2, "humidity": 65.0, "dew_point": 18.15,
                   "dew_margin": 7.05, "valid": True, "status": "ok", "samples": 3},
        "point2": {...}, "point3": {...},
        "max_temp_diff": 1.3, "min_dew_margin": 5.36, "risk_point": 3,
        "data_valid": True,
        "system_status": "ok",   # "ok" / "partial" / "all_failed" / "not_initialized"
        "valid_count": 3, "faulty_points": [], "seq": 42
      }

    使用规则（给 B、C 同学）：
      - 先看 system_status 和每个测点的 valid；valid 为 False 的测点，数值都是 None，不要使用。
      - data_valid 为 False 表示数据不完整（至少一个测点无效），风险判断要谨慎。
    """
    global _last_sample_ms
    _last_sample_ms = _now_ms()
    return process_sensor_data(collect_sensor_data())


def get_environment_data_if_due():
    """
    “不阻塞”版本：到了采样时间才采集，没到就立刻返回 None。
    适合放进主循环，主循环可以同时做别的事（比如处理网络消息、控制风扇），
    不需要为了定时而 sleep 卡住整个程序。

    采样间隔由 config.SAMPLE_PERIOD_S 决定。第一次调用一定会采样。
    """
    now = _now_ms()
    if _last_sample_ms is not None:
        if _elapsed_ms(now, _last_sample_ms) < config.SAMPLE_PERIOD_S * 1000:
            return None   # 还没到时间
    return get_environment_data()
