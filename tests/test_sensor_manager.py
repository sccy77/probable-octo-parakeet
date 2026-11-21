# -*- coding: utf-8 -*-
"""
PC 上运行：python tests/test_sensor_manager.py

重要说明：
  使用“模拟 I2C 总线”，所有温湿度数据都是人为构造的，不是真实传感器测量结果。
  这里验证的是：采集 → 滤波 → 露点 → 汇总 这条数据流的逻辑是否正确。
  真实硬件上的运行仍然是【待上板验证】。
"""
import json

from fake_i2c import make_frame, setup_three_points   # 同时会设置好 import 路径
import config
import sensor
import sensor_manager as sm


def start(frames):
    """配置三个测点 + 初始化整个系统，返回模拟总线。"""
    bus = setup_three_points(frames)
    sm.initialize_sensor_system(bus)
    return bus


# 三组人为构造的数据（温度, 湿度）。参考你文档里的示例结构，数值只是演示。
F1 = make_frame(25.2, 65.0)
F2 = make_frame(24.7, 68.0)
F3 = make_frame(23.9, 72.0)


def test_all_valid_output():
    start({0x44: F1, 0x45: F2, 0x46: F3})
    out = sm.get_environment_data()

    # 1) 结构完整
    for name in ("point1", "point2", "point3"):
        assert out[name]["valid"] is True and out[name]["status"] == "ok"
    assert out["data_valid"] is True and out["system_status"] == "ok"
    assert out["valid_count"] == 3 and out["faulty_points"] == []

    # 2) 各测点分别算露点（不是平均）：湿度越高、温度越低的点，露点温差越小
    assert out["point1"]["dew_margin"] > out["point2"]["dew_margin"] > out["point3"]["dew_margin"]
    # 25.2°C/65%RH 的露点约 18.2°C（手算校验，见 dew_point 测试里的同类数值）
    assert abs(out["point1"]["dew_point"] - 18.15) < 0.1

    # 3) 汇总：最大温差 = 25.2 - 23.9 = 1.3；风险点是露点温差最小的 point3（编号 3）
    assert abs(out["max_temp_diff"] - 1.3) < 0.05
    assert out["risk_point"] == 3
    assert abs(out["min_dew_margin"] - out["point3"]["dew_margin"]) < 1e-9


def test_one_sensor_fails():
    bus = start({0x44: F1, 0x45: F2, 0x46: F3})
    bus.frames[0x46] = OSError(19)    # point3 无应答
    out = sm.get_environment_data()

    assert out["point3"]["valid"] is False and out["point3"]["status"] == "i2c_error"
    assert out["point3"]["temperature"] is None and out["point3"]["dew_margin"] is None
    assert out["data_valid"] is False and out["system_status"] == "partial"
    assert out["faulty_points"] == ["point3"] and out["valid_count"] == 2
    # 汇总只用 point1、point2：风险点不能是已故障的 point3
    assert out["risk_point"] == 2
    assert abs(out["max_temp_diff"] - 0.5) < 0.05


def test_only_one_valid_has_no_temp_diff():
    bus = start({0x44: F1, 0x45: OSError(19), 0x46: OSError(19)})
    out = sm.get_environment_data()
    assert out["valid_count"] == 1 and out["system_status"] == "partial"
    assert out["max_temp_diff"] is None          # 只有一个点，算不出温差
    assert out["risk_point"] == 1 and out["min_dew_margin"] is not None


def test_all_fail():
    start({0x44: OSError(19), 0x45: OSError(19), 0x46: OSError(19)})
    out = sm.get_environment_data()
    assert out["system_status"] == "all_failed" and out["data_valid"] is False
    assert out["valid_count"] == 0
    assert out["max_temp_diff"] is None and out["min_dew_margin"] is None
    assert out["risk_point"] is None


def test_crc_error_point_excluded():
    bad = bytearray(F3)
    bad[2] ^= 0xFF                                # 破坏 CRC
    start({0x44: F1, 0x45: F2, 0x46: bytes(bad)})
    out = sm.get_environment_data()
    assert out["point3"]["status"] == "crc_error" and not out["point3"]["valid"]
    assert out["risk_point"] == 2                 # 校验失败的 point3 不参与风险计算


def test_filter_averages_valid_samples():
    bus = start({0x44: make_frame(20.0, 50.0), 0x45: F2, 0x46: F3})
    sm.get_environment_data()
    bus.frames[0x44] = make_frame(22.0, 50.0)
    out = sm.get_environment_data()
    # 窗口里有 20 和 22 两个有效样本，平均 21
    assert abs(out["point1"]["temperature"] - 21.0) < 0.02
    assert out["point1"]["samples"] == 2


def test_no_stale_data_after_failure():
    bus = start({0x44: F1, 0x45: F2, 0x46: F3})
    sm.get_environment_data()
    bus.frames[0x44] = OSError(110)
    out = sm.get_environment_data()
    # 失败后不能继续输出之前滤波的结果
    assert out["point1"]["valid"] is False
    assert out["point1"]["temperature"] is None and out["point1"]["samples"] == 0
    # 传感器恢复后，窗口从头开始，只有 1 个新样本
    bus.frames[0x44] = make_frame(30.0, 40.0)
    out = sm.get_environment_data()
    assert out["point1"]["samples"] == 1 and abs(out["point1"]["temperature"] - 30.0) < 0.02


def test_seq_increases():
    start({0x44: F1, 0x45: F2, 0x46: F3})
    a = sm.get_environment_data()["seq"]
    b = sm.get_environment_data()["seq"]
    assert b == a + 1


def test_not_initialized():
    sm._filter_state = None
    out = sm.process_sensor_data({})
    assert out["system_status"] == "not_initialized" and out["data_valid"] is False
    assert out["point1"]["status"] == "not_initialized" and out["point1"]["temperature"] is None


def test_default_config_has_unconfigured_point():
    # 模拟 config.py 的默认情况：point3 还没配置地址，必须被明确标为“数据不完整”
    bus = setup_three_points({0x44: F1, 0x45: F2})
    config.SENSORS[2]["addr"] = None
    sm.initialize_sensor_system(bus)
    out = sm.get_environment_data()
    assert out["point3"]["status"] == "not_configured"
    assert out["system_status"] == "partial" and out["data_valid"] is False


def test_json_serializable():
    # 要发给云端：必须能转成 JSON，而且不能出现 NaN / Infinity
    bus = start({0x44: F1, 0x45: OSError(19), 0x46: F3})
    text = json.dumps(sm.get_environment_data(), allow_nan=False)
    assert "null" in text      # 无效测点的数值是 null
    json.loads(text)


def test_due_scheduling():
    start({0x44: F1, 0x45: F2, 0x46: F3})
    clock = {"t": 1000}
    original_now = sm._now_ms
    sm._now_ms = lambda: clock["t"]               # 假装时间（测试专用）
    try:
        assert sm.get_environment_data_if_due() is not None   # 第一次一定采样
        clock["t"] += 1000
        assert sm.get_environment_data_if_due() is None       # 才过 1 秒，没到 5 秒
        clock["t"] += 3999
        assert sm.get_environment_data_if_due() is None       # 4.999 秒，还没到
        clock["t"] += 1
        assert sm.get_environment_data_if_due() is not None   # 刚好 5 秒
    finally:
        sm._now_ms = original_now                 # 还原，避免影响其他测试


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("通过:", t.__name__)
    print("全部 %d 项测试通过（使用模拟总线，不代表真实传感器已验证）" % len(tests))
