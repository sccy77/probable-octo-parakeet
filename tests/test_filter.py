# -*- coding: utf-8 -*-
"""PC 上运行的滤波测试：python tests/test_filter.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "stm32"))
import data_filter as df

NAMES = ["point1", "point2", "point3"]


def near(a, b, tol=1e-9):
    return abs(a - b) <= tol


def test_average_and_window():
    s = df.create_filter_state(NAMES, 3)
    r = None
    for t in (10.0, 20.0, 30.0):
        r = df.update_filter(s, "point1", t, 50.0, True)
    assert near(r["temperature"], 20.0) and r["samples"] == 3
    r = df.update_filter(s, "point1", 40.0, 50.0, True)  # 最老的 10 被挤出
    assert near(r["temperature"], 30.0) and r["samples"] == 3


def test_temp_and_hum_independent():
    s = df.create_filter_state(NAMES, 2)
    df.update_filter(s, "point1", 10.0, 40.0, True)
    r = df.update_filter(s, "point1", 20.0, 60.0, True)
    assert near(r["temperature"], 15.0) and near(r["humidity"], 50.0)


def test_points_independent():
    s = df.create_filter_state(NAMES, 3)
    df.update_filter(s, "point1", 10.0, 40.0, True)
    r2 = df.update_filter(s, "point2", 30.0, 70.0, True)
    assert near(r2["temperature"], 30.0) and r2["samples"] == 1


def test_invalid_not_added_and_clears():
    s = df.create_filter_state(NAMES, 3)
    df.update_filter(s, "point1", 10.0, 40.0, True)
    bad = df.update_filter(s, "point1", None, None, False)
    assert bad["valid"] is False and bad["temperature"] is None and bad["samples"] == 0
    assert df.filter_temperature(s, "point1") is None  # 旧数据已清除
    r = df.update_filter(s, "point1", 30.0, 60.0, True)  # 恢复后只用新数据
    assert near(r["temperature"], 30.0) and r["samples"] == 1


def test_valid_flag_but_nan_value():
    s = df.create_filter_state(NAMES, 3)
    r = df.update_filter(s, "point1", float("nan"), 50.0, True)
    assert r["valid"] is False


def test_other_point_unaffected_by_failure():
    s = df.create_filter_state(NAMES, 3)
    df.update_filter(s, "point2", 22.0, 55.0, True)
    df.update_filter(s, "point1", None, None, False)
    assert near(df.filter_temperature(s, "point2"), 22.0)


def test_bad_window_size():
    for w in (0, -1, 2.5, None):
        try:
            df.create_filter_state(NAMES, w)
        except ValueError:
            continue
        raise AssertionError("window_size=%r 应该报错" % (w,))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("通过:", t.__name__)
    print("全部 %d 项测试通过" % len(tests))
