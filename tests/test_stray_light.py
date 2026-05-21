"""杂散光算法单元测试。

针对 core/stray_light.py 的 5 项 AND 判定核心函数。所有数据用合成
np.array 生成，不依赖真实图像，便于在 CI / 离线环境跑。
"""

from __future__ import annotations

import numpy as np
import pytest

from heidstar_flat.core.stray_light import (
    StrayLightThresholds,
    _sensor_max,
    compute_stray_metrics,
    evaluate_stray,
)


# ---------------- _sensor_max ----------------

def test_sensor_max_uint8():
    assert _sensor_max(np.dtype("uint8")) == 255.0


def test_sensor_max_uint16():
    assert _sensor_max(np.dtype("uint16")) == 65535.0


def test_sensor_max_uint32():
    assert _sensor_max(np.dtype("uint32")) == float(2 ** 32 - 1)


def test_sensor_max_float():
    assert _sensor_max(np.dtype("float32")) == 1.0
    assert _sensor_max(np.dtype("float64")) == 1.0


def test_sensor_max_other_integer_via_iinfo():
    # int16 走 np.iinfo 通路
    assert _sensor_max(np.dtype("int16")) == float(np.iinfo("int16").max)


# ---------------- compute_stray_metrics ----------------

def _uniform_stack(value: int, n: int = 5, h: int = 100, w: int = 100,
                   dtype=np.uint8) -> np.ndarray:
    return np.full((n, h, w), value, dtype=dtype)


def test_compute_perfect_uniform_dark():
    """全场恒定暗本底：DC1 反映 value/255，DC2≈100%、DC3≈0%、DC5=0。"""
    stack = _uniform_stack(value=10, n=5, h=99, w=99, dtype=np.uint8)
    m = compute_stray_metrics(stack)

    assert m.n_tiles == 5
    assert m.sensor_max == 255.0
    assert m.dark_mean == pytest.approx(10.0)
    # DC1: 10/255 ≈ 3.92%
    assert m.dc_pct_of_max == pytest.approx(10.0 / 255.0 * 100.0)
    # DC2: 完全均匀 → ≈ 100% (std == 0)
    assert m.zone_dc_uniformity_pct == pytest.approx(100.0)
    # DC3: DSNU = std(mean_img) = 0
    assert m.dsnu_value == pytest.approx(0.0)
    assert m.dsnu_pct_of_max == pytest.approx(0.0)
    # DC4: 无时间波动
    assert m.temporal_noise == pytest.approx(0.0)
    assert m.temporal_noise_pct == pytest.approx(0.0)
    # DC5: 没有像素能超过 μ + 10×0
    assert m.hot_pixel_count == 0
    assert m.hot_pixel_pct == pytest.approx(0.0)
    # 9 区均值都是 10
    assert all(z == pytest.approx(10.0) for z in m.zone_dc)


def test_compute_local_bright_spot_breaks_dc2():
    """左上角一片明显亮：DC2 应被显著拉低。"""
    stack = _uniform_stack(value=5, n=5, h=99, w=99)
    # 左上区块改成大幅亮
    stack[:, :30, :30] = 200
    m = compute_stray_metrics(stack)

    # DC2 远低于 100%（左上块均值高，与其他块差异大）
    assert m.zone_dc_uniformity_pct < 50.0
    # 最亮像素位置应该在左上区
    r, c = m.max_pixel_position
    assert r < 33 and c < 33


def test_compute_pixel_pattern_breaks_dc3():
    """每个像素有 ±20 的固定偏差但跨帧一致：DC3 (DSNU) 应明显非零，
    DC4 (时间噪声) 接近 0。"""
    rng = np.random.default_rng(42)
    base = 50
    h = w = 60
    pixel_offset = rng.integers(-20, 21, size=(h, w))  # 每像素固定偏差
    base_img = (base + pixel_offset).clip(0, 255).astype(np.uint8)
    stack = np.stack([base_img] * 5, axis=0)  # 跨帧完全相同 → 时间噪声 0

    m = compute_stray_metrics(stack)

    # DC3 应反映这个 ±20 范围的 std（理论 ~12, 限于 uint8 截断稍微小一点）
    assert m.dsnu_value > 8.0
    assert m.dsnu_pct_of_max > 3.0
    # DC4 接近 0（每帧完全一致）
    assert m.temporal_noise == pytest.approx(0.0)


def test_compute_temporal_noise_breaks_dc4():
    """每像素跨帧波动大但空间均匀：DC4 应明显非零，DC3 接近 0。"""
    rng = np.random.default_rng(123)
    h = w = 60
    n = 20
    # 全场固定 100，外加每帧每像素独立的 ±15 噪声
    noise = rng.integers(-15, 16, size=(n, h, w))
    stack = (100 + noise).clip(0, 255).astype(np.uint8)

    m = compute_stray_metrics(stack)

    # DC4：每像素跨 20 帧的 std 中位数应该接近 9（均匀分布 [-15,15] std ≈ 9）
    assert 6.0 < m.temporal_noise < 12.0
    # DC3：先取时间平均后空间 std 应较小（噪声被平均掉）
    # 理论上 std/sqrt(20) ≈ 2
    assert m.dsnu_value < 4.0


