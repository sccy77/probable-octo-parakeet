# -*- coding: utf-8 -*-
"""
tests/fake_i2c.py —— 测试专用的“模拟 I2C 总线”和“模拟数据帧”

重要：这里所有数据都是人为构造的，不是真实传感器测量结果。
它的作用只是让我们在没有硬件的电脑上，验证软件逻辑是否正确。
"""
import os
import sys

# 让测试能找到 firmware/stm32 下的模块
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "stm32"))
import config
import sensor


def make_frame(temperature, humidity):
    """
    按 SHT30 的 6 字节帧格式，反向构造一帧数据（含 CRC）。
    格式：[温度高, 温度低, CRC, 湿度高, 湿度低, CRC]
    """
    raw_t = int(round((temperature + 45.0) * 65535.0 / 175.0))
    raw_h = int(round(humidity * 65535.0 / 100.0))
    t = bytes([raw_t >> 8, raw_t & 0xFF])
    h = bytes([raw_h >> 8, raw_h & 0xFF])
    return t + bytes([sensor.crc8(t)]) + h + bytes([sensor.crc8(h)])


class FakeI2C(object):
    """
    模拟 I2C 总线，提供和真实 machine.I2C 相同名字的方法。
      frames[地址] = bytes      该地址读取时返回的数据帧
      frames[地址] = Exception  该地址一通信就抛出这个异常（模拟传感器无应答）
      present                   scan() 返回的地址列表
      writes                    记录所有写入过的 (地址, 数据)，用来检查发出的命令
    """

    def __init__(self):
        self.frames = {}
        self.writes = []
        self.present = []

    def scan(self):
        return list(self.present)

    def writeto(self, addr, data):
        self.writes.append((addr, bytes(data)))
        item = self.frames.get(addr)
        # 只有发“测量命令”时才模拟故障，这样不影响多路复用器的通道切换写入
        if isinstance(item, Exception) and bytes(data) == bytes(config.SHT30_MEASURE_CMD):
            raise item
        return len(data)

    def readfrom(self, addr, n):
        item = self.frames.get(addr)
        if isinstance(item, Exception):
            raise item
        if item is None:
            raise OSError(19)  # 没有这个地址的数据：当作无应答
        return item


def setup_three_points(frames):
    """
    把 config 设成“三个测点都配置好”的测试配置，并初始化 sensor 模块。
    返回 FakeI2C 对象，测试可以继续修改 bus.frames 来模拟故障。
    """
    config.SENSORS = [
        {"name": "point1", "addr": 0x44, "mux_channel": None},
        {"name": "point2", "addr": 0x45, "mux_channel": None},
        {"name": "point3", "addr": 0x46, "mux_channel": None},  # 测试用的假地址
    ]
    config.POINT_NAMES = [s["name"] for s in config.SENSORS]
    config.SENSOR_COUNT = len(config.SENSORS)
    config.USE_MUX = False
    config.SHT30_MEASURE_WAIT_MS = 0   # 测试里不需要真的等待
    config.FILTER_WINDOW_SIZE = 3
    config.SAMPLE_PERIOD_S = 5
    bus = FakeI2C()
    bus.frames = frames
    bus.present = [0x44, 0x45, 0x46]
    return bus
