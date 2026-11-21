# -*- coding: utf-8 -*-
"""
PC 上运行：python tests/test_sensor.py

重要说明：
  本文件用“模拟 I2C 总线（FakeI2C）”测试 sensor.py 的逻辑。
  里面所有温湿度数据都是人为构造的，不是真实传感器测量结果。
  它只能证明“CRC、解析、状态判断、不返回旧数据”这些逻辑正确，
  不能证明真实 SHT30 能读通——那一项仍然是【待上板验证】。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "stm32"))
import config
import sensor


# ---------- 构造模拟数据的辅助工具（仅测试用）----------
def make_frame(temperature, humidity):
    """按 SHT30 的帧格式，反向构造一帧（含 CRC）。"""
    raw_t = int(round((temperature + 45.0) * 65535.0 / 175.0))
    raw_h = int(round(humidity * 65535.0 / 100.0))
    t = bytes([raw_t >> 8, raw_t & 0xFF])
    h = bytes([raw_h >> 8, raw_h & 0xFF])
    return t + bytes([sensor.crc8(t)]) + h + bytes([sensor.crc8(h)])


class FakeI2C(object):
    """模拟 I2C 总线：记录写入的内容；按地址返回预先设好的帧。"""

    def __init__(self):
        self.frames = {}        # 地址 -> 返回的 bytes，或 Exception 对象
        self.writes = []        # [(地址, 数据), ...]
        self.present = []       # scan() 返回的地址列表

    def scan(self):
        return list(self.present)

    def writeto(self, addr, data):
        self.writes.append((addr, bytes(data)))
        item = self.frames.get(addr)
        if isinstance(item, Exception) and bytes(data) == bytes(config.SHT30_MEASURE_CMD):
            raise item
        return len(data)

    def readfrom(self, addr, n):
        item = self.frames.get(addr)
        if isinstance(item, Exception):
            raise item
        if item is None:
            raise OSError(19)
        return item


def fresh(frames=None, third=0x45):
    """重置 config 为测试配置，并返回已初始化的 FakeI2C。"""
    config.SENSORS = [
        {"name": "point1", "addr": 0x44, "mux_channel": None},
        {"name": "point2", "addr": 0x45, "mux_channel": None},
        {"name": "point3", "addr": None, "mux_channel": None},
    ]
    config.POINT_NAMES = [s["name"] for s in config.SENSORS]
    config.USE_MUX = False
    config.SHT30_MEASURE_WAIT_MS = 0
    bus = FakeI2C()
    bus.frames = frames or {}
    bus.present = [0x44, 0x45]
    sensor.init_sensors(bus)
    return bus


# ---------- 纯函数测试 ----------
def test_crc_datasheet_vector():
    assert sensor.crc8(bytes([0xBE, 0xEF])) == 0x92  # 数据手册给出的测试向量


def test_conversion_endpoints():
    assert abs(sensor.raw_to_temperature(0) - (-45.0)) < 1e-9
    assert abs(sensor.raw_to_temperature(0xFFFF) - 130.0) < 1e-9
    assert sensor.raw_to_humidity(0) == 0.0
    assert abs(sensor.raw_to_humidity(0xFFFF) - 100.0) < 1e-9


def test_decode_roundtrip():
    status, t, h = sensor.decode_frame(make_frame(25.2, 65.0))
    assert status == "ok"
    assert abs(t - 25.2) < 0.01 and abs(h - 65.0) < 0.01  # 分辨率内


def test_decode_bad_crc():
    frame = bytearray(make_frame(25.0, 60.0))
    frame[2] ^= 0xFF
    assert sensor.decode_frame(bytes(frame)) == ("crc_error", None, None)
    frame = bytearray(make_frame(25.0, 60.0))
    frame[5] ^= 0x01
    assert sensor.decode_frame(bytes(frame))[0] == "crc_error"


def test_decode_bad_length():
    assert sensor.decode_frame(b"\x00\x01\x02")[0] == "bad_length"
    assert sensor.decode_frame(None)[0] == "bad_length"


# ---------- 驱动层逻辑测试（用模拟总线）----------
def test_read_ok_and_command_sent():
    bus = fresh({0x44: make_frame(24.0, 50.0)})
    r = sensor.read_sensor("point1")
    assert r["valid"] and r["status"] == "ok"
    assert abs(r["temperature"] - 24.0) < 0.01
    assert (0x44, bytes([0x24, 0x00])) in bus.writes  # 发出了 0x2400 测量命令


def test_i2c_error_gives_none():
    fresh({0x44: OSError(19)})
    r = sensor.read_sensor("point1")
    assert r["status"] == "i2c_error" and not r["valid"]
    assert r["temperature"] is None and r["humidity"] is None


def test_crc_error_gives_none():
    bad = bytearray(make_frame(24.0, 50.0))
    bad[2] ^= 0x55
    fresh({0x44: bytes(bad)})
    r = sensor.read_sensor("point1")
    assert r["status"] == "crc_error" and r["temperature"] is None


def test_unconfigured_point():
    fresh({})
    r = sensor.read_sensor("point3")
    assert r["status"] == "not_configured" and not r["valid"]
    assert sensor.read_sensor("nope")["status"] == "not_configured"


def test_not_initialized():
    sensor._i2c = None
    assert sensor.read_sensor("point1")["status"] == "not_initialized"


def test_no_stale_data():
    # 第一次读成功，第二次读失败：必须返回 None，不能返回上一次的数值
    bus = fresh({0x44: make_frame(24.0, 50.0)})
    assert sensor.read_sensor("point1")["valid"]
    bus.frames[0x44] = OSError(110)
    r = sensor.read_sensor("point1")
    assert not r["valid"] and r["temperature"] is None and r["humidity"] is None


def test_read_all_isolated_failures():
    fresh({0x44: make_frame(24.0, 50.0), 0x45: OSError(19)})
    out = sensor.read_all_sensors()
    assert sorted(out.keys()) == ["point1", "point2", "point3"]
    assert out["point1"]["valid"]
    assert out["point2"]["status"] == "i2c_error"
    assert out["point3"]["status"] == "not_configured"


def test_init_report():
    fresh({})
    bus = FakeI2C()
    bus.present = [0x44]  # 0x45 不在总线上
    report = sensor.init_sensors(bus)
    assert report == {"point1": "ok", "point2": "not_found", "point3": "not_configured"}


def test_mux_channel_select_and_release():
    bus = fresh({0x44: make_frame(22.0, 40.0)})
    config.USE_MUX = True
    config.MUX_ADDR = 0x70
    config.SENSORS[0]["mux_channel"] = 2
    bus.writes = []
    r = sensor.read_sensor("point1")
    assert r["valid"]
    assert bus.writes[0] == (0x70, bytes([0b100]))   # 先选通道 2
    assert bus.writes[-1] == (0x70, bytes([0]))      # 读完关闭所有通道


def test_mux_released_even_on_error():
    bus = fresh({0x44: OSError(19)})
    config.USE_MUX = True
    config.SENSORS[0]["mux_channel"] = 1
    bus.writes = []
    sensor.read_sensor("point1")
    assert bus.writes[-1] == (0x70, bytes([0]))


def test_output_feeds_dew_point():
    # 与 dew_point 模块对接：read_all_sensors 的输出可以直接作为 calculate_all_dew_points 的输入
    import dew_point
    fresh({0x44: make_frame(25.0, 60.0), 0x45: OSError(19)})
    result = dew_point.calculate_all_dew_points(sensor.read_all_sensors())
    assert result["point1"]["valid"] and abs(result["point1"]["dew_point"] - 16.7) < 0.2
    assert not result["point2"]["valid"] and result["point2"]["dew_point"] is None
    assert not result["point3"]["valid"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("通过:", t.__name__)
    print("全部 %d 项测试通过（使用模拟总线，不代表真实传感器已验证）" % len(tests))
