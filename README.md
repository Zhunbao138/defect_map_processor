# 缺陷图谱处理系统 (Defect Map Processor)

> 一站式处理钢板缺陷图谱 Excel 表：自动提取图片、切分三视图、OCR 识别参数、Web 展示与编辑。

---

## 🚀 快速上手 (3 分钟)

### 1. 准备环境

需要 **Python 3.10+**，推荐使用虚拟环境：

```bash
# 克隆仓库
git clone <你的仓库地址>
cd defect_map_processor

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

> 首次运行 OCR 还会自动下载约 100MB 的 EasyOCR 模型文件，请保持网络畅通。

### 2. 处理一个 Excel 文件 (最快 1 行命令)

仓库已经附带 `input/sample.xlsx` 和 `output/` 下的处理结果。**如果你想直接看效果**：

```bash
# 启动 Web 服务，浏览器打开 http://127.0.0.1:5000
python cli.py serve

# 或者命令行处理自己的文件
python cli.py process input/sample.xlsx --gpu
```

处理完成后输出在 `output/<task_id>/` 目录：

```
output/
└── 60607613/
    ├── defect_records.json   ← 整合后的所有数据 (74 条)
    ├── defect_records.xlsx   ← 同上 Excel 格式
    ├── images/               ← 150 张原图 (1920×1080)
    ├── views/                ← 切分的三视图
    │   └── row007_缺陷图谱_1/
    │       ├── row007_缺陷图谱_1_1_top.png     ← 俯视图
    │       ├── row007_缺陷图谱_1_2_long.png    ← 长边侧视图
    │       ├── row007_缺陷图谱_1_3_short.png   ← 短边侧视图
    │       └── row007_缺陷图谱_1_annotated.png ← 标注预览
    └── ocr_debug/            ← OCR 调试图片
```

### 3. 打开 Web 界面

```bash
python cli.py serve
# → http://127.0.0.1:5000
```

界面功能：
- 📁 **上传区**：拖拽 .xls/.xlsx 文件
- ⏳ **进度区**：实时显示处理阶段 (导入/提取/切图/OCR/数据库)
- 📊 **结果区**：所有缺陷记录卡片，每条含钢种、类别、原图、三视图、OCR 参数
- ✏️ **编辑**：点 "✏️ 编辑" 可手动修改 OCR 识别错的缺陷参数 (实时保存到 JSON)

---

## 📋 处理流程

```
.xlsx 上传
   ↓
[importer] 读取 sheet2 文字数据 (排除示意行, 只保留 1~74 号真实记录)
   ↓
[image_extractor] 提取"缺陷图谱"列所有图片 (原图直存, md5 一致)
   ↓
[view_splitter] 每张图切分为三视图 (俯视图/长边/短边)
   ↓
[ocr_extractor] 跑两次 OCR:
   1) 1_top 切图 → 拿缺陷中心X/Y、长度、宽度、深度
   2) 原图顶部 → 拿钢板号、材料尺寸
   ↓
[data_merger] 按 row_index 合并 → JSON + Excel + SQLite
   ↓
[Flask Web] 展示 + 编辑
```

---

## 🛠️ 详细使用

### CLI 模式

```bash
# 基本处理
python cli.py process input.xlsx

# 指定输出目录
python cli.py process input.xls -o ./my_output

# 跳过 OCR (快很多, 适合不需要缺陷参数)
python cli.py process input.xlsx --no-ocr

# 跳过三视图切分
python cli.py process input.xlsx --no-split

# GPU 加速 OCR (强烈推荐, 30x 提速)
python cli.py process input.xlsx --gpu

# 自定义 OCR 语言
python cli.py process input.xlsx --lang en,ch_sim
```

### Web 服务

```bash
# 默认 http://127.0.0.1:5000
python cli.py serve

# 自定义端口
python cli.py serve --port 8080

# 允许外部访问 (局域网共享)
python cli.py serve --host 0.0.0.0 --port 8080
```

### Python API

```python
from core.pipeline import run_pipeline

def progress(stage, percent, message):
    print(f"[{stage}] {percent*100:.0f}% - {message}")

result = run_pipeline(
    file_path="input/sample.xlsx",
    output_dir="output",
    enable_ocr=True,
    enable_split=True,
    ocr_gpu=True,                    # 强烈推荐 GPU
    progress_callback=progress,
)

