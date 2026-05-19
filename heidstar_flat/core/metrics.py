"""平场均匀性指标计算与示例图像生成。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np


@dataclass
class UniformityMetrics:
    minimum: float
    maximum: float
    mean: float
    std: float
    michelson_uniformity_pct: float          # (1 - (Max-Min)/(Max+Min)) * 100
    cv_uniformity_pct: float                 # (1 - σ/μ) * 100
    center_corner_ratio: float               # 中心 ROI 均值 / 四角 ROI 均值平均
    nine_zone_means: List[float] = field(default_factory=list)  # row-major, 长度 9

    def as_table_rows(self) -> List[tuple]:
        """返回 (指标名, 数值字符串) 列表，供 QTableWidget 直接展示。"""
        return [
            ("最小值", f"{self.minimum:.4f}"),
            ("最大值", f"{self.maximum:.4f}"),
            ("均值", f"{self.mean:.4f}"),
            ("标准差", f"{self.std:.4f}"),
            ("Michelson 均匀性", f"{self.michelson_uniformity_pct:.2f} %"),
            ("CV 均匀性 (1-σ/μ)", f"{self.cv_uniformity_pct:.2f} %"),
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


def compute_metrics(flatfield: np.ndarray) -> tuple[np.ndarray, UniformityMetrics]:
    """计算归一化平场和均匀性指标。返回 (normalized_flatfield, metrics)。"""
    norm = _normalize(flatfield)
    h, w = norm.shape

    mn = float(np.min(norm))
    mx = float(np.max(norm))
    mean = float(np.mean(norm))
    std = float(np.std(norm))

    if mx + mn > 0:
        michelson = (1.0 - (mx - mn) / (mx + mn)) * 100.0
    else:
        michelson = 0.0

    cv = (1.0 - std / mean) * 100.0 if mean > 0 else 0.0

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
        mean=mean,
        std=std,
        michelson_uniformity_pct=michelson,
        cv_uniformity_pct=cv,
        center_corner_ratio=cc_ratio,
        nine_zone_means=zones,
    )
    return norm, metrics


def passes_threshold(metrics: UniformityMetrics, threshold_pct: float) -> bool:
    return metrics.michelson_uniformity_pct >= threshold_pct


@dataclass
class ExampleTriplet:
    index: int
    original: np.ndarray   # float32
    corrected: np.ndarray  # float32
    difference: np.ndarray # float32


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
    # 避免除零
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
