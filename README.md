# Heidstar 多通道图像平场性 / 杂散光检测

基于 PyQt5 + BaSiCPy 的图形化工具，一次性评估多荧光通道
(默认 7 色：Blue / Cyan / Green / Yellow / Orange / Red / Purple) 的
两套 QC 指标：

- **平场均匀性**（7 项 AND 判定）—— 照明 / 光路的不均匀性是否在可接受范围
- **杂散光**（5 项 AND 判定）—— 关激发暗场下相机本底 / DSNU / 时间噪声 / 热像素是否在规格内

支持 **Ubuntu 22.04** 与 **Windows 10/11** 双平台，源码运行。

> **判据详解**：每项指标的公式、物理含义、通俗解释和默认阈值见 [`CRITERIA.md`](CRITERIA.md)；
> 也可以在 GUI 工具栏点「判据说明」（或按 **F1**）直接打开预生成的 [`docs/CRITERIA.pdf`](docs/CRITERIA.pdf)。

## 主要功能

GUI 顶部两个 Tab，**两套流程完全独立、各自选目录各自跑**：

### 平场检测 Tab
- 自动发现 `*_<Color>/` 子目录中的所有通道
- 每通道页：归一化平场热力图（标 Min/Max 位置）+ 强度直方图 + 中心十字断面 + 原图/校正/差异三联画
- 均匀性指标表（15 行）+ 9 区 ROI 表 + 状态徽章
- **7 项 AND 判定**：稳健 Min/Max、CV 均匀性、九区四角对称、九区中心最亮、九区最暗格、九区粗糙度、顶端饱和率（反作弊）
- 每通道阈值差异化（Yellow/Orange 暗角天然重，阈值更宽松；Purple 反而最均匀，阈值最严）
- **一键导出 PDF**：封面汇总 + 每通道概览 + 全部示例三联画

### 杂散光检测 Tab
- 同样的自动通道发现，但输入的是**关激发暗场图**（与正常扫描相同曝光/增益拍摄）
- 每通道页：暗场均值热力图（标最亮像素位置）+ 灰度分布 + 9 区 mini 热力图 + 杂散光指标表
- **5 项 AND 判定**：
  - DC1 本底强度（dark_mean / sensor_max）
  - DC2 本底空间均匀性（9 区 CV）
  - DC3 DSNU 像素级（EMVA 1288 风格）
  - DC4 时间噪声底（σ_temporal）
  - DC5 热像素密度
- 独立 PDF 报告（封面 9 列汇总 + 每通道单页）

### 通用功能
- 计算运行在独立 QThread，UI 不阻塞；中途可停止
- 异步扫描：大目录 / 网络盘不卡 UI
- 瓦片并行加载（ThreadPoolExecutor），24 张 SSD 上比串行快 3-5×
- 通道列表「全选 / 全不选」一键勾选
- 日志独立对话框（**Ctrl+L** 打开）
- 关窗保护：Yes 等待 / No 强退 / Cancel 不退，最多等 10 分钟覆盖 BaSiC 首次 JAX 编译

## 数据约定

GUI 入口选**扫描根目录**（一般是一次扫描的日期目录，例如 `data/0519`），
其下每个直接子目录代表一个通道，目录名结尾 `_<Suffix>` 决定通道身份：

```
<扫描根目录>/
├── 2026-05-19-092323_Blue/
│   ├── Images/IMG{row:03d}x{col:03d}.tif   ★ 真正用于计算的瓦片
│   ├── Scan.txt                            ★ 元数据 (Fluo 名、颜色、曝光、增益、网格)
│   ├── Result-*.tif / Preview-*.tif / Focus-*.tif / Thumbs/   忽略
├── 2026-05-19-092323_Cyan/
├── … (Green / Yellow / Orange / Red / Purple)
```

平场检测和杂散光检测共用相同的目录结构，**只是输入两个不同的根目录**（前者是样品扫描，后者是关激发暗场扫描）。

约定：

- 程序按目录名最后一个下划线后的内容作为 **suffix**（Blue / Cyan / …），并以此匹配阈值偏好。
- 同通道所有瓦片必须 dtype、尺寸一致；瓦片数建议 ≥ 4（中值/方差类指标需要多张才稳定）。
- 任何未识别 suffix 的子目录会被跳过；未在偏好中的 suffix 走全局默认阈值。
- 默认瓦片子目录是 `Images/`、文件 glob 是 `IMG*.tif`，可在「通道偏好与设置」中改。

## 安装

### 通用步骤（Linux / macOS）

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### Ubuntu 22.04 特别说明

- 若启动时报 `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`，
  安装一次系统库：

  ```bash
  sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0
  ```

- 中文字体（matplotlib 标签、PDF 报告）：

  ```bash
  sudo apt install fonts-noto-cjk
  ```

- BaSiCPy 默认通过 JAX 调度计算。无 NVIDIA GPU / 驱动时会自动回落到 CPU，
  日志会打印 `An NVIDIA GPU may be present ... Falling back to cpu`，
  这是预期行为。

### Windows 10/11

**一键启动（推荐）**：双击 `run-windows.bat`。该脚本会：

1. 检测 conda（PATH 优先，否则查 `%UserProfile%\Miniconda3`）；找不到时**提示 Y/N 自动下载 + 静默安装 Miniconda**（per-user、无需管理员、不改 PATH）
2. 用 `conda-forge --override-channels` 创建 `heidstar_flat` 环境（Python 3.11 + pip），绕开 Anaconda 默认频道的 ToS
3. 依赖检查改为 `import` 验证；半成品环境会自动补装
4. 启动 GUI

