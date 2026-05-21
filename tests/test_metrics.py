"""平场算法单元测试。

针对 core/metrics.py 的 7 项 AND 判定核心函数。
"""

from __future__ import annotations

import numpy as np
import pytest

from heidstar_flat.core.metrics import (
    VerdictThresholds,
    compute_metrics,
    evaluate_verdict,
)


# ---------------- compute_metrics ----------------

def test_compute_perfect_uniform_flatfield():
    """完全均匀的平场：所有指标接近理论最优。"""
    flat = np.full((100, 100), 1.0, dtype=np.float32)
    norm, m = compute_metrics(flat)
    assert norm.shape == (100, 100)
    assert m.minimum == pytest.approx(1.0)
    assert m.maximum == pytest.approx(1.0)
    assert m.mean == pytest.approx(1.0)
    assert m.std == pytest.approx(0.0)
    # CV: 完美一致 → 100%
    assert m.cv_uniformity_pct == pytest.approx(100.0)
    # 9 区: 全部相等 → 100%
    assert m.nine_zone_uniformity_pct == pytest.approx(100.0)
    assert m.nine_zone_corner_symmetry_pct == pytest.approx(100.0)
    # P1/P99 = 1
    assert m.robust_min_max_ratio_pct == pytest.approx(100.0)
    # 顶端饱和率：全部 ≥ 0.99 → 100%
    assert m.top_saturation_pct == pytest.approx(100.0)


def test_compute_robust_minmax_resists_single_dead_pixel():
    """单个坏点 (强行设 0) 不会把 robust Min/Max 拉到 0。"""
    flat = np.full((100, 100), 0.8, dtype=np.float32)
    flat[50, 50] = 0.0  # 单个死像素
    _, m = compute_metrics(flat)
    # 原始 min/max 比应被坏点拉到 0
    assert m.min_max_ratio_pct == pytest.approx(0.0)
    # robust P1/P99 应几乎不受影响
    assert m.robust_min_max_ratio_pct > 90.0


def test_compute_records_min_max_position():
    """记录 min/max 像素位置。"""
    flat = np.full((50, 50), 0.5, dtype=np.float32)
    flat[10, 20] = 1.0  # 最亮
    flat[40, 30] = 0.1  # 最暗
    _, m = compute_metrics(flat)
    assert m.max_position == (10, 20)
    assert m.min_position == (40, 30)


def test_compute_nine_zone_breakdown():
    """9 区均值结构正确（顺序：行优先 0..8）。

    注意 compute_metrics 内部会先 _normalize（除以 max），所以输入要让 max=1.0，
    归一化才是恒等，区块均值才容易对得上。
    """
    flat = np.zeros((30, 30), dtype=np.float32)
    flat[10:20, 10:20] = 1.0  # 中心块满量程
    flat[:10, :10] = 0.5      # 左上半量程
    _, m = compute_metrics(flat)
    assert len(m.nine_zone_means) == 9
    assert m.nine_zone_means[4] == pytest.approx(1.0)  # 中心
    assert m.nine_zone_means[0] == pytest.approx(0.5)  # 左上
    # 其他 7 块为 0
    for idx in (1, 2, 3, 5, 6, 7, 8):
        assert m.nine_zone_means[idx] == pytest.approx(0.0)


def test_compute_rejects_invalid_shape():
    with pytest.raises(ValueError, match="非空"):
        compute_metrics(np.zeros((0, 10), dtype=np.float32))
    with pytest.raises(ValueError, match="非空"):
        compute_metrics(np.zeros((10,), dtype=np.float32))


def test_compute_rejects_too_small_image():
    with pytest.raises(ValueError, match="尺寸过小"):
        compute_metrics(np.zeros((2, 2), dtype=np.float32))


# ---------------- evaluate_verdict ----------------

def _strict_pass_thresholds() -> VerdictThresholds:
    """所有 7 项都应该被完全均匀的 flatfield 通过。"""
    return VerdictThresholds(
        robust_min_max_pct=99.0,
        cv_pct=99.0,
        corner_symmetry_pct=99.0,
        center_to_max_pct=99.0,
        min_zone_to_max_pct=99.0,
        nine_zone_uniformity_pct=99.0,
        top_saturation_pct=100.0,
    )


def test_evaluate_all_pass_on_uniform():
    flat = np.full((100, 100), 1.0, dtype=np.float32)
    _, m = compute_metrics(flat)
    v = evaluate_verdict(m, _strict_pass_thresholds())
    assert v.passed is True
    assert len(v.checks) == 7
    assert all(c.passed for c in v.checks)


def test_evaluate_min_max_failure():
    """中心亮、四角暗 → robust Min/Max 应被拉低。"""
    flat = np.full((100, 100), 1.0, dtype=np.float32)
    flat[:30, :30] = 0.2  # 左上暗角
    flat[:30, 70:] = 0.2
    flat[70:, :30] = 0.2
    flat[70:, 70:] = 0.2
    _, m = compute_metrics(flat)
    thr = _strict_pass_thresholds()
    thr.robust_min_max_pct = 90.0  # 暗角实际 P1/P99 远低于 90%
    v = evaluate_verdict(m, thr)
    # 至少 Min/Max 项 fail
    minmax_check = next(c for c in v.checks if c.name == "Min/Max")
    assert minmax_check.passed is False


def test_evaluate_top_saturation_direction():
    """顶端饱和是 ≤ 方向（与其他 6 项相反）。"""
    flat = np.full((100, 100), 1.0, dtype=np.float32)  # 全部 ≥ 0.99 → 100%
    _, m = compute_metrics(flat)
    thr = _strict_pass_thresholds()
    thr.top_saturation_pct = 5.0  # 实际 100% > 5% → 该项 FAIL（≤ 方向）
    v = evaluate_verdict(m, thr)
    sat_check = next(c for c in v.checks if c.name == "顶端饱和")
    assert sat_check.direction == "<="
    assert sat_check.passed is False
