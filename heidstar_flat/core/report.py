"""PDF 报告生成：封面汇总 + 每通道概览页 + 示例三联画。

使用 matplotlib 的 PdfPages 后端，**无新增依赖**。

报告结构：
  1. 封面：标题 / 扫描根目录 / 输出目录 / 生成时间 / 通道汇总表
  2. 每通道一页概览：通道名 + PASS|FAIL 徽章 / 元数据 / 平场热力图 /
     强度直方图 / 中心十字断面 / 均匀性指标表 / 九区 ROI 表
  3. 每个示例图三联画一页：原图 / 校正后 / 差异
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np


A4_PORTRAIT = (8.27, 11.69)
A4_LANDSCAPE = (11.69, 8.27)

ProgressFn = Callable[[str, int, int], None]   # (label, current_page, total_pages)


def _fmt_exposure(us: Optional[float]) -> str:
    if us is None:
        return "—"
    if us >= 1000:
        return f"{us/1000:.2f} ms"
    return f"{us:.0f} µs"


def _verdict_text(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _verdict_color(passed: bool) -> str:
    return "#2ea043" if passed else "#cf222e"


def generate_pdf_report(
    results: List,                # List[ChannelResult]
    output_path: Path | str,
    scan_root: str,
    output_dir: str,
    progress_fn: Optional[ProgressFn] = None,
) -> Path:
    """生成包含所有通道的 PDF 报告，落到 output_path。"""
    # 确保 matplotlib 字体（CJK）和 rcParams 已配置
    from heidstar_flat.ui import mpl_canvas  # noqa: F401

    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_pages = 1
    for r in results:
        total_pages += 1 + len(r.examples)

    page_idx = 0

    def _bump(label: str) -> None:
        nonlocal page_idx
        page_idx += 1
        if progress_fn:
            progress_fn(label, page_idx, total_pages)

    with PdfPages(str(output_path)) as pdf:
        fig = _build_cover(results, scan_root, output_dir)
        pdf.savefig(fig)
        _close(fig)
        _bump("封面")

        for r in results:
            fig = _build_overview(r)
            pdf.savefig(fig)
            _close(fig)
            _bump(f"{r.suffix} 概览")

            for i, ex in enumerate(r.examples, 1):
                fig = _build_example(r, ex, i)
                pdf.savefig(fig, dpi=120)
                _close(fig)
                _bump(f"{r.suffix} 示例 {i}")

        # PDF 元数据
        d = pdf.infodict()
        d["Title"] = "Heidstar 多通道平场性检测报告"
        d["Author"] = "Heidstar Flat"
        d["Subject"] = f"Scan: {scan_root}"
        d["CreationDate"] = datetime.now()

    return output_path


def _close(fig) -> None:
    """安全关闭 figure，释放内存。"""
    try:
        import matplotlib.pyplot as plt

        plt.close(fig)
    except Exception:
        pass


# ---------- 页面构造 ----------

def _build_cover(results: List, scan_root: str, output_dir: str):
    from matplotlib.figure import Figure

    fig = Figure(figsize=A4_PORTRAIT)
    fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)

    ax = fig.add_subplot(111)
    ax.axis("off")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ax.text(
        0.5, 0.97,
        "Heidstar 多通道平场性检测报告",
        ha="center", va="top", fontsize=20, fontweight="bold",
        transform=ax.transAxes,
    )
    ax.text(
        0.5, 0.93,
        f"生成时间  {now}",
        ha="center", va="top", fontsize=11, color="#555",
        transform=ax.transAxes,
    )

    ax.text(0.04, 0.88, f"扫描根目录: {scan_root}",
            fontsize=10, transform=ax.transAxes)
    ax.text(0.04, 0.86, f"输出目录:   {output_dir}",
            fontsize=10, transform=ax.transAxes)

    pass_count = sum(1 for r in results if r.passed)
    fail_count = len(results) - pass_count
    ax.text(
        0.04, 0.83,
        f"通道总数 {len(results)}  ·  PASS {pass_count}  ·  FAIL {fail_count}",
        fontsize=12, fontweight="bold", transform=ax.transAxes,
    )

    ax.text(0.04, 0.79, "通道汇总", fontsize=14, fontweight="bold",
            transform=ax.transAxes)

    headers = ["通道", "Fluo", "瓦片",
               "Min/Max", "CV", "四角对称", "中心", "最暗格", "九格粗糙",
               "顶端饱和", "判定"]
    rows = []
    for r in results:
        fluo = r.job.discovered.fluo_name or "—"
        m = r.metrics
        rows.append([
            r.job.display_name,
            fluo,
            str(r.num_images),
            f"{m.robust_min_max_ratio_pct:.1f}",
            f"{m.cv_uniformity_pct:.1f}",
            f"{m.nine_zone_corner_symmetry_pct:.1f}",
            f"{m.nine_zone_center_to_max_pct:.1f}",
            f"{m.nine_zone_min_to_max_pct:.1f}",
            f"{m.nine_zone_uniformity_pct:.1f}",
            f"{m.top_saturation_pct:.2f}",
            _verdict_text(r.passed),
        ])

    # 用一个独立轴放表格，便于精准定位
    table_ax = fig.add_axes([0.04, 0.30, 0.92, 0.45])
    table_ax.axis("off")
    table = table_ax.table(
        cellText=rows, colLabels=headers,
        loc="upper left", cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.0)
    table.scale(1, 1.7)
    # 染色：判定列；每个数值单元格按 PASS/FAIL 着色（对应该项的对比阈值）
    for i, r in enumerate(results, 1):
        cell = table[(i, len(headers) - 1)]
        cell.set_facecolor(_verdict_color(r.passed))
        cell.set_text_props(color="white", fontweight="bold")
        # 染色 6 个指标数值列：3..8（headers 索引）
        check_pass = [c.passed for c in r.verdict.checks]
        # 7 项指标列：3..9
        for col, ok in zip(range(3, 3 + len(check_pass)), check_pass):
            cell = table[(i, col)]
            cell.set_facecolor("#e8f4ec" if ok else "#fbe2e2")
    # 表头加粗
    for j in range(len(headers)):
        table[(0, j)].set_facecolor("#dde4ea")
        table[(0, j)].set_text_props(fontweight="bold")

    ax.text(
        0.5, 0.04,
        "Heidstar Flat — 基于 BaSiCPy 拟合的平场均匀性检测",
        ha="center", va="bottom", fontsize=9, color="#888",
        transform=ax.transAxes,
    )

    return fig


def _build_overview(result):
    from matplotlib.figure import Figure

    fig = Figure(figsize=A4_PORTRAIT)
    gs = fig.add_gridspec(
        4, 2,
        height_ratios=[0.7, 3.5, 2.5, 3.5],
        width_ratios=[1.2, 1],
        hspace=0.45, wspace=0.30,
        left=0.06, right=0.96, top=0.96, bottom=0.04,
    )

    # —— 头部 ——
    ax_hdr = fig.add_subplot(gs[0, :])
    ax_hdr.axis("off")
    ax_hdr.text(
        0, 0.85, result.job.display_name,
        fontsize=18, fontweight="bold",
        transform=ax_hdr.transAxes,
    )
    ax_hdr.text(
        1.0, 0.85, _verdict_text(result.passed),
        fontsize=18, fontweight="bold", color="white",
        ha="right", va="center",
        transform=ax_hdr.transAxes,
        bbox=dict(
            facecolor=_verdict_color(result.passed),
            edgecolor="none", boxstyle="round,pad=0.5",
        ),
    )

    fluo = result.job.discovered.fluo_name or "—"
    expo = _fmt_exposure(result.job.discovered.exposure_us)
    gain = (
        str(result.job.discovered.gain)
        if result.job.discovered.gain is not None else "—"
    )
    grid = (
        f"{result.job.discovered.grid_rows}×{result.job.discovered.grid_cols}"
        if result.job.discovered.grid_rows and result.job.discovered.grid_cols
        else "—"
    )
    meta_line = (
        f"Fluo: {fluo}    曝光: {expo}    增益: {gain}    "
        f"瓦片: {result.num_images}    网格: {grid}    "
        f"判定: 7 项 AND"
    )
    ax_hdr.text(
        0, 0.30, meta_line,
        fontsize=10, color="#444",
        transform=ax_hdr.transAxes,
    )
    # 7 项检查行内列出（用 OK / NG 文本，避免某些 CJK 字体缺 ✗ 字形）
    if getattr(result, "verdict", None) and result.verdict.checks:
        bits = []
        for c in result.verdict.checks:
            mark = "OK" if c.passed else "NG"
            direction = getattr(c, "direction", ">=")
            op = "≥" if direction == ">=" else "≤"
            bits.append(
                f"[{mark}] {c.name} {c.value_pct:.1f}%{op}{c.threshold_pct:.1f}%"
            )
        ax_hdr.text(
            0, 0.04, "   ".join(bits),
            fontsize=8.0, color="#222",
            transform=ax_hdr.transAxes,
        )

    # —— 热力图（带 Min/Max 位置标注）——
    ax_hm = fig.add_subplot(gs[1, 0])
    im = ax_hm.imshow(
        result.flatfield_normalized,
        cmap="viridis", vmin=0.0, vmax=1.0,
        origin="upper", aspect="equal",
    )
    ax_hm.set_title("归一化平场", fontsize=12)
    ax_hm.set_xlabel("X (pixels)", fontsize=9)
    ax_hm.set_ylabel("Y (pixels)", fontsize=9)
    fig.colorbar(im, ax=ax_hm, fraction=0.046, pad=0.04, label="强度")
    mr, mc = result.metrics.min_position
    Mr, Mc = result.metrics.max_position
    ax_hm.plot(mc, mr, "x", color="red", markersize=14, markeredgewidth=2.2,
               label=f"Min @ ({mr},{mc})")
    ax_hm.plot(Mc, Mr, "o", color="#ffd166", markersize=10, markeredgewidth=1.8,
               markerfacecolor="none", label=f"Max @ ({Mr},{Mc})")
    ax_hm.legend(loc="upper right", framealpha=0.85, fontsize=8)

    # —— 直方图 ——
    ax_hist = fig.add_subplot(gs[1, 1])
    ax_hist.hist(
        result.flatfield_normalized.ravel(),
        bins=50, color="#3a6ea5", edgecolor="black", alpha=0.85,
    )
    ax_hist.set_xlim(0, 1)
    ax_hist.set_title("强度分布", fontsize=12)
    ax_hist.set_xlabel("归一化强度", fontsize=9)
    ax_hist.set_ylabel("像素数", fontsize=9)
    ax_hist.grid(True, alpha=0.3)

    # —— 中心十字断面 ——
    ax_cs = fig.add_subplot(gs[2, :])
    norm = result.flatfield_normalized
    h, w = norm.shape
    cr, cc = h // 2, w // 2
    ax_cs.plot(norm[cr, :], label=f"行 {cr}", color="#1f77b4")
    ax_cs.plot(norm[:, cc], label=f"列 {cc}", color="#d62728")
    ax_cs.set_ylim(0, 1.05)
    ax_cs.set_xlabel("像素位置", fontsize=9)
    ax_cs.set_ylabel("归一化强度", fontsize=9)
    ax_cs.set_title("中心十字断面", fontsize=12)
    ax_cs.legend(loc="lower right", fontsize=9)
    ax_cs.grid(True, alpha=0.3)

    # —— 指标表 ——
    ax_met = fig.add_subplot(gs[3, 0])
    ax_met.axis("off")
    ax_met.set_title("均匀性指标", fontsize=12, loc="left", fontweight="bold")
    rows = result.metrics.as_table_rows()
    t1 = ax_met.table(
        cellText=rows, colLabels=["指标", "数值"],
        loc="upper left", cellLoc="left",
        colWidths=[0.55, 0.40],
    )
    t1.auto_set_font_size(False)
    t1.set_fontsize(8.5)
    t1.scale(1, 1.45)
    for j in (0, 1):
        t1[(0, j)].set_facecolor("#dde4ea")
        t1[(0, j)].set_text_props(fontweight="bold")
    # 判定指标行加粗
    if rows and rows[0][0].startswith("★"):
        for j in (0, 1):
            t1[(1, j)].set_text_props(fontweight="bold")

    # —— 九区 ROI ——
    ax_nz = fig.add_subplot(gs[3, 1])
    ax_nz.axis("off")
    ax_nz.set_title("九区 ROI 均值", fontsize=12, loc="left", fontweight="bold")
    zones = result.metrics.nine_zone_means
    z_rows = [
        [f"{zones[i * 3 + j]:.3f}" for j in range(3)]
        for i in range(3)
    ]
    t2 = ax_nz.table(
        cellText=z_rows, loc="upper left", cellLoc="center",
    )
    t2.auto_set_font_size(False)
    t2.set_fontsize(11)
    t2.scale(1, 2.2)
    # 中心格高亮
    t2[(1, 1)].set_facecolor("#fff3b0")
    t2[(1, 1)].set_text_props(fontweight="bold")

    return fig


def _build_example(result, ex, idx_in_channel: int):
    from matplotlib.figure import Figure

    fig = Figure(figsize=A4_LANDSCAPE)
    fig.suptitle(
        f"{result.job.display_name}    示例 #{idx_in_channel}    (原图 idx={ex.index})",
        fontsize=13, fontweight="bold",
    )
    axes = fig.subplots(1, 3)
    fig.subplots_adjust(left=0.04, right=0.96, top=0.90, bottom=0.04, wspace=0.15)

    for ax, img, title, cmap in zip(
        axes,
        [ex.original, ex.corrected, ex.difference],
        ["原图", "校正后", "差异 (校正 − 原)"],
        ["gray", "gray", "RdBu_r"],
    ):
        if cmap == "RdBu_r":
            vmax = float(np.max(np.abs(img))) if np.any(img) else 1.0
            im = ax.imshow(img, cmap=cmap, vmin=-vmax, vmax=vmax, origin="upper")
        else:
            im = ax.imshow(img, cmap=cmap, origin="upper")
        ax.set_title(title, fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    return fig
