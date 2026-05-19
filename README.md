# Heidstar 多通道图像平场性检测

基于 PyQt5 + BaSiCPy 的图形化工具，用于一次性评估多个荧光通道
(默认 7 色：Blue / Cyan / Green / Yellow / Orange / Red / Purple) 的
照明平场均匀性。

支持 **Ubuntu 22.04** 与 **Windows 10/11** 双平台，源码运行。

## 主要功能

- 选定扫描根目录后**自动发现**子目录中的所有通道（按 `*_<Color>/` 命名）
- 每通道页头部展示 Scan.txt 元数据：荧光名 (DAPI/PVB480/…)、颜色色块、曝光、增益、瓦片数、网格、位深
- 每通道结果页：
  - 归一化平场热力图 + 强度分布直方图 + 中心十字断面
  - 均匀性指标：Min/Max/Mean/Std、★ Min/Max ratio (判定指标)、Michelson 均匀性、CV 均匀性、中心/四角比、九区 ROI 表
  - 示例画廊：原图 / 校正后 / 差异 三联画
  - PASS / FAIL 徽章（按 **Min/Max ratio** 阈值判定，每通道阈值可配并持久化）
- 计算运行在 QThread 子线程，UI 不阻塞，可中途停止
- **导出 PDF 报告**：一键生成包含封面汇总表 + 每通道概览页 + 全部示例三联画的整合 PDF

## 数据约定

入口选择**扫描根目录**（一般是一次扫描的日期目录，例如 `data/0519`），
其下每个直接子目录代表一个通道，目录名结尾 `_<Suffix>` 决定通道身份：

```
<扫描根目录>/
├── 2026-05-19-092323_Blue/
│   ├── Images/IMG{row:03d}x{col:03d}.tif   ★ 真正用于拟合的瓦片
│   ├── Scan.txt                            ★ 元数据 (Fluo 名、颜色、曝光、增益、网格)
│   ├── Result-*.tif / Preview-*.tif / Focus-*.tif / Thumbs/   忽略
├── 2026-05-19-092323_Cyan/
├── … (Green / Yellow / Orange / Red / Purple)
```

约定：

- 程序按目录名最后一个下划线后的内容作为 **suffix**（Blue / Cyan / …），并以此匹配阈值偏好。
- 同通道所有瓦片必须 dtype、尺寸一致；网格大小无要求，BaSiC 拟合需要至少 ~2 张。
- 任何未识别 suffix 的子目录会被跳过；未在偏好中的 suffix 走全局默认阈值。
- 默认瓦片子目录是 `Images/`、文件 glob 是 `IMG*.tif`，可在「通道偏好与设置」中改。

## 安装

### 通用步骤

```bash
python3 -m venv .venv
# Ubuntu / macOS
source .venv/bin/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt
```

### Ubuntu 22.04 特别说明

- 若启动时报 `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`，
  安装一次系统库即可：

  ```bash
  sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0
  ```

- BaSiCPy 默认通过 JAX 调度计算。无 NVIDIA GPU / 驱动时会自动回落到 CPU，
  日志会打印 `An NVIDIA GPU may be present ... Falling back to cpu`，
  这是预期行为。

### Windows 10/11 特别说明

- 推荐使用 Python 3.10 或 3.11。
- BaSiCPy 在 Windows 上依赖 CPU 版 `jaxlib`。`pip install basicpy` 通常会
  自动拉到合适的 wheel；若失败，按 [JAX 官方安装文档](https://github.com/google/jax#installation)
  手动指定 CPU wheel。
- PyQt5 wheel 自带平台插件，一般无需额外配置。

## 运行

```bash
python run.py
# 或
python -m heidstar_flat
```

1. 选择「扫描根目录」（如 `data/0519`），程序自动扫描并填充所有发现的通道 Tab。
2. 左侧勾选要跑的通道，点击 **开始**；输出目录留空时默认写入
   `<扫描根目录>/flatfield_results/flatfield_results_<suffix>/`。
3. 各通道结束后，对应 Tab 上的徽章会显示 PASS/FAIL，热力图、指标、画廊都会刷新。
4. 工具栏「通道偏好与设置」可调整每通道 suffix/显示名/阈值、默认阈值、瓦片子目录与 glob、示例数；改动会保存到：
   - Linux/macOS: `~/.config/heidstar_flat/config.json`
   - Windows: `%APPDATA%\heidstar_flat\config.json`

## 输出文件

每个通道在输出目录下生成 `flatfield_results_<suffix>/`，包含：

- `flatfield.tiff` / `flatfield.npy` — BaSiC 原始平场 (float32)
- `flatfield_normalized.tiff` — 归一化到 [0,1] 的平场

UI 中显示的热力图、指标、示例画廊均直接来自内存中的计算结果，
无需读盘。

## 项目结构

```
heidstar_flat/
├── app.py             # QApplication 入口
├── __main__.py        # python -m heidstar_flat
├── config.py          # 通道偏好 / 阈值 / 配置持久化
├── worker.py          # QThread Worker，顺序处理多个通道
├── core/
│   ├── loader.py      # Scan.txt 解析 + 通道发现 + 瓦片加载
│   ├── flatfield.py   # BaSiCPy 薄封装
│   └── metrics.py     # 均匀性指标 + 示例生成
└── ui/
    ├── main_window.py
    ├── channel_tab.py
    ├── mpl_canvas.py
    ├── metrics_table.py
    ├── gallery.py
    └── settings_dialog.py
```

## 已知限制

- 整个瓦片栈在内存中处理；24 张 3000×2656 uint8 ≈ 191 MB，BaSiC/JAX
  会再额外消耗若干倍 RAM。低内存机器建议减少单次勾选的通道数，或分批跑。
- BaSiCPy 没有暴露细粒度进度回调，因此「BaSiC 拟合」阶段进度条是不确定模式。
- 单 QThread 顺序处理，BaSiC 拟合期间停止按钮仅在通道之间生效。
