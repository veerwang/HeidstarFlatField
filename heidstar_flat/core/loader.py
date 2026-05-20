"""目录扫描式数据加载。

约定：扫描根目录下的若干「通道目录」，每个通道目录形如 `<prefix>_<Color>/`，
内部含：
  - `Images/IMG{row:03d}x{col:03d}.tif`：真正用于拟合平场的瓦片
  - `Scan.txt`：元数据（Fluo 名、颜色、曝光、增益、网格等）
  - Result/Preview/Focus/Thumbs：忽略

模块对外暴露：
  - `parse_scan_txt(path)` — 解析 Scan.txt
  - `discover_channels(root, ...)` — 列出根目录下所有可识别的通道
  - `load_channel_tiles(channel, ...)` — 把一个通道的瓦片堆成 (N,H,W) 数组
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import tifffile


ProgressFn = Callable[[int, int], None]


# ---------- Scan.txt 解析 ----------

_SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_KV_RE = re.compile(r"^(?P<k>[^=]+)=(?P<v>.*)$")


def parse_scan_txt(path: Path) -> Dict[str, Dict[str, str]]:
    """读 Scan.txt 返回 {section: {key: value}}。Scan.txt 不存在时返回空 dict。"""
    out: Dict[str, Dict[str, str]] = {}
    if not path.is_file():
        return out
    current: Optional[str] = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            current = m_sec.group("name")
            out.setdefault(current, {})
            continue
        if current is None:
            continue
        m_kv = _KV_RE.match(line)
        if m_kv:
            out[current][m_kv.group("k").strip()] = m_kv.group("v").strip()
    return out


def _first_with_prefix(d: Dict[str, str], prefix: str) -> Optional[str]:
    for k, v in d.items():
        if k.startswith(prefix):
            return v
    return None


def _to_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ---------- 通道发现 ----------

@dataclass
class DiscoveredChannel:
    """扫到的一个通道。其 suffix 是 *_<Color>/ 里的 <Color>。"""

    directory: Path                       # 通道目录绝对路径
    suffix: str                           # 目录名 _ 之后的部分（Blue / Cyan / ...）
    image_dir: Path                       # 实际瓦片所在子目录
    num_tiles: int                        # 瓦片张数
    fluo_name: Optional[str] = None       # 例：DAPI / PVB480
    color_hex: Optional[str] = None       # 例：#0000ff
    exposure_us: Optional[float] = None   # 单位 µs，来自 Scan.txt
    gain: Optional[int] = None
    grid_rows: Optional[int] = None
    grid_cols: Optional[int] = None
    tile_width: Optional[int] = None
    tile_height: Optional[int] = None
    pixel_bits: Optional[int] = None
    preview_path: Optional[Path] = None   # 缩略图（用于空闲态展示）
    scan_meta: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # 给 UI 用
    @property
    def display_name(self) -> str:
        if self.fluo_name:
            return f"{self.suffix} ({self.fluo_name})"
        return self.suffix


def _extract_suffix(dir_name: str) -> Optional[str]:
    """目录名最后一个下划线之后的部分作为 suffix。例如
    `2026-05-19-092323_Blue` → `Blue`。无下划线返回 None。"""
    if "_" not in dir_name:
        return None
    return dir_name.rsplit("_", 1)[-1]


def _find_preview(channel_dir: Path) -> Optional[Path]:
    """寻找一张轻量预览图。

    **优先非 LZW 压缩版本**：tifffile 解 LZW 需要可选的 imagecodecs 包，
    缺包时会抛 `<COMPRESSION.LZW: 5> requires the 'imagecodecs' package`。
    多数 Scan 目录里 `Preview-X.tif` 和 `Preview-X.lzw.tif` 都存在且大小相近，
    挑非压缩的更稳。
    """
    def _pick_non_lzw_then_lzw(paths) -> Optional[Path]:
        # 第一轮：非 lzw
        for p in paths:
            if ".lzw." not in p.name:
                return p
        # 第二轮：lzw（需要 imagecodecs，可能加载失败）
        for p in paths:
            return p
        return None

    chosen = _pick_non_lzw_then_lzw(sorted(channel_dir.glob("Preview-*.tif")))
    if chosen is not None:
        return chosen

    thumbs = channel_dir / "Thumbs"
    if thumbs.is_dir():
        return _pick_non_lzw_then_lzw(sorted(thumbs.glob("Preview-*.tif")))
    return None


def discover_channels(
    root: Path | str,
    image_subdir: str = "Images",
    image_glob: str = "IMG*.tif",
    suffix_whitelist: Optional[List[str]] = None,
) -> List[DiscoveredChannel]:
    """扫描 `root` 直接子目录，识别符合通道结构的目录。

    suffix_whitelist 不为 None 时，仅返回 suffix 在白名单中的通道（大小写敏感）。
    """
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"扫描根目录不存在: {root}")

    results: List[DiscoveredChannel] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        suffix = _extract_suffix(sub.name)
        if suffix is None:
            continue
        if suffix_whitelist is not None and suffix not in suffix_whitelist:
            continue
        images_dir = sub / image_subdir
        if not images_dir.is_dir():
            continue
        tiles = sorted(images_dir.glob(image_glob))
        if not tiles:
            continue

        meta = parse_scan_txt(sub / "Scan.txt")
        fluo = meta.get("Fluo", {})
        general = meta.get("General", {})

        # 颜色 & Fluo 名键名带 Fluo 名后缀，例如 ColorDAPI / ExpoTimeDAPI
        fluo_name = fluo.get("Name")
        color_hex = _first_with_prefix(fluo, "Color")
        expo = _to_float(_first_with_prefix(fluo, "ExpoTime"))
        gain = _to_int(_first_with_prefix(fluo, "ExpoGain"))

        ch = DiscoveredChannel(
            directory=sub.resolve(),
            suffix=suffix,
            image_dir=images_dir.resolve(),
            num_tiles=len(tiles),
            fluo_name=fluo_name,
            color_hex=color_hex,
            exposure_us=expo,
            gain=gain,
            grid_rows=_to_int(general.get("RowCount")),
            grid_cols=_to_int(general.get("ColumnCount")),
            tile_width=_to_int(general.get("ImageWidth")),
            tile_height=_to_int(general.get("ImageHeight")),
            pixel_bits=_to_int(general.get("PixelBits")),
            preview_path=_find_preview(sub),
            scan_meta=meta,
        )
        results.append(ch)

    return results


# ---------- 瓦片加载 ----------

def load_channel_tiles(
    channel: DiscoveredChannel,
    image_glob: str = "IMG*.tif",
    progress: ProgressFn | None = None,
) -> Tuple[np.ndarray, List[str]]:
    """加载一个通道的所有瓦片为 (N,H,W) 数组。"""
    files = sorted(channel.image_dir.glob(image_glob))
    if not files:
        raise ValueError(f"通道目录 {channel.directory} 下未找到 {image_glob}")

    first = tifffile.imread(files[0])
    if first.ndim != 2:
        raise ValueError(
            f"暂只支持单通道 2D 瓦片，{files[0].name} 形状为 {first.shape}"
        )

    h, w = first.shape
    estimated_bytes = len(files) * h * w * first.dtype.itemsize
    try:
        stack = np.zeros((len(files), h, w), dtype=first.dtype)
    except MemoryError as e:
        # 给清晰可操作的中文提示替代裸 MemoryError，worker 会把这条
        # 信息 emit 给 UI 的「错误徽章」+ 日志
        raise MemoryError(
            f"内存不足：需要为 {len(files)} 张 {h}×{w} {first.dtype} "
            f"瓦片分配约 {estimated_bytes / 1024 / 1024:.0f} MB 连续数组；"
            f"建议减少单次勾选的通道数 / 分批处理，或换更大内存的机器"
        ) from e
    stack[0] = first
    if progress:
        progress(1, len(files))

    for i, fp in enumerate(files[1:], 1):
        img = tifffile.imread(fp)
        if img.shape != first.shape:
            raise ValueError(
                f"{fp.name} shape={img.shape} 与首张 {first.shape} 不一致"
            )
        if img.dtype != first.dtype:
            raise ValueError(
                f"{fp.name} dtype={img.dtype} 与首张 {first.dtype} 不一致"
            )
        stack[i] = img
        if progress:
            progress(i + 1, len(files))

    return stack, [f.name for f in files]
