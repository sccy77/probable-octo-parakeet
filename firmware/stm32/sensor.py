# -*- coding: utf-8 -*-
"""
sensor.py —— SHT30 温湿度传感器读取

分两层，方便在电脑上测试：
  1) 纯函数层（不碰硬件）：crc8、换算、帧解析 —— 可在电脑上完整测试
  2) 驱动层（通过 I2C 对象读传感器）：init_sensors / read_sensor / read_all_sensors
     驱动层不自己创建 I2C 也能工作（可传入 i2c 对象），所以电脑上能用“模拟总线”测试逻辑。

重要原则：读取失败时只返回 None 和明确的状态，绝不返回旧数据。
本文件不保存任何上一次的测量结果。

状态 status 取值：
  ok               读取成功，数据有效
  not_initialized  还没有调用 init_sensors()
  not_configured   该测点在 config.py 中没有配置地址
  i2c_error        I2C 通信失败（无应答、超时等）
  bad_length       读到的字节数不是 6
  crc_error        校验和不对，数据不可信
"""

import time
import config

# 当前使用的 I2C 对象；由 init_sensors() 设置
_i2c = None


# ---------------------------------------------------------------
# 纯函数层（不依赖硬件）
# ---------------------------------------------------------------
def crc8(data):
    """
    Sensirion 使用的 CRC-8：多项式 0x31，初值 0xFF。
    数据手册给出的测试向量：crc8(bytes([0xBE, 0xEF])) == 0x92
    """
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def raw_to_temperature(raw):
    """16 位原始值 -> 摄氏度。公式：T = -45 + 175 * raw / 65535"""
    return -45.0 + 175.0 * raw / 65535.0


def raw_to_humidity(raw):
    """16 位原始值 -> 相对湿度 %。公式：RH = 100 * raw / 65535"""
    return 100.0 * raw / 65535.0


def decode_frame(frame):
    """
    解析传感器返回的 6 个字节：[温度高, 温度低, CRC, 湿度高, 湿度低, CRC]
    返回 (status, 温度, 湿度)；status 不是 "ok" 时温度和湿度都是 None。
    """
    if frame is None or len(frame) != 6:
        return ("bad_length", None, None)

    if crc8(frame[0:2]) != frame[2] or crc8(frame[3:5]) != frame[5]:
        return ("crc_error", None, None)

    raw_t = (frame[0] << 8) | frame[1]
    raw_h = (frame[3] << 8) | frame[4]
    return ("ok", raw_to_temperature(raw_t), raw_to_humidity(raw_h))


# ---------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------
def _sleep_ms(ms):
    """MicroPython 有 time.sleep_ms，标准 Python 没有，这里统一处理。"""
    fn = getattr(time, "sleep_ms", None)
    if fn is not None:
        fn(ms)
    else:
        time.sleep(ms / 1000.0)


def _find_config(sensor_id):
    """按测点名称找到 config.SENSORS 里对应的那一项，找不到返回 None。"""
    for item in config.SENSORS:
        if item["name"] == sensor_id:
            return item
    return None


def _result(sensor_id, status, temperature=None, humidity=None, error=None):
    """统一的返回格式。"""
    return {
        "id": sensor_id,
        "temperature": temperature,
        "humidity": humidity,
        "valid": status == "ok",
        "status": status,
        "error": error,
    }


def _mux_select(channel):
    """
    切换 TCA9548A 通道。channel 为 None 表示关闭所有通道。
    config.USE_MUX 为 False 时什么都不做。
    """
    if not config.USE_MUX:
        return
    mask = 0 if channel is None else (1 << channel)
    _i2c.writeto(config.MUX_ADDR, bytes([mask]))


# ---------------------------------------------------------------
# 驱动层
# ---------------------------------------------------------------
def init_sensors(i2c=None):
    """
    初始化 I2C，并检查每个测点的传感器是否在总线上。
    i2c: 可传入已有的 I2C 对象（电脑测试时传模拟对象）；
         不传则在板子上用 machine.I2C(config.I2C_BUS_ID, ...) 创建。
    返回 {测点名: "ok" / "not_found" / "not_configured" / "i2c_error"}。
    某个测点没找到不会阻止后续读取（可能是接触不良，之后还会重试）。
    """
    global _i2c
    if i2c is None:
        try:
            import machine
        except ImportError:
            raise RuntimeError("当前环境没有 machine 模块；在电脑上请传入模拟的 i2c 对象")
        i2c = machine.I2C(config.I2C_BUS_ID, freq=config.I2C_FREQ_HZ,
                          timeout=config.I2C_TIMEOUT_US)
    _i2c = i2c

    report = {}
    for item in config.SENSORS:
        name = item["name"]
        if item["addr"] is None:
            report[name] = "not_configured"
            continue
        try:
            _mux_select(item["mux_channel"])
            found = item["addr"] in _i2c.scan()
            report[name] = "ok" if found else "not_found"
        except Exception as e:
            report[name] = "i2c_error"
        finally:
            try:
                _mux_select(None)
            except Exception:
                pass
    return report


def read_sensor(sensor_id):
    """
    读取一个测点。返回字典：
      {"id", "temperature", "humidity", "valid", "status", "error"}
    失败时 temperature/humidity 为 None，valid 为 False。
    """
    if _i2c is None:
        return _result(sensor_id, "not_initialized")

    item = _find_config(sensor_id)
    if item is None or item["addr"] is None:
        return _result(sensor_id, "not_configured")

    addr = item["addr"]
    try:
        _mux_select(item["mux_channel"])
        _i2c.writeto(addr, bytes(config.SHT30_MEASURE_CMD))
        _sleep_ms(config.SHT30_MEASURE_WAIT_MS)
        frame = _i2c.readfrom(addr, 6)
    except Exception as e:
        # 待验证：真实板子上 NACK/超时抛什么异常类型，上板后再收窄
        return _result(sensor_id, "i2c_error", error=repr(e))
    finally:
        try:
            _mux_select(None)  # 读完关闭通道，避免相同地址的传感器互相冲突
        except Exception:
            pass

    status, temperature, humidity = decode_frame(frame)
    return _result(sensor_id, status, temperature, humidity)


def read_all_sensors():
    """
    依次读取所有测点。返回 {测点名: 读取结果字典}。
    一个测点失败不影响其他测点。
    """
    results = {}
    for name in config.POINT_NAMES:
        results[name] = read_sensor(name)
    return results