如果半成品 env 卡住，跑 `reset-env.bat`（同目录）强删后重来。

**手动安装**：与 Linux 步骤相同，推荐 Python 3.10 或 3.11。

## 运行

```bash
python run.py
# 或
python -m heidstar_flat
```

### 平场检测流程

1. 顶部切到「**平场检测**」Tab
2. 选择「扫描根目录」（如 `data/0519`），自动扫描填充所有通道 Tab
3. 左侧勾选要跑的通道（或点「全选」），点 **开始**；输出目录留空时默认写入 `<扫描根目录>/flatfield_results/flatfield_results_<suffix>/`
4. 各通道结束后徽章显示 PASS/FAIL，热力图、指标、画廊都会刷新
5. 点「**导出 PDF 报告**」生成完整报告

### 杂散光检测流程

1. 顶部切到「**杂散光检测**」Tab
2. 选择「**暗场扫描根目录**」（与平场不同，必须是关激发拍的暗场扫描）
3. 同样的扫描 → 勾选 → 开始 → 看徽章 → 导出 PDF
4. 与平场互不干扰，可同时跑（两个独立 QThread）

### 通道偏好与设置

工具栏「**通道偏好与设置**」打开对话框，可调：

- 全局参数：示例数、输出子目录、瓦片目录、glob 模式
- 平场判据阈值（7 项 AND）
- 杂散光判据阈值（5 项 AND）
- 每通道 suffix / 显示名 / Min/Max 阈值表

改动保存到：

- Linux/macOS: `~/.config/heidstar_flat/config.json`
- Windows: `%APPDATA%\heidstar_flat\config.json`

### 查看判据详解

工具栏「**判据说明**」（或按 **F1**）→ 系统默认 PDF 阅读器打开 [`docs/CRITERIA.pdf`](docs/CRITERIA.pdf)。
该 PDF 从 [`CRITERIA.md`](CRITERIA.md) 构建生成，修改 markdown 后重新生成：

```bash
pip install markdown weasyprint
python scripts/build_criteria_pdf.py
```

## 输出文件

### 平场检测
每通道输出目录下生成 `flatfield_results_<suffix>/`，包含：
- `flatfield.tiff` / `flatfield.npy` — BaSiC 原始平场 (float32)
- `flatfield_normalized.tiff` — 归一化到 [0,1] 的平场

### 杂散光检测
每通道输出目录下生成 `stray_results_<suffix>/`，包含：
- `dark_mean.tiff` — N 张暗场瓦片的均值图 (float32)

UI 中显示的热力图、指标均来自内存中的计算结果，无需读盘。

> **TIFF 提示**：这些都是 float32 TIFF，Windows 资源管理器 / 画图打开看不到内容（不支持 float）。用 ImageJ / Fiji 或 Python 的 matplotlib 才能正常显示。

## 项目结构

```
heidstar_flat/
├── app.py                # QApplication 入口
├── __main__.py           # python -m heidstar_flat
├── __init__.py           # __version__
├── config.py             # 配置 / 阈值 / 通道偏好持久化
├── worker.py             # 平场 QThread Worker
├── stray_worker.py       # 杂散光 QThread Worker
├── core/
│   ├── loader.py         # Scan.txt 解析 + 通道发现 + 瓦片并行加载
│   ├── flatfield.py      # BaSiCPy 薄封装
│   ├── metrics.py        # 平场 7 项判定 + 9 区 ROI + 示例生成
│   ├── stray_light.py    # 杂散光 5 项判定
│   ├── report.py         # 平场 PDF 报告
│   └── stray_report.py   # 杂散光 PDF 报告
└── ui/
    ├── main_window.py        # 顶级 Tab 容器 + 工具栏 + 日志
    ├── flatfield_panel.py    # 平场检测面板
    ├── stray_light_panel.py  # 杂散光检测面板
    ├── channel_tab.py        # 平场单通道页（含 VerdictBadge / ColorSwatch）
    ├── stray_channel_tab.py  # 杂散光单通道页
    ├── mpl_canvas.py         # matplotlib Qt 画布封装
    ├── metrics_table.py
    ├── gallery.py
    ├── log_dialog.py         # 独立日志对话框
    └── settings_dialog.py    # 设置对话框

docs/
└── CRITERIA.pdf              # 判据详解（从 CRITERIA.md 生成）

scripts/
└── build_criteria_pdf.py     # CRITERIA.md → PDF 构建脚本

run-windows.bat               # Windows 一键启动（含 Miniconda 自动安装）
reset-env.bat                 # Windows env 故障重置
```

## 已知限制

- 整个瓦片栈在内存中处理；24 张 3000×2656 uint8 ≈ 191 MB，BaSiC/JAX 还会再吃数倍 RAM。
  低内存机器建议减少单次勾选的通道数，或分批跑。`load_channel_tiles` 在 OOM 时会
  给出带"瓦片数 / 形状 / dtype / 估算 MB"的明确错误提示。
- BaSiCPy 没有暴露细粒度进度回调，所以「BaSiC 拟合」阶段进度条是不确定模式。
- 杂散光评估的鬼影 / 通道间串扰矩阵需要专门的采集协议（点光源 / 轮流单通道激发），
  当前版本不实现。详见 `CRITERIA.md` Part B.8。
- 关窗时若 worker 正在跑，最多等 10 分钟（覆盖 BaSiC 首次 JAX 编译）；
  超时后强退仍可能让 Qt 警告 thread 未正常退出，但已通过 blockSignals 避免崩溃。
