"""杂散光 PDF 报告：封面汇总 + 每通道概览页（独立于平场报告）。

每通道仅一页，比平场报告轻很多（无示例三联画 / 无校正图 / 无断面）。
页面布局：
  - 头部：通道名 + PASS/FAIL 徽章 + 元数据 + 2 项判定的 OK/NG 行
  - 暗场均值热力图 + 灰度分布直方图
  - 杂散光指标表 + 9 区均值 mini 热力图
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np


A4_PORTRAIT = (8.27, 11.69)

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


def generate_stray_pdf_report(
    results: List,                # List[StrayChannelResult]
    output_path: Path | str,
    scan_root: str,
    output_dir: str,
    progress_fn: Optional[ProgressFn] = None,
) -> Path:
    """生成杂散光 PDF 报告（封面 + 每通道一页）。"""
    # 确保 matplotlib 字体（CJK）和 rcParams 已配置
    from heidstar_flat.ui import mpl_canvas  # noqa: F401

    from heidstar_flat import __version__
    from matplotlib.backends.backend_pdf import PdfPages

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_pages = 1 + len(results)
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

        d = pdf.infodict()
        d["Title"] = "Heidstar 杂散光评估报告"
        d["Author"] = f"Heidstar Flat v{__version__}"
        d["Subject"] = f"Stray light scan: {scan_root}"
        d["CreationDate"] = datetime.now()

    return output_path


def _close(fig) -> None:
    try:
        import matplotlib.pyplot as plt
        plt.close(fig)
    except Exception:
        pass


# ---------- 封面 ----------

def _build_cover(results: List, scan_root: str, output_dir: str):
    from heidstar_flat import __version__
    from matplotlib.figure import Figure

    fig = Figure(figsize=A4_PORTRAIT)
    fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)

    ax = fig.add_subplot(111)
    ax.axis("off")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ax.text(
        0.5, 0.97,
        "Heidstar 杂散光评估报告",
        ha="center", va="top", fontsize=20, fontweight="bold",
        transform=ax.transAxes,
    )
    ax.text(
        0.5, 0.93,
        f"v{__version__}  ·  生成时间  {now}",
        ha="center", va="top", fontsize=11, color="#555",
        transform=ax.transAxes,
    )

    ax.text(0.04, 0.88, f"暗场扫描根目录: {scan_root}",
            fontsize=10, transform=ax.transAxes)
    ax.text(0.04, 0.86, f"输出目录:       {output_dir}",
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

    headers = [
        "通道", "Fluo", "瓦片", "Sensor max",
        "Dark mean", "DC1 (%)", "DC2 (%)", "判定",
    ]
    rows = []
    for r in results:
        fluo = r.job.discovered.fluo_name or "—"
        m = r.metrics
        rows.append([
            r.job.display_name,
            fluo,
            str(r.num_images),
            f"{m.sensor_max:.0f}",
            f"{m.dark_mean:.2f}",
            f"{m.dc_pct_of_max:.4f}",
            f"{m.zone_dc_uniformity_pct:.2f}",
            _verdict_text(r.passed),
        ])

    table_ax = fig.add_axes([0.04, 0.30, 0.92, 0.45])
    table_ax.axis("off")
    table = table_ax.table(
        cellText=rows, colLabels=headers,
        loc="upper left", cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.7)

    # 染色：DC1 / DC2 / 判定列
    for i, r in enumerate(results, 1):
        cell = table[(i, len(headers) - 1)]
        cell.set_facecolor(_verdict_color(r.passed))
        cell.set_text_props(color="white", fontweight="bold")
        # DC1 列索引 = 5；DC2 列索引 = 6
        check_pass = [c.passed for c in r.verdict.checks]
        for col, ok in zip((5, 6), check_pass):
            c2 = table[(i, col)]
            c2.set_facecolor("#e8f4ec" if ok else "#fbe2e2")
    for j in range(len(headers)):
        table[(0, j)].set_facecolor("#dde4ea")
        table[(0, j)].set_text_props(fontweight="bold")

    ax.text(
        0.5, 0.04,
        "Heidstar Flat — 杂散光暗本底评估（关激发暗场图，2 项 AND 判定）",
        ha="center", va="bottom", fontsize=9, color="#888",
        transform=ax.transAxes,
    )

    return fig


# ---------- 每通道概览 ----------

def _build_overview(result):
    from matplotlib.figure import Figure

    fig = Figure(figsize=A4_PORTRAIT)
    gs = fig.add_gridspec(
        3, 2,
        height_ratios=[1.2, 4.5, 4.0],
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
        f"判定: 2 项 AND"
    )
    ax_hdr.text(
        0, 0.50, meta_line,
        fontsize=10, color="#444",
        transform=ax_hdr.transAxes,
    )

    if getattr(result, "verdict", None) and result.verdict.checks:
        bits = []
        for c in result.verdict.checks:
            mark = "OK" if c.passed else "NG"
            direction = getattr(c, "direction", "<=")
            op = "≤" if direction == "<=" else "≥"
            bits.append(
                f"[{mark}] {c.name} {c.value_pct:.4f}%{op}{c.threshold_pct:.4f}%"
            )
        ax_hdr.text(
            0, 0.10, "    ".join(bits),
            fontsize=9, color="#222",
            transform=ax_hdr.transAxes,
        )

    # —— 暗场均值热力图（带最亮像素位置标注）——
    ax_hm = fig.add_subplot(gs[1, 0])
    dark = result.dark_mean_image
    vmin = float(dark.min())
    vmax = float(max(dark.max(), vmin + 1e-6))
    im = ax_hm.imshow(
        dark, cmap="viridis", vmin=vmin, vmax=vmax,
        origin="upper", aspect="equal",
    )
    ax_hm.set_title("暗场均值", fontsize=12)
    ax_hm.set_xlabel("X (pixels)", fontsize=9)
    ax_hm.set_ylabel("Y (pixels)", fontsize=9)
    fig.colorbar(im, ax=ax_hm, fraction=0.046, pad=0.04, label="灰度值")
    mr, mc = result.metrics.max_pixel_position
    ax_hm.plot(mc, mr, "o", color="red", markersize=12, markeredgewidth=2.0,
               markerfacecolor="none", label=f"Max @ ({mr},{mc})")
    ax_hm.legend(loc="upper right", framealpha=0.85, fontsize=8)

    # —— 灰度分布直方图 ——
    ax_hist = fig.add_subplot(gs[1, 1])
    ax_hist.hist(
        dark.ravel(), bins=50, color="#3a6ea5", edgecolor="black", alpha=0.85,
    )
    ax_hist.set_title("灰度分布", fontsize=12)
    ax_hist.set_xlabel("灰度值", fontsize=9)
    ax_hist.set_ylabel("像素数", fontsize=9)
    ax_hist.grid(True, alpha=0.3)

    # —— 指标表 ——
    ax_met = fig.add_subplot(gs[2, 0])
    ax_met.axis("off")
    ax_met.set_title("杂散光指标", fontsize=12, loc="left", fontweight="bold")
    rows = result.metrics.as_table_rows()
    t1 = ax_met.table(
        cellText=rows, colLabels=["指标", "数值"],
        loc="upper left", cellLoc="left",
        colWidths=[0.55, 0.40],
    )
    t1.auto_set_font_size(False)
    t1.set_fontsize(9.0)
    t1.scale(1, 1.5)
    for j in (0, 1):
        t1[(0, j)].set_facecolor("#dde4ea")
        t1[(0, j)].set_text_props(fontweight="bold")
    # ★ 判定指标行（前两行）加粗
    for i in (1, 2):
        if i <= len(rows):
            for j in (0, 1):
                t1[(i, j)].set_text_props(fontweight="bold")

    # —— 9 区 mini 热力图 ——
    ax_nz = fig.add_subplot(gs[2, 1])
    ax_nz.set_title("9 区暗本底均值", fontsize=12, loc="left", fontweight="bold")
    zones = result.metrics.zone_dc
    zone_grid = np.asarray(zones).reshape(3, 3)
    ax_nz.imshow(zone_grid, cmap="viridis", vmin=vmin, vmax=vmax, aspect="auto")
    ax_nz.set_xticks([0, 1, 2])
    ax_nz.set_yticks([0, 1, 2])
    midpoint = (vmin + vmax) / 2
    for i in range(3):
        for j in range(3):
            v = float(zone_grid[i, j])
            ax_nz.text(
                j, i, f"{v:.2f}",
                ha="center", va="center",
                color="white" if v < midpoint else "black",
                fontsize=10,
            )

    return fig
