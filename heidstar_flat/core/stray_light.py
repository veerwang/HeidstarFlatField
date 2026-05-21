"""杂散光评估：从关激发暗场图算暗本底指标。

判定 2 项 AND（独立于平场的 7 项判定）：

  DC1: dark_mean / sensor_max × 100%                    ≤ 阈值（默认 1%）
       本底光强度（暗电流 + 环境光泄漏 + 通道间漏光的总效应）。

  DC2: 9 区 ROI 均值的均匀性 (1 − std/mean) × 100%      ≥ 阈值（默认 60%）
       本底空间均匀性；若某一片明显偏亮，意味着该区域有局部杂光。

不做鬼影 C —— 关激发暗场图里没有亮点，C 鬼影需要的是带强亮点的图
（点光源样品 / 单 bead），将来若有此类采集再加。

sensor_max 由 dtype 推断：uint8 → 255，uint16 → 65535，float → 1.0。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np


# ---------------- 数据模型 ----------------

@dataclass
class StrayLightMetrics:
    n_tiles: int
    sensor_max: float
    # 全栈强度统计
    dark_min: float
    dark_max: float
    dark_mean: float
    dark_p99: float
    # 判定指标
    dc_pct_of_max: float                         # ★ DC1（≤ 阈值）
    zone_dc: List[float] = field(default_factory=list)  # 9 区均值
    zone_dc_uniformity_pct: float = 0.0          # ★ DC2（≥ 阈值）
    # 疑似杂光斑位置：累积亮度最高的像素
    max_pixel_position: Tuple[int, int] = (0, 0)

    def as_table_rows(self) -> List[tuple]:
        return [
            ("★ DC1 本底强度 (判定, ≤)", f"{self.dc_pct_of_max:.4f} %"),
            ("★ DC2 本底均匀性 (判定, ≥)", f"{self.zone_dc_uniformity_pct:.2f} %"),
            ("瓦片数", str(self.n_tiles)),
            ("Sensor max (推断)", f"{self.sensor_max:.0f}"),
            ("暗场 Min / Max", f"{self.dark_min:.2f} / {self.dark_max:.2f}"),
            ("暗场 Mean / P99", f"{self.dark_mean:.2f} / {self.dark_p99:.2f}"),
            ("最亮像素位置 (row, col)",
             f"({self.max_pixel_position[0]}, {self.max_pixel_position[1]})"),
        ]


@dataclass
class StrayLightThresholds:
    """杂散光判定阈值（全通道共用）。"""
    dc_pct_of_max: float          # DC1 上限 %
    zone_dc_uniformity_pct: float  # DC2 下限 %


@dataclass
class StrayLightCheck:
    name: str
    value_pct: float
    threshold_pct: float
    passed: bool
    direction: str = "<="           # "<=" or ">="


@dataclass
class StrayLightVerdict:
    passed: bool
    checks: List[StrayLightCheck]

    @property
    def reason(self) -> str:
        if self.passed:
            inner = " ; ".join(
                f"{c.name} {c.value_pct:.4f}%" for c in self.checks
            )
            return f"PASS ({inner})"
        fails = [c for c in self.checks if not c.passed]
        inner = " ; ".join(
            # 失败时数学符号方向反转：≤ 失败 → 实际 >；≥ 失败 → 实际 <
            f"{c.name} {c.value_pct:.4f}% "
            f"{'>' if c.direction == '<=' else '<'} {c.threshold_pct:.4f}%"
            for c in fails
        )
        return f"FAIL ({inner})"


# ---------------- 计算 ----------------

def _sensor_max(dtype: np.dtype) -> float:
    """根据 dtype 推断传感器最大可达值。"""
    if dtype == np.uint8:
        return 255.0
    if dtype == np.uint16:
        return 65535.0
    if dtype == np.uint32:
        return float(2 ** 32 - 1)
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return float(info.max)
    # float TIFF：假设已归一化到 [0, 1]
    return 1.0


def compute_stray_metrics(stack: np.ndarray) -> StrayLightMetrics:
    """对暗场瓦片栈 (N,H,W) 算 DC1/DC2 + 极值统计。"""
    if stack.ndim != 3 or stack.size == 0:
        raise ValueError(
            f"stack 必须是非空 (N,H,W) 数组，当前 shape={stack.shape}"
        )
    n, h, w = stack.shape
    if h < 3 or w < 3:
        raise ValueError(
            f"瓦片尺寸过小 (H={h}, W={w})，九区分析需要至少 3×3 像素"
        )

    sensor_max = _sensor_max(stack.dtype)

    # 全栈强度统计（np 默认在内部用 float64 累加，对 uint8/uint16 安全）
    dark_min = float(stack.min())
    dark_max = float(stack.max())
    dark_mean = float(stack.mean())
    dark_p99 = float(np.percentile(stack, 99))
    dc_pct = dark_mean / sensor_max * 100.0 if sensor_max > 0 else 0.0

    # 9 区 ROI：先把所有瓦片累平均得到代表性"暗场均值图"，再切 3×3
    mean_img = stack.astype(np.float32).mean(axis=0)
    rs = np.linspace(0, h, 4, dtype=int)
    cs = np.linspace(0, w, 4, dtype=int)
    zones: List[float] = []
    for i in range(3):
        for j in range(3):
            block = mean_img[rs[i]:rs[i + 1], cs[j]:cs[j + 1]]
            zones.append(float(block.mean()) if block.size else 0.0)

    zones_arr = np.asarray(zones, dtype=np.float64)
    nz_mean = float(zones_arr.mean())
    nz_std = float(zones_arr.std())
    zone_uniformity = (
        (1.0 - nz_std / nz_mean) * 100.0 if nz_mean > 0 else 0.0
    )

    # 疑似杂光斑位置：累积亮度最高的像素（用 mean_img 的 argmax）
    flat_idx = int(np.argmax(mean_img))
    max_r, max_c = divmod(flat_idx, w)

    return StrayLightMetrics(
        n_tiles=n,
        sensor_max=sensor_max,
        dark_min=dark_min,
        dark_max=dark_max,
        dark_mean=dark_mean,
        dark_p99=dark_p99,
        dc_pct_of_max=dc_pct,
        zone_dc=zones,
        zone_dc_uniformity_pct=zone_uniformity,
        max_pixel_position=(max_r, max_c),
    )


# ---------------- 判定 ----------------

def evaluate_stray(
    metrics: StrayLightMetrics, thr: StrayLightThresholds
) -> StrayLightVerdict:
    """2 项 AND 判定。"""
    items = [
        ("DC1 本底强度", metrics.dc_pct_of_max, thr.dc_pct_of_max, "<="),
        ("DC2 本底均匀性",
         metrics.zone_dc_uniformity_pct, thr.zone_dc_uniformity_pct, ">="),
    ]
    checks = []
    for name, value, t, direction in items:
        passed = (value <= t) if direction == "<=" else (value >= t)
        checks.append(
            StrayLightCheck(
                name=name,
                value_pct=float(value),
                threshold_pct=float(t),
                passed=passed,
                direction=direction,
            )
        )
    return StrayLightVerdict(
        passed=all(c.passed for c in checks), checks=checks
    )