def test_compute_hot_pixel_breaks_dc5():
    """少数像素明显高出本底：DC5 应抓到。"""
    stack = _uniform_stack(value=10, n=10, h=100, w=100)
    # 在一个像素位置插入 200 的"热点"，跨所有帧
    stack[:, 50, 50] = 200
    stack[:, 25, 75] = 250
    m = compute_stray_metrics(stack)

    # 至少 2 个热像素被识别
    assert m.hot_pixel_count >= 2
    # 占比 = 2 / 10000 × 100% = 0.02%
    assert m.hot_pixel_pct >= 0.02 - 1e-6


def test_compute_n_equals_1_dc4_falls_back_to_zero():
    """N=1 时无法算时间噪声，应退化为 0 而不是抛错。"""
    stack = _uniform_stack(value=10, n=1, h=20, w=20)
    m = compute_stray_metrics(stack)
    assert m.temporal_noise == 0.0
    assert m.temporal_noise_pct == 0.0


def test_compute_rejects_invalid_shape():
    with pytest.raises(ValueError, match="非空"):
        compute_stray_metrics(np.zeros((0, 10, 10), dtype=np.uint8))
    with pytest.raises(ValueError, match="非空"):
        compute_stray_metrics(np.zeros((10, 10), dtype=np.uint8))


def test_compute_rejects_too_small_image():
    with pytest.raises(ValueError, match="尺寸过小"):
        compute_stray_metrics(np.zeros((5, 2, 2), dtype=np.uint8))


# ---------------- evaluate_stray ----------------

def _passing_thresholds() -> StrayLightThresholds:
    """非常宽松的阈值，所有 5 项都应通过。"""
    return StrayLightThresholds(
        dc_pct_of_max=100.0,
        zone_dc_uniformity_pct=0.0,
        dsnu_pct_of_max=100.0,
        temporal_noise_pct=100.0,
        hot_pixel_pct=100.0,
    )


def test_evaluate_all_pass():
    stack = _uniform_stack(value=10, n=5, h=99, w=99)
    metrics = compute_stray_metrics(stack)
    v = evaluate_stray(metrics, _passing_thresholds())
    assert v.passed is True
    assert len(v.checks) == 5
    assert all(c.passed for c in v.checks)
    assert v.reason.startswith("PASS")


def test_evaluate_dc1_fails():
    stack = _uniform_stack(value=200, n=5, h=99, w=99)  # 暗本底 200/255 = 78%
    metrics = compute_stray_metrics(stack)
    thr = _passing_thresholds()
    thr.dc_pct_of_max = 1.0  # 实际 78% > 1% → FAIL
    v = evaluate_stray(metrics, thr)
    assert v.passed is False
    assert v.checks[0].passed is False
    assert v.checks[0].name == "DC1 本底强度"
    assert "DC1" in v.reason


def test_evaluate_dc2_fails():
    """局部杂光斑场景使 DC2 < 阈值。"""
    stack = _uniform_stack(value=5, n=5, h=99, w=99)
    stack[:, :30, :30] = 200
    metrics = compute_stray_metrics(stack)
    thr = _passing_thresholds()
    thr.zone_dc_uniformity_pct = 90.0  # 实际很低 → FAIL
    v = evaluate_stray(metrics, thr)
    assert v.passed is False
    assert v.checks[1].passed is False
    assert v.checks[1].name == "DC2 本底均匀性"


def test_evaluate_reason_format_pass_lists_all():
    stack = _uniform_stack(value=10, n=5, h=99, w=99)
    metrics = compute_stray_metrics(stack)
    v = evaluate_stray(metrics, _passing_thresholds())
    # PASS 时 reason 应该列出全部 5 项
    for name in ("DC1", "DC2", "DC3", "DC4", "DC5"):
        assert name in v.reason


def test_evaluate_reason_format_fail_lists_only_failures():
    """FAIL 时 reason 只列失败项，不应列已通过项。"""
    stack = _uniform_stack(value=200, n=5, h=99, w=99)
    metrics = compute_stray_metrics(stack)
    thr = _passing_thresholds()
    thr.dc_pct_of_max = 1.0
    v = evaluate_stray(metrics, thr)
    assert v.passed is False
    assert "DC1" in v.reason
    # DC2/3/4/5 都用宽松阈值，应通过，不在 fail reason 里
    assert "DC2" not in v.reason
    assert "DC5" not in v.reason
