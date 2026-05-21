"""杂散光评估：从关激发暗场图算暗本底指标。

判定 5 项 AND（独立于平场的 7 项判定）：

  DC1 本底强度        dark_mean / sensor_max × 100%               ≤ 阈值
  DC2 本底空间均匀性  (1 − std(zone)/mean(zone)) × 100%           ≥ 阈值
  DC3 DSNU 像素级     std(mean_image) / sensor_max × 100%         ≤ 阈值
  DC4 时间噪声底      median(std_over_time) / sensor_max × 100%   ≤ 阈值
  DC5 热像素密度      (#{mean_pixel > μ + Kσ}) / total × 100%     ≤ 阈值

DC1/DC2 看的是"暗本底整体水平和空间分布"；
DC3 看"像素级 fixed-pattern noise"（EMVA 1288 的 DSNU 粗版本）；
DC4 看"无信号下的随机噪声底"（决定 SNR 分母）；
DC5 看"明显异常的热像素个数"（DC1-DC4 都看不到孤立坏点）。

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
    # DSNU 像素级（std of 时间平均图，绝对 ADU + 归一化 %）
    dsnu_value: float = 0.0
    dsnu_pct_of_max: float = 0.0                 # ★ DC3（≤ 阈值）
    # 时间噪声底（逐像素跨帧 std 的中位数，绝对 ADU + 归一化 %）
    temporal_noise: float = 0.0
    temporal_noise_pct: float = 0.0              # ★ DC4（≤ 阈值）
    # 热像素（mean_pixel > μ + Kσ 的像素个数 + 占比 %）
    hot_pixel_count: int = 0
    hot_pixel_pct: float = 0.0                   # ★ DC5（≤ 阈值）
    # 疑似杂光斑位置：累积亮度最高的像素
    max_pixel_position: Tuple[int, int] = (0, 0)

    def as_table_rows(self) -> List[tuple]:
        return [
            ("★ DC1 本底强度 (判定, ≤)", f"{self.dc_pct_of_max:.4f} %"),
            ("★ DC2 本底均匀性 (判定, ≥)", f"{self.zone_dc_uniformity_pct:.2f} %"),
            ("★ DC3 DSNU 像素级 (判定, ≤)", f"{self.dsnu_pct_of_max:.4f} %"),
            ("★ DC4 时间噪声底 (判定, ≤)", f"{self.temporal_noise_pct:.4f} %"),
            ("★ DC5 热像素密度 (判定, ≤)", f"{self.hot_pixel_pct:.4f} %"),
            ("瓦片数", str(self.n_tiles)),
            ("Sensor max (推断)", f"{self.sensor_max:.0f}"),
            ("DSNU (绝对 ADU)", f"{self.dsnu_value:.3f}"),
            ("时间噪声 (绝对 ADU)", f"{self.temporal_noise:.3f}"),
            ("热像素个数", str(self.hot_pixel_count)),
            ("暗场 Min / Max", f"{self.dark_min:.2f} / {self.dark_max:.2f}"),
            ("暗场 Mean / P99", f"{self.dark_mean:.2f} / {self.dark_p99:.2f}"),
            ("最亮像素位置 (row, col)",
             f"({self.max_pixel_position[0]}, {self.max_pixel_position[1]})"),
        ]


@dataclass
class StrayLightThresholds:
    """杂散光判定阈值（全通道共用）。"""
    dc_pct_of_max: float            # DC1 上限 %
    zone_dc_uniformity_pct: float    # DC2 下限 %
    dsnu_pct_of_max: float           # DC3 上限 %
    temporal_noise_pct: float        # DC4 上限 %
    hot_pixel_pct: float             # DC5 上限 %


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

    # 一次性转 float32，便于 mean/std/median 在同一份数据上算
    stack_f32 = stack.astype(np.float32)

    # 全栈强度统计
    dark_min = float(stack.min())
    dark_max = float(stack.max())
    dark_mean = float(stack_f32.mean())
    dark_p99 = float(np.percentile(stack, 99))
    dc_pct = dark_mean / sensor_max * 100.0 if sensor_max > 0 else 0.0

    # 代表性"暗场均值图"（用于 DC2、DC3、DC5、最亮位置）
    mean_img = stack_f32.mean(axis=0)
    pixel_mean = float(mean_img.mean())

    # DC2：9 区 ROI 均值的均匀性
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

    # DC3：DSNU 像素级（mean_img 的空间 std，正比于 fixed-pattern noise）
    dsnu_value = float(mean_img.std())
    dsnu_pct = dsnu_value / sensor_max * 100.0 if sensor_max > 0 else 0.0

    # DC4：时间噪声底（每像素跨帧 std 的中位数）
    # 至少 2 帧才有意义；少于 2 帧时退化为 0
    if n >= 2:
        # ddof=0 是默认，与 numpy 标准一致；与 EMVA 1288 的 σ_temporal 同义
        pixel_std = stack_f32.std(axis=0)
        temporal_noise = float(np.median(pixel_std))
    else:
        temporal_noise = 0.0
    temporal_noise_pct = (
        temporal_noise / sensor_max * 100.0 if sensor_max > 0 else 0.0
    )

    # DC5：热像素（mean_img 中显著高于本底的孤立像素）
    # 阈值取 K=10 倍 DSNU：保守，只抓极端异常；偶发暗角不会误判
    K_HOT = 10.0
    hot_threshold = pixel_mean + K_HOT * dsnu_value
    hot_count = int((mean_img > hot_threshold).sum())
    hot_pct = hot_count / mean_img.size * 100.0 if mean_img.size > 0 else 0.0

    # 疑似杂光斑位置：mean_img 的全局 argmax
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
        dsnu_value=dsnu_value,
        dsnu_pct_of_max=dsnu_pct,
        temporal_noise=temporal_noise,
        temporal_noise_pct=temporal_noise_pct,
        hot_pixel_count=hot_count,
        hot_pixel_pct=hot_pct,
        max_pixel_position=(max_r, max_c),
    )


# ---------------- 判定 ----------------

def evaluate_stray(
    metrics: StrayLightMetrics, thr: StrayLightThresholds
) -> StrayLightVerdict:
    """5 项 AND 判定。"""
    items = [
        ("DC1 本底强度", metrics.dc_pct_of_max, thr.dc_pct_of_max, "<="),
        ("DC2 本底均匀性",
         metrics.zone_dc_uniformity_pct, thr.zone_dc_uniformity_pct, ">="),
        ("DC3 DSNU 像素级",
         metrics.dsnu_pct_of_max, thr.dsnu_pct_of_max, "<="),
        ("DC4 时间噪声底",
         metrics.temporal_noise_pct, thr.temporal_noise_pct, "<="),
        ("DC5 热像素密度",
         metrics.hot_pixel_pct, thr.hot_pixel_pct, "<="),
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
