"""平场均匀性指标计算与示例图像生成。

判定指标改造（按"稳健化 + 双指标 AND"原则）：
- 主判定使用 **robust Min/Max** = P1 / P99，对单像素污点/坏点免疫
- 第二判定使用 **CV 均匀性** (1 - σ/μ)，控制整体分散度
- 同时记录 Min/Max 出现位置 (像素坐标)，便于在热力图上可视化
- 原始 Min/Max、Michelson 仍计算并展示作为参考
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np


@dataclass
class UniformityMetrics:
    # 原始极值（含像素位置，用于可视化）
    minimum: float
    maximum: float
    min_position: Tuple[int, int]            # (row, col) - 用于热力图上标注
    max_position: Tuple[int, int]
    # 稳健极值（P1/P99，免疫单像素离群）
    p1: float
    p99: float
    # 整体分布
    mean: float
    std: float
    # 派生比值
    min_max_ratio_pct: float                 # Min/Max × 100，参考
    robust_min_max_ratio_pct: float          # ★ P1/P99 × 100，PASS/FAIL 主指标
    michelson_uniformity_pct: float          # (1-(M-m)/(M+m)) × 100，参考
    cv_uniformity_pct: float                 # ★ (1-σ/μ) × 100，PASS/FAIL 第二指标
    # 空间结构
    center_corner_ratio: float
    nine_zone_means: List[float] = field(default_factory=list)

    def as_table_rows(self) -> List[tuple]:
        """返回 (指标名, 数值字符串) 列表，供 QTableWidget 直接展示。
        判定指标用 ★ 标识；参考指标列其后。"""
        return [
            ("★ 稳健 Min/Max (判定)", f"{self.robust_min_max_ratio_pct:.2f} %"),
            ("★ CV 均匀性 (判定)", f"{self.cv_uniformity_pct:.2f} %"),
            ("P1 / P99", f"{self.p1:.4f} / {self.p99:.4f}"),
            ("原始 Min / Max", f"{self.minimum:.4f} / {self.maximum:.4f}"),
            ("Min 位置 (row, col)", f"({self.min_position[0]}, {self.min_position[1]})"),
            ("Max 位置 (row, col)", f"({self.max_position[0]}, {self.max_position[1]})"),
            ("原始 Min/Max 比", f"{self.min_max_ratio_pct:.2f} %"),
            ("Michelson 均匀性", f"{self.michelson_uniformity_pct:.2f} %"),
            ("均值 / 标准差", f"{self.mean:.4f} / {self.std:.4f}"),
            ("中心/四角比", f"{self.center_corner_ratio:.4f}"),
        ]


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
    """计算归一化平场和均匀性指标。返回 (normalized_flatfield, metrics)。"""
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

    if mx + mn > 0:
        michelson = (1.0 - (mx - mn) / (mx + mn)) * 100.0
    else:
        michelson = 0.0

    cv = (1.0 - std / mean) * 100.0 if mean > 0 else 0.0
    min_max_ratio_pct = (mn / mx * 100.0) if mx > 0 else 0.0
    robust_min_max_ratio_pct = (p1 / p99 * 100.0) if p99 > 0 else 0.0

    # 九区 ROI：行三等分、列三等分
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
    )
    return norm, metrics


def evaluate_verdict(
    metrics: UniformityMetrics,
    robust_threshold_pct: float,
    cv_threshold_pct: float,
) -> Tuple[bool, str]:
    """双指标 AND 判定。

    Returns:
        (passed, reason)
        - passed: 两个判定指标同时达标
        - reason: 人类可读的描述（PASS 时给数值摘要；FAIL 时列出失败项）
    """
    rmm = metrics.robust_min_max_ratio_pct
    cv = metrics.cv_uniformity_pct
    rmm_ok = rmm >= robust_threshold_pct
    cv_ok = cv >= cv_threshold_pct

    if rmm_ok and cv_ok:
        return True, (
            f"PASS (Min/Max {rmm:.2f}% ≥ {robust_threshold_pct:.2f}%, "
            f"CV {cv:.2f}% ≥ {cv_threshold_pct:.2f}%)"
        )

    fails = []
    if not rmm_ok:
        fails.append(f"Min/Max {rmm:.2f}% < {robust_threshold_pct:.2f}%")
    if not cv_ok:
        fails.append(f"CV {cv:.2f}% < {cv_threshold_pct:.2f}%")
    return False, "FAIL (" + " ; ".join(fails) + ")"


# 旧名兼容：仍可按主指标做单项判定（PDF/report 内部还在用），但建议改用 evaluate_verdict
def passes_threshold(metrics: UniformityMetrics, threshold_pct: float) -> bool:
    return metrics.robust_min_max_ratio_pct >= threshold_pct


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
