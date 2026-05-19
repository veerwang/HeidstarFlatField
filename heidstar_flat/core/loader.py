"""按 glob 模式加载 TIFF 图像栈。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Tuple

import numpy as np
import tifffile


ProgressFn = Callable[[int, int], None]


def load_image_stack(
    directory: str | Path,
    pattern: str,
    progress: ProgressFn | None = None,
) -> Tuple[np.ndarray, List[str]]:
    """读取目录下匹配 `pattern` 的 TIFF，叠成 (N,H,W) 数组。

    所有图像必须 dtype、shape 一致；不一致时直接抛 ValueError。
    """
    image_dir = Path(directory)
    files = sorted(image_dir.glob(pattern))
    if not files:
        raise ValueError(f"目录 {directory} 中未找到匹配 {pattern} 的图像")

    first = tifffile.imread(files[0])
    if first.ndim != 2:
        raise ValueError(f"暂只支持单通道 2D 图像，{files[0].name} 形状为 {first.shape}")

    h, w = first.shape
    stack = np.zeros((len(files), h, w), dtype=first.dtype)
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
