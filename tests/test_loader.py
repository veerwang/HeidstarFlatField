"""目录扫描 / 元数据解析单元测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from heidstar_flat.core.loader import (
    _extract_suffix,
    discover_channels,
    load_channel_tiles,
    parse_scan_txt,
)


# ---------------- _extract_suffix ----------------

def test_extract_suffix_basic():
    assert _extract_suffix("2026-05-19-092323_Blue") == "Blue"


def test_extract_suffix_multiple_underscores_takes_last_segment():
    assert _extract_suffix("prefix_with_many_underscores_Red") == "Red"


def test_extract_suffix_no_underscore_returns_none():
    assert _extract_suffix("nounderscore") is None


def test_extract_suffix_trailing_underscore_returns_empty():
    # 实际是 rsplit("_", 1)[-1]，末尾下划线后返回空串
    assert _extract_suffix("trailing_") == ""


# ---------------- parse_scan_txt ----------------

def test_parse_scan_txt_missing_returns_empty(tmp_path: Path):
    assert parse_scan_txt(tmp_path / "nonexistent.txt") == {}


def test_parse_scan_txt_basic_sections(tmp_path: Path):
    p = tmp_path / "Scan.txt"
    p.write_text(
        "[Fluo]\n"
        "Name=DAPI\n"
        "ColorDAPI=#0000ff\n"
        "ExpoTimeDAPI=13630\n"
        "\n"
        "[General]\n"
        "RowCount=12\n"
        "ColumnCount=14\n",
        encoding="utf-8",
    )
    meta = parse_scan_txt(p)
    assert meta["Fluo"]["Name"] == "DAPI"
    assert meta["Fluo"]["ColorDAPI"] == "#0000ff"
    assert meta["General"]["RowCount"] == "12"


def test_parse_scan_txt_ignores_non_kv_lines(tmp_path: Path):
    """不带 = 的行被忽略；section 前的内容也被忽略。"""
    p = tmp_path / "Scan.txt"
    p.write_text(
        "garbage line before any section\n"
        "[Fluo]\n"
        "ValidKey=1\n"
        "another garbage line\n",
        encoding="utf-8",
    )
    meta = parse_scan_txt(p)
    assert meta == {"Fluo": {"ValidKey": "1"}}


# ---------------- discover_channels ----------------

def _make_fake_channel(
    root: Path, suffix: str, num_tiles: int = 3,
    shape=(20, 20), dtype=np.uint8,
) -> Path:
    """在 root 下造一个 *_<suffix>/Images/IMG*.tif 的目录结构。"""
    ch_dir = root / f"2026-05-19-1_{suffix}"
    img_dir = ch_dir / "Images"
    img_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(hash(suffix) & 0xFFFFFFFF)
    for i in range(num_tiles):
        img = rng.integers(0, 100, size=shape, dtype=dtype)
        tifffile.imwrite(img_dir / f"IMG{i:03d}x{i:03d}.tif", img)
    return ch_dir


def test_discover_channels_basic(tmp_path: Path):
    _make_fake_channel(tmp_path, "Blue", num_tiles=3)
    _make_fake_channel(tmp_path, "Green", num_tiles=4)
    channels = discover_channels(tmp_path)
    assert len(channels) == 2
    suffixes = {c.suffix for c in channels}
    assert suffixes == {"Blue", "Green"}


def test_discover_channels_skips_unmatched_dirs(tmp_path: Path):
    _make_fake_channel(tmp_path, "Blue")
    # 无 Images 子目录
    (tmp_path / "garbage").mkdir()
    # 无下划线
    (tmp_path / "nounderscore").mkdir()
    (tmp_path / "nounderscore" / "Images").mkdir()
    channels = discover_channels(tmp_path)
    assert [c.suffix for c in channels] == ["Blue"]


def test_discover_channels_whitelist(tmp_path: Path):
    _make_fake_channel(tmp_path, "Blue")
    _make_fake_channel(tmp_path, "Green")
    _make_fake_channel(tmp_path, "Red")
    channels = discover_channels(tmp_path, suffix_whitelist=["Blue", "Red"])
    suffixes = {c.suffix for c in channels}
    assert suffixes == {"Blue", "Red"}


def test_discover_channels_invalid_root_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="不存在"):
        discover_channels(tmp_path / "nonexistent")


# ---------------- load_channel_tiles ----------------

def test_load_channel_tiles_parallel_keeps_order(tmp_path: Path):
    """线程池并发加载后 stack 顺序与文件名排序一致。"""
    ch_dir = _make_fake_channel(tmp_path, "Blue", num_tiles=10, shape=(50, 50))
    channels = discover_channels(tmp_path)
    assert len(channels) == 1

    stack, names = load_channel_tiles(channels[0])
    assert stack.shape == (10, 50, 50)
    assert names == sorted(names)
    # 验证每个槽位的内容确实是按文件名排序的对应文件（不被并发打乱）
    for i, name in enumerate(names):
        expected = tifffile.imread(ch_dir / "Images" / name)
        assert np.array_equal(stack[i], expected)


def test_load_channel_tiles_dtype_mismatch_raises(tmp_path: Path):
    """同通道下两张瓦片 dtype 不一致应该抛错（线程池里某个 worker 抛）。"""
    ch_dir = _make_fake_channel(tmp_path, "Blue", num_tiles=3, shape=(20, 20),
                                 dtype=np.uint8)
    # 替换其中一张为 uint16
    bad = (tmp_path / "2026-05-19-1_Blue" / "Images" / "IMG001x001.tif")
    tifffile.imwrite(bad, np.zeros((20, 20), dtype=np.uint16))
    channels = discover_channels(tmp_path)
    with pytest.raises(ValueError, match="dtype"):
        load_channel_tiles(channels[0])
