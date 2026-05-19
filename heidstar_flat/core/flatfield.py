"""BaSiCPy 平场拟合的薄封装。

延迟导入 basicpy，避免 GUI 启动时间被 JAX 初始化拖慢。
"""

from __future__ import annotations

import numpy as np


def calculate_flatfield(image_stack: np.ndarray, smoothness: float = 1.0) -> np.ndarray:
    """对图像栈拟合 BaSiC，仅返回 flatfield (H,W) float32。"""
    from basicpy import BaSiC  # 延迟导入

    basic = BaSiC(get_darkfield=False, smoothness_flatfield=smoothness)
    basic.fit(image_stack)
    flatfield = np.asarray(basic.flatfield, dtype=np.float32)
    return flatfield


def clear_jax_caches() -> None:
    """每通道处理完后尽量释放 JAX/BaSiC 占用，缓解 OOM。"""
    try:
        import jax

        if hasattr(jax, "clear_caches"):
            jax.clear_caches()
    except Exception:
        pass
