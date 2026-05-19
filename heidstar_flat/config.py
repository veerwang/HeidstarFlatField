"""默认配置：通道、阈值、输出目录、文件命名。

用户可在 GUI 中临时修改，并通过设置对话框持久化到 user config dir。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


@dataclass
class ChannelConfig:
    wavelength: str
    pattern: str
    uniformity_threshold: float


@dataclass
class AppConfig:
    channels: List[ChannelConfig] = field(default_factory=list)
    examples_per_channel: int = 3
    output_subdir: str = "flatfield_results"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        channels = [ChannelConfig(**c) for c in data.get("channels", [])]
        return cls(
            channels=channels or default_channels(),
            examples_per_channel=int(data.get("examples_per_channel", 3)),
            output_subdir=data.get("output_subdir", "flatfield_results"),
        )


def default_channels() -> List[ChannelConfig]:
    return [
        ChannelConfig("405", "*Fluorescence_405_nm_Ex.tiff", 85.0),
        ChannelConfig("488", "*Fluorescence_488_nm_Ex.tiff", 85.0),
        ChannelConfig("561", "*Fluorescence_561_nm_Ex.tiff", 85.0),
        ChannelConfig("638", "*Fluorescence_638_nm_Ex.tiff", 85.0),
        ChannelConfig("730", "*Fluorescence_730_nm_Ex.tiff", 80.0),
    ]


def default_config() -> AppConfig:
    return AppConfig(channels=default_channels())


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