print(f"成功: {result.success}")
print(f"记录: {result.stats['records_count']}")
print(f"图片: {result.stats['images_count']}")
print(f"JSON: {result.json_path}")
```

---

## 📁 项目结构

```
defect_map_processor/
├── cli.py                   # 命令行入口
├── app.py                   # Flask Web 应用
├── requirements.txt         # Python 依赖
├── README.md
├── .gitignore
├── core/                    # 核心处理模块
│   ├── importer.py          # xls/xlsx 导入 + 示意行过滤
│   ├── image_extractor.py   # 图片原图直存提取
│   ├── view_splitter.py     # 三视图切分 (黑底矩形检测)
│   ├── ocr_extractor.py     # OCR + 自动定位黑底白字方块
│   ├── data_merger.py       # 数据合并 + JSON/Excel 输出
│   ├── image_matcher.py     # 图片-记录关联
│   ├── database.py          # SQLite 持久化
│   └── pipeline.py          # 主流水线
├── templates/
│   └── index.html           # Web 页面
├── static/
│   ├── app.js               # 前端逻辑 (含编辑功能)
│   └── style.css
├── input/                   # 放待处理 xlsx
│   └── sample.xlsx          # 示例
└── output/                  # 处理结果
    └── <task_id>/
        ├── defect_records.json
        ├── defect_records.xlsx
        ├── images/           # 原图
        ├── views/            # 切分的三视图
        └── ocr_debug/        # OCR 调试
```

---

## 📊 数据格式

### `defect_records.json` 每条记录

```json
{
  "row_index": 7,
  "序号": "1",
  "生产厂": "中板厂",
  "钢板号": "26102421340201",
  "钢种": "JX22145-2025 X60MS",
  "类别": "管线",
  "缺陷分析": "显孔",
  "图-1": "output/.../row007_缺陷图谱_1.png",
  "图-2": "output/.../row007_缺陷图谱_2.png",
  "俯视图-1": "output/.../row007_缺陷图谱_1_1_top.png",
  "长边方向侧视图-1": "output/.../row007_缺陷图谱_1_2_long.png",
  "短边方向侧视图-1": "output/.../row007_缺陷图谱_1_3_short.png",
  "缺陷数据": {
    "钢板号": "26102421340201",
    "材料尺寸": "12000×2430×30",
    "缺陷中心X": "8412",
    "缺陷中心Y": "1839",
    "缺陷长度": "1669.4",
    "缺陷宽度": "162.6",
    "缺陷深度": "14.3"
  }
}
```

### 输入 Excel 格式 (sheet2)

| 列 | 字段 | 示例 |
|----|------|------|
| 1 | 序号 | 1, 2, 3, ... |
| 2 | 生产厂 | 中板厂 |
| 3 | 钢板号 | 26102421340201 |
| 4 | 钢种 | JX22145-2025 X60MS |
| 5 | 类别 | 管线 / 容器 / 船板 |
| 6 | **缺陷图谱** | (嵌入图片, F 列, 每行 2 张) |
| 7 | 缺陷照片 | (可选) |
| 8 | 缺陷分析 | 显孔 / 中心裂纹 |

> 表格前 6 行是表头/负责人/要求/示意，**会自动跳过**，只处理 1~74 号真实数据。

---

## 🔧 进阶

### 调整 OCR 识别字段

`core/ocr_extractor.py` 中的 `PARAM_PATTERNS` 定义要提取的字段正则：

```python
PARAM_PATTERNS = [
    ("钢板号", r"(\d{14})"),
    ("材料尺寸", r"(\d{3,6})\s*[×xX\*·]\s*(\d{3,6})\s*[×xX\*·]\s*(\d+(?:\.\d+)?)"),
    # ... 缺陷中心X/Y, 长度/宽度/深度
]
```

### 调整三视图切分

`core/view_splitter.py` 复用了 `extract_black_border.py` 的算法：
- `threshold=100`：黑色边框提取阈值
- `w*h >= 10000`：最小矩形面积
- 俯视图 = 最上方最大的矩形

### 持久化到数据库

所有数据自动存入 `data/defect_map.db` (SQLite)：

```python
import sqlite3
c = sqlite3.connect('data/defect_map.db').cursor()
for r in c.execute('SELECT 钢板号, 钢种 FROM records LIMIT 5'):
    print(r)
```

---

## ❓ 常见问题

### Q: OCR 识别率低？
- 必开 GPU：`--gpu` (CPU 跑要 2 分钟, GPU 30 秒)
- OCR 对小字+反相图易失败，可手动在 Web 界面"编辑"修改

### Q: xls 格式图片提取不到？
xls 是 OLE2 格式，图片关联信息不在 BIFF 流中。**推荐先在 WPS 中另存为 xlsx 再处理**。

### Q: 端口被占用？
```bash
python cli.py serve --port 8080
```

### Q: 处理中断了？
后台任务数据在内存里会丢，磁盘上的 `output/<task_id>/` 还在。重启服务后会从磁盘重建任务列表。

---

## 📜 许可证

MIT License — 内部工具，自由使用修改。

## 🙏 致谢

- [EasyOCR](https://github.com/JaidedAI/EasyOCR) — 友好的多语言 OCR
- [OpenCV](https://opencv.org/) — 图像处理基础
- [Flask](https://flask.palletsprojects.com/) — Web 框架
