# Heidstar 多通道图像平场性检测

基于 PyQt5 + BaSiCPy 的图形化工具，用于一次性评估多个荧光波段
(默认 405 / 488 / 561 / 638 / 730 nm) 的照明平场均匀性。

支持 **Ubuntu 22.04** 与 **Windows 10/11** 双平台，源码运行。

## 主要功能

- 一键批量分析所有勾选通道，结果在多 Tab 中并排展示
- 每通道结果页：
  - 归一化平场热力图、强度分布直方图、中心十字断面
  - 均匀性指标：Min/Max/Mean/Std、Michelson 均匀性 (%)、CV 均匀性、中心/四角比、九区 ROI 表
  - 示例画廊：原图 / 校正后 / 差异 三联画
  - PASS / FAIL 徽章（按 Michelson 阈值判定，阈值可配）
- 通道、glob、阈值、示例数均可通过设置对话框持久化到用户配置目录
- 计算运行在 QThread 子线程，UI 不阻塞，可中途停止

## 输入约定

将待分析图像放在同一目录下，文件名形如：

```
current_<N>_0_Fluorescence_<wavelength>_nm_Ex.tiff
```

其中 `<wavelength>` 默认对应 `405 / 488 / 561 / 638 / 730`，每通道至少 2 张
(BaSiC 拟合需要)。所有图像须 dtype、尺寸一致。

也可在 *通道与阈值设置* 中修改任意通道的 glob 模式以适配其它命名。

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

1. 在“输入目录”选择含 TIFF 的目录；输出目录可留空，默认写入
   `<输入目录>/flatfield_results/flatfield_results_<波长>nm/`。
2. 左侧勾选要跑的通道，点击 **开始**。
3. 各通道结束后，对应 Tab 上的徽章会显示 PASS/FAIL，热力图、指标、画廊都会刷新。
4. 工具栏“通道与阈值设置”可调整每通道 glob、阈值与示例数；改动会保存到：
   - Linux/macOS: `~/.config/heidstar_flat/config.json`
   - Windows: `%APPDATA%\heidstar_flat\config.json`

## 输出文件

每个通道在输出目录下生成 `flatfield_results_<波长>nm/`，包含：

- `flatfield.tiff` / `flatfield.npy` — BaSiC 原始平场 (float32)
- `flatfield_normalized.tiff` — 归一化到 [0,1] 的平场

UI 中显示的热力图、指标、示例画廊均直接来自内存中的计算结果，
无需读盘。

## 项目结构

```
heidstar_flat/
├── app.py             # QApplication 入口
├── __main__.py        # python -m heidstar_flat
├── config.py          # 默认通道 / 阈值 / 配置持久化
├── worker.py          # QThread Worker，顺序处理多个通道
├── core/
│   ├── loader.py      # TIFF stack 加载
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

- 整个图像栈在内存中处理；4168×4168 × 7 张 uint16 占约 0.5 GB，BaSiC/JAX
  会再额外消耗若干倍 RAM。低内存机器建议减少单次勾选的通道数，或分批跑。
- BaSiCPy 没有暴露细粒度进度回调，因此“BaSiC 拟合”阶段进度条是不确定模式。
- 单 QThread 顺序处理，BaSiC 拟合期间停止按钮仅在通道之间生效。
