"""默认配置：通道偏好、阈值、扫描子目录约定。

通道偏好用 `suffix → ChannelPref` 字典存储；运行时由发现到的通道与之合并，
未在字典中的 suffix 走全局默认阈值。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ChannelPref:
    """对某个通道 suffix 的偏好设置。"""

    suffix: str
    display_name: Optional[str] = None    # 留空则用 suffix（或叠加 Scan.txt 的 Fluo 名）
    uniformity_threshold: float = 85.0


@dataclass
class AppConfig:
    channel_prefs: List[ChannelPref] = field(default_factory=list)
    examples_per_channel: int = 3
    output_subdir: str = "flatfield_results"
    # 每通道 robust Min/Max (P1/P99) 阈值；发现到但未在 prefs 中的通道用此默认
    default_threshold: float = 30.0
    # 以下为全局阈值（所有通道共用），构成 6 项 AND 判定的其余 5 项
    cv_threshold: float = 75.0                          # CV 均匀性 (1-σ/μ)
    corner_symmetry_threshold: float = 70.0             # 四角对称: min_corner/max_corner
    center_to_max_threshold: float = 95.0               # 中心最亮: center/max_zone
    min_zone_to_max_threshold: float = 40.0             # 最暗格: min_zone/max_zone
    nine_zone_uniformity_threshold: float = 75.0        # 九格粗糙度: 1-σ_zone/μ_zone
    top_saturation_threshold: float = 5.0               # 顶端饱和率 ≤ 阈值 (% pixels ≥ 0.99)
    image_subdir: str = "Images"
    image_glob: str = "IMG*.tif"

    def pref_for(self, suffix: str) -> ChannelPref:
        for p in self.channel_prefs:
            if p.suffix == suffix:
                return p
        return ChannelPref(suffix=suffix, uniformity_threshold=self.default_threshold)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        prefs = [ChannelPref(**p) for p in data.get("channel_prefs", [])]
        return cls(
            channel_prefs=prefs or default_channel_prefs(),
            examples_per_channel=int(data.get("examples_per_channel", 3)),
            output_subdir=data.get("output_subdir", "flatfield_results"),
            default_threshold=float(data.get("default_threshold", 30.0)),
            cv_threshold=float(data.get("cv_threshold", 75.0)),
            corner_symmetry_threshold=float(
                data.get("corner_symmetry_threshold", 70.0)
            ),
            center_to_max_threshold=float(
                data.get("center_to_max_threshold", 95.0)
            ),
            min_zone_to_max_threshold=float(
                data.get("min_zone_to_max_threshold", 40.0)
            ),
            nine_zone_uniformity_threshold=float(
                data.get("nine_zone_uniformity_threshold", 75.0)
            ),
            top_saturation_threshold=float(
                data.get("top_saturation_threshold", 5.0)
            ),
            image_subdir=data.get("image_subdir", "Images"),
            image_glob=data.get("image_glob", "IMG*.tif"),
        )


def default_channel_prefs() -> List[ChannelPref]:
    """默认 7 个荧光通道的 Min/Max ratio 阈值偏好（边缘亮度 ≥ 中心 X%）。

    阈值依据 data/0519 实测值留出余量：
    - Yellow/Orange 暗角最重 (~24-28%)，默认 20%
    - Blue/Green 中等 (~33-37%)，默认 25-30%
    - Cyan/Red 较好 (~40-42%)，默认 30%
    - Purple 最均匀 (~57%)，默认 50%
    需要按你的产线接受范围进一步收紧或放宽。
    """
    return [
        ChannelPref("Blue", "Blue (DAPI)", 30.0),
        ChannelPref("Cyan", "Cyan (PVB480)", 30.0),
        ChannelPref("Green", "Green (PVB520)", 30.0),
        ChannelPref("Yellow", "Yellow (PVB570)", 20.0),
        ChannelPref("Orange", "Orange (PVB620)", 25.0),
        ChannelPref("Red", "Red (PVB690)", 30.0),
        ChannelPref("Purple", "Purple (PVB780)", 50.0),
    ]


def default_config() -> AppConfig:
    return AppConfig(channel_prefs=default_channel_prefs())


def _user_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "heidstar_flat"


CONFIG_FILE = _user_config_dir() / "config.json"


def load_config() -> AppConfig:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return AppConfig.from_dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return default_config()


def save_config(cfg: AppConfig) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
