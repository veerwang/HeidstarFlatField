"""平场均匀性指标计算与判定。

判定使用 6 项 AND 检查，每项独立阈值可配（统一约定"高 = 好，必须 ≥ 阈值"）：
  1. ★ robust Min/Max  (P1 / P99)         — 抗污点的暗角幅度
  2. ★ CV 均匀性       (1 − σ/μ)          — 整体分散度
  3. 四角对称性        (min_corner / max_corner) — 抓装配倾斜 / 同心度偏移
  4. 中心格最亮        (center / max_zone)  — 抓中心被遮挡
  5. 最暗格阈值        (min_zone / max_zone) — ROI 平均后的衰减幅度
  6. 九格粗糙度        (1 − σ_zone/μ_zone) — 大尺度结构均匀性

也记录 Min/Max 像素位置，用于在热力图上区分"暗角" vs "中心异常"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np


# ---------------- 数据模型 ----------------

@dataclass
class UniformityMetrics:
    # 原始极值（含像素位置）
    minimum: float
    maximum: float
    min_position: Tuple[int, int]
    max_position: Tuple[int, int]
    # 稳健极值
    p1: float
    p99: float
    # 整体统计
    mean: float
    std: float
    # 派生比值
    min_max_ratio_pct: float
    robust_min_max_ratio_pct: float         # ★ 判定 #1
    michelson_uniformity_pct: float
    cv_uniformity_pct: float                # ★ 判定 #2
    # 空间结构 (九区)
    center_corner_ratio: float
    nine_zone_means: List[float] = field(default_factory=list)
    # 九区派生（★ 判定 #3–#6）
    nine_zone_corner_symmetry_pct: float = 0.0
    nine_zone_center_to_max_pct: float = 0.0
    nine_zone_min_to_max_pct: float = 0.0
    nine_zone_uniformity_pct: float = 0.0

    def as_table_rows(self) -> List[tuple]:
        return [
            ("★ 稳健 Min/Max (判定)", f"{self.robust_min_max_ratio_pct:.2f} %"),
            ("★ CV 均匀性 (判定)", f"{self.cv_uniformity_pct:.2f} %"),
            ("★ 九区 四角对称 (判定)", f"{self.nine_zone_corner_symmetry_pct:.2f} %"),
            ("★ 九区 中心最亮 (判定)", f"{self.nine_zone_center_to_max_pct:.2f} %"),
            ("★ 九区 最暗格 (判定)", f"{self.nine_zone_min_to_max_pct:.2f} %"),
            ("★ 九区 粗糙度 (判定)", f"{self.nine_zone_uniformity_pct:.2f} %"),
            ("P1 / P99", f"{self.p1:.4f} / {self.p99:.4f}"),
            ("原始 Min / Max", f"{self.minimum:.4f} / {self.maximum:.4f}"),
            ("Min 位置 (row, col)", f"({self.min_position[0]}, {self.min_position[1]})"),
            ("Max 位置 (row, col)", f"({self.max_position[0]}, {self.max_position[1]})"),
            ("原始 Min/Max 比", f"{self.min_max_ratio_pct:.2f} %"),
            ("Michelson 均匀性", f"{self.michelson_uniformity_pct:.2f} %"),
            ("均值 / 标准差", f"{self.mean:.4f} / {self.std:.4f}"),
            ("中心/四角比", f"{self.center_corner_ratio:.4f}"),
        ]


@dataclass
class VerdictThresholds:
    """评判一个通道用到的全部阈值。"""
    robust_min_max_pct: float
    cv_pct: float
    corner_symmetry_pct: float
    center_to_max_pct: float
    min_zone_to_max_pct: float
    nine_zone_uniformity_pct: float


@dataclass
class VerdictCheck:
    name: str
    value_pct: float
    threshold_pct: float
    passed: bool


@dataclass
class VerdictResult:
    passed: bool
    checks: List[VerdictCheck]

    @property
    def reason(self) -> str:
        if self.passed:
            inner = " ; ".join(
                f"{c.name} {c.value_pct:.2f}%" for c in self.checks
            )
            return f"PASS ({inner})"
        fails = [c for c in self.checks if not c.passed]
        inner = " ; ".join(
            f"{c.name} {c.value_pct:.2f}% < {c.threshold_pct:.2f}%"
            for c in fails
        )
        return f"FAIL ({inner})"


# ---------------- 计算 ----------------

def _normalize(flatfield: np.ndarray) -> np.ndarray:
    m = float(np.max(flatfield))
    if m <= 0 or not np.isfinite(m):
        return flatfield.astype(np.float32)
    return (flatfield / m).astype(np.float32)


def _roi_mean(arr: np.ndarray, r0: int, r1: int, c0: int, c1: int) -> float:
    block = arr[r0:r1, c0:c1]
    if block.size == 0:
        return float("nan")
    return float(np.mean(block))


def _argmin_position(arr: np.ndarray) -> Tuple[int, int]:
    idx = int(np.argmin(arr))
    return divmod(idx, arr.shape[1])


def _argmax_position(arr: np.ndarray) -> Tuple[int, int]:
    idx = int(np.argmax(arr))
    return divmod(idx, arr.shape[1])


def compute_metrics(flatfield: np.ndarray) -> Tuple[np.ndarray, UniformityMetrics]:
    """计算归一化平场和均匀性指标。"""
    norm = _normalize(flatfield)
    h, w = norm.shape

    mn = float(np.min(norm))
    mx = float(np.max(norm))
    p1 = float(np.percentile(norm, 1))
    p99 = float(np.percentile(norm, 99))
    mean = float(np.mean(norm))
    std = float(np.std(norm))
    min_pos = _argmin_position(norm)
    max_pos = _argmax_position(norm)

    michelson = (1.0 - (mx - mn) / (mx + mn)) * 100.0 if mx + mn > 0 else 0.0
    cv = (1.0 - std / mean) * 100.0 if mean > 0 else 0.0
    min_max_ratio_pct = (mn / mx * 100.0) if mx > 0 else 0.0
    robust_min_max_ratio_pct = (p1 / p99 * 100.0) if p99 > 0 else 0.0

    # 九区 ROI
    rs = np.linspace(0, h, 4, dtype=int)
    cs = np.linspace(0, w, 4, dtype=int)
    zones: List[float] = []
    for i in range(3):
        for j in range(3):
            zones.append(_roi_mean(norm, rs[i], rs[i + 1], cs[j], cs[j + 1]))

    center = zones[4]
    corners = [zones[0], zones[2], zones[6], zones[8]]
    corner_avg = float(np.mean([c for c in corners if np.isfinite(c)]))
    cc_ratio = center / corner_avg if corner_avg > 0 else float("nan")

    # 九区派生
    zones_arr = np.asarray(zones, dtype=np.float64)
    nz_mean = float(np.mean(zones_arr))
    nz_std = float(np.std(zones_arr))
    nz_max = float(np.max(zones_arr))
    nz_min = float(np.min(zones_arr))
    corner_max = float(max(corners))
    corner_min = float(min(corners))

    nine_zone_corner_symmetry_pct = (
        corner_min / corner_max * 100.0 if corner_max > 0 else 0.0
    )
    nine_zone_center_to_max_pct = (
        center / nz_max * 100.0 if nz_max > 0 else 0.0
    )
    nine_zone_min_to_max_pct = (
        nz_min / nz_max * 100.0 if nz_max > 0 else 0.0
    )
    nine_zone_uniformity_pct = (
        (1.0 - nz_std / nz_mean) * 100.0 if nz_mean > 0 else 0.0
    )

    metrics = UniformityMetrics(
        minimum=mn,
        maximum=mx,
        min_position=min_pos,
        max_position=max_pos,
        p1=p1,
        p99=p99,
        mean=mean,
        std=std,
        min_max_ratio_pct=min_max_ratio_pct,
        robust_min_max_ratio_pct=robust_min_max_ratio_pct,
        michelson_uniformity_pct=michelson,
        cv_uniformity_pct=cv,
        center_corner_ratio=cc_ratio,
        nine_zone_means=zones,
        nine_zone_corner_symmetry_pct=nine_zone_corner_symmetry_pct,
        nine_zone_center_to_max_pct=nine_zone_center_to_max_pct,
        nine_zone_min_to_max_pct=nine_zone_min_to_max_pct,
        nine_zone_uniformity_pct=nine_zone_uniformity_pct,
    )
    return norm, metrics


# ---------------- 判定 ----------------

def evaluate_verdict(
    metrics: UniformityMetrics, thr: VerdictThresholds
) -> VerdictResult:
    """6 项 AND 判定。返回结构化结果（含每项 pass/fail）。"""
    items = [
        ("Min/Max", metrics.robust_min_max_ratio_pct, thr.robust_min_max_pct),
        ("CV", metrics.cv_uniformity_pct, thr.cv_pct),
        ("四角对称", metrics.nine_zone_corner_symmetry_pct, thr.corner_symmetry_pct),
        ("中心最亮", metrics.nine_zone_center_to_max_pct, thr.center_to_max_pct),
        ("最暗格", metrics.nine_zone_min_to_max_pct, thr.min_zone_to_max_pct),
        ("九格粗糙度", metrics.nine_zone_uniformity_pct, thr.nine_zone_uniformity_pct),
    ]
    checks = [
        VerdictCheck(name=n, value_pct=float(v), threshold_pct=float(t), passed=v >= t)
        for n, v, t in items
    ]
    return VerdictResult(passed=all(c.passed for c in checks), checks=checks)


# 旧 API 兼容（PDF/老代码）：单项主指标判定
def passes_threshold(metrics: UniformityMetrics, threshold_pct: float) -> bool:
    return metrics.robust_min_max_ratio_pct >= threshold_pct


# ---------------- 示例三联画 ----------------

@dataclass
class ExampleTriplet:
    index: int
    original: np.ndarray
    corrected: np.ndarray
    difference: np.ndarray


def build_examples(
    image_stack: np.ndarray,
    flatfield: np.ndarray,
    num_examples: int = 3,
) -> List[ExampleTriplet]:
    n = len(image_stack)
    if n == 0 or num_examples <= 0:
        return []
    k = min(num_examples, n)
    indices = np.linspace(0, n - 1, k, dtype=int)
    out: List[ExampleTriplet] = []
    safe_flat = np.where(flatfield > 0, flatfield, 1.0).astype(np.float32)
    for idx in indices:
        original = image_stack[int(idx)].astype(np.float32)
        corrected = original / safe_flat
        out.append(
            ExampleTriplet(
                index=int(idx),
                original=original,
                corrected=corrected,
                difference=corrected - original,
            )
        )
    return out
