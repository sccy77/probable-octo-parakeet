# -*- coding: utf-8 -*-
"""PC 上运行的露点算法测试：python tests/test_dew_point.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "stm32"))
import dew_point as dp


def near(a, b, tol):
    return abs(a - b) <= tol


def test_known_value():
    # 25°C / 60%RH，常见露点参考值约 16.7°C（Magnus 公式结果）
    td = dp.calculate_dew_point(25.0, 60.0)
    assert near(td, 16.7, 0.1), td


def test_saturated_air():
    # 相对湿度 100% 时，露点应等于空气温度
    for t in (-10.0, 0.0, 20.0, 40.0):
        assert near(dp.calculate_dew_point(t, 100.0), t, 1e-9)


def test_margin():
    assert near(dp.calculate_dew_margin(25.0, 16.7), 8.3, 1e-9)


def test_monotonic_in_humidity():
    # 温度不变，湿度越高，露点越高
    a = dp.calculate_dew_point(25.0, 40.0)
    b = dp.calculate_dew_point(25.0, 70.0)
    assert a < b


def test_invalid_inputs():
    bad = [(None, 50.0), (25.0, None), (25.0, 0.0), (25.0, -5.0), (25.0, 100.5),
           (200.0, 50.0), (-50.0, 50.0), (float("nan"), 50.0), (25.0, float("inf")),
           ("25", 50.0), (True, 50.0)]
    for t, rh in bad:
        assert dp.calculate_dew_point(t, rh) is None, (t, rh)


def test_margin_invalid():
    assert dp.calculate_dew_margin(None, 10.0) is None
    assert dp.calculate_dew_margin(25.0, None) is None


def test_all_points_independent():
    data = {
        "point1": {"temperature": 25.0, "humidity": 60.0, "valid": True},
        "point2": {"temperature": 20.0, "humidity": 90.0, "valid": True},
        "point3": {"temperature": 22.0, "humidity": 55.0, "valid": False},  # 故障点
    }
    snapshot = {k: dict(v) for k, v in data.items()}
    out = dp.calculate_all_dew_points(data)

    assert data == snapshot  # 不修改输入
    assert out["point1"]["valid"] and out["point2"]["valid"]
    assert out["point1"]["dew_point"] != out["point2"]["dew_point"]  # 各算各的
    assert out["point2"]["dew_margin"] < out["point1"]["dew_margin"]  # 湿度高的点更危险
    # 故障点：没有露点，也不能被当作有效数据
    assert out["point3"]["dew_point"] is None
    assert out["point3"]["dew_margin"] is None
    assert out["point3"]["valid"] is False


def test_valid_flag_but_bad_numbers():
    data = {"point1": {"temperature": 25.0, "humidity": 0.0, "valid": True}}
    out = dp.calculate_all_dew_points(data)
    assert out["point1"]["valid"] is False and out["point1"]["dew_point"] is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("通过:", t.__name__)
    print("全部 %d 项测试通过" % len(tests))
