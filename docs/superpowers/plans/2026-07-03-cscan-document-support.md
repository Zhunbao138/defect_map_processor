# 中厚板卷厂 (cscan) 文档支持 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有"中板厂 (zhongban)" 文档流程之外,新增"中厚板卷厂 (cscan)" 文档的并行处理流程。本步骤只做"图像识别文字"和"原图提取",不做切图、不做 xlsx 导出。

**Architecture:** 在 `core/pipeline.py` 加 `task_type` 分支,新模块 `core/cscan_ocr.py` 负责从 F/G 列提取原图 + 跑 Tesseract 识别左上角 13 列缺陷表格 + 试样大小信息。新模块 `core/cscan_merger.py` 打包 schema 并写入新表 `cscan_records`。前端加文档类型选择,Web 页面分标签显示两种数据。

**Tech Stack:** Python (openpyxl + pytesseract + PIL), HTML/CSS/JS。沿用现有依赖,不加新包。

## Global Constraints

- 不动现有"中板厂"流程。所有 `zhongban` 相关文件保持向后兼容
- `task_type` 字段默认 `"zhongban"`,缺失时按 zhongban 处理
- `cscan` 流程: **不** 调现有 `ocr_extractor` 切图后的部分. **会** 调 `view_splitter` 但输出标签改为 table + ascan + cscan (复用同一个矩形检测算法, 仅命名变化)
- **cscan 类型切图**: 中板厂切图后是 5 张 (原图×2 + 俯/长/短), cscan 切图后是 6 张子图 (F 切 3 张: table/ascan/cscan + G 切 3 张同样)
- OCR 仍用 Tesseract,不支持 GPU
- 数据库: 新表 `cscan_records` 与 `records` 并列
- A 扫 / C 扫 / 表格的命名: F 列和 G 列都有 3 个子图, 命名带 F/G 前缀区分
- 实施时需用样本二次确认 view_splitter 找出的 3 个矩形确实对应 [table, ascan, cscan] (Task 1.4)

## Sample file structure (来自实测)

```
input/2026-4月30日-5月7日 国家项目数据采集日常工作搜集表（中厚板卷厂）1_xxx.xlsx
  - size: 18 MB
  - sheets: 2
    - 'Shee1' (0): 4 rows × 10 cols, 19 张图 (row 2-3, col B-E) — 钢材类型示例图
    - '5.1'   (1): 68 rows × 13 cols, 86 张图 — 真实数据
  - '5.1' 关键布局:
    - row 1: 标题
    - row 2: 表头 (序号/生产厂/钢板号/钢种/类别/缺陷图谱/缺陷照片/缺陷分析)
    - row 3-4: 负责单位 / 要求
    - row 5: 示意行
    - row 7+: 真实数据 (序号 1, 2, 3...)
  - 图片布局 (用户原话: "左上是个表格, 右上是 a 扫, 下面是 c 扫"):
    - F 列 (col=5, 0-based): 1 张原图, 内部含 3 个区域 — 左上: 13 列缺陷表格, 右上: A 扫, 下面: C 扫
    - G 列 (col=6, 0-based): 1 张原图, 内部含 3 个区域 — 同上布局
  - **切图 + OCR (本步核心)**:
    - view_splitter 已经能找出 3 个黑色矩形 (top/short/long). 复用算法, 但标签改为 `table` / `ascan` / `cscan`
    - `table` (top 区域, 1_top): 跑 Tesseract 识别 13 列缺陷表格, 正则提取 `序号|X起始|X终止|...|幅值`
    - `ascan` (right 区域, 3_short): 直接保存为子图
    - `cscan` (bottom 区域, 2_long): 直接保存为子图
  - **保存约定** (每行 6 张子图):
    - F 切出 → `F_table-{row:03d}.png`, `F_ascan-{row:03d}.png`, `F_cscan-{row:03d}.png`
    - G 切出 → `G_table-{row:03d}.png`, `G_ascan-{row:03d}.png`, `G_cscan-{row:03d}.png`
  - **已有 view_splitter 适配 (Task 1.1)**: 加新函数 `detect_and_crop_cscan_views` 或加 `mode="cscan"` 参数, 输出 `table/ascan/cscan` 而非 `top/long/short`
```

## File Structure

| 文件 | 改动 | 职责 |
|---|---|---|
| `core/cscan_ocr.py` | 新建 | 提取 C 扫/A 扫原图 + 跑 OCR 识别试样大小 |
| `core/cscan_merger.py` | 新建 | 打包 cscan schema + 存 DB 新表 |
| `core/pipeline.py` | 改 | 加 `task_type` / `cscan_ocr` / `cscan_merger` 分支调用 |
| `core/database.py` | 改 | 加 `cscan_records` 表 |
| `app.py` | 改 | 加 `task_type` 接收 + 路由按 type 区分返回 |
| `cli.py` | 改 | 加 `--type` 参数 |
| `templates/index.html` | 改 | 加"文档类型"radio + cscan 表格/图区 |
| `static/app.js` | 改 | 加 cscan 渲染函数 + 任务类型识别 |
| `static/style.css` | 改 | 加 cscan 表格样式 |

## Task 1: 新增 `core/cscan_ocr.py`

**Files:** Create `core/cscan_ocr.py`

**接口:**
- `split_cscan_views(image_path, output_dir) -> dict` — 调 `view_splitter` 切出 3 个子图, 标签为 `table` (top), `ascan` (right), `cscan` (bottom). 返回 `{table: Path, ascan: Path, cscan: Path}`
- `extract_cscan_from_xlsx(ws, output_dir) -> dict[int, dict]` — 遍历 `ws._images` F/G 列, 调 `split_cscan_views` 切每张, 返回 `{row_idx: {"F_table": Path, "F_ascan": Path, "F_cscan": Path, "G_table": Path, "G_ascan": Path, "G_cscan": Path}}`
- `ocr_defect_table(table_image_path) -> list[dict]` — 跑 Tesseract 识别 13 列缺陷表格, 返回 `[{"序号": 18, "X起始": 868.0, ..., "幅值": 100.0}, ...]`
- `extract_sample_size(image_path) -> str | None` — 从图顶部识别试样大小 "12000×2430×30" 格式

**Steps:**

- [ ] **Step 1.0**: 扩展 `core/view_splitter.py` 加新函数 `detect_and_crop_cscan_views(image_path, output_dir)`: 复用现有矩形检测算法, 输出 `{"table": Path, "ascan": Path, "cscan": Path}` 替代原来的 `{"1-俯视图": ..., "2-长边侧视图": ..., "3-短边侧视图": ...}`. 不动原函数 (向后兼容)

- [ ] **Step 1.1**: 写 `split_cscan_views` (在 `cscan_ocr.py` 里) 调用 `detect_and_crop_cscan_views`, 文件名加 F/G 前缀: `F_table-{row:03d}.png`, `F_ascan-{row:03d}.png`, `F_cscan-{row:03d}.png`, 同理 G

- [ ] **Step 1.2**: 写 `extract_cscan_from_xlsx`: 遍历 `ws._images`, 取 F (col=5) 和 G (col=6) 锚点, row 排序, 调 `split_cscan_views` 处理每张

- [ ] **Step 1.3**: 写 `ocr_defect_table`: 对切出的 `table` 子图跑 pytesseract, 识别 13 列 (序号/X起始/X终止/X中点/X长度/Y起始/Y终止/Y中点/Y长度/面积/类型/深度/幅值). 返回 list[dict]

- [ ] **Step 1.4**: 写 `extract_sample_size`: 从图顶部切一条带状区域 (高度 ~40px), pytesseract 跑 `image_to_string`, 正则匹配 `(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)`, 返回 `f"{w}×{h}×{t}"` 格式

- [ ] **Step 1.5**: 单元测试: 对样本 `input/..._20260702_155121.xlsx` 跑一次, 确认能从 5.1 提取 6×N 张子图, OCR 表格得到 ≥1 行, 试样大小能识别

## Task 2: 新增 `core/cscan_merger.py`

**Files:** Create `core/cscan_merger.py`

**接口:**
- `merge_cscan_records(rows: list[dict], image_map: dict, sample_sizes: dict) -> list[dict]`
- `save_json(records, output_dir) -> Path`
- `save_to_db(records, db)` (or similar)

**Schema (cscan_records.json 每条):**
```json
{
  "row_index": 7,
  "序号": 1,
  "生产厂": "中厚板卷厂",
  "钢板号": "26302650370101",
  "钢种": "X7NI9",
  "类别": "低温压力容器用合金钢",
  "缺陷分析": "显孔",
  "试样大小": "12000×2430×30",
  "F_table": "images/F_table-007.png",
  "F_ascan": "images/F_ascan-007.png",
  "F_cscan": "images/F_cscan-007.png",
  "G_table": "images/G_table-007.png",
  "G_ascan": "images/G_ascan-007.png",
  "G_cscan": "images/G_cscan-007.png",
  "缺陷表格": [
    {"序号": 18, "X起始": 868.0, "X终止": 971.0, "X中点": 919.5, "X长度": 103.0,
     "Y起始": 2733.3, "Y终止": 2737.4, "Y中点": 2735.3, "Y长度": 4.1,
     "面积": 420.9, "类型": 0, "深度": 1.1, "幅值": 100.0},
    ...
  ],
  "warnings": []
}
```

**Steps:**

- [ ] **Step 2.1**: 写 `merge_cscan_records`,从 5.1 的 row 7+ 提取 6 列基础字段,加上 F-table/ascan/cscan + G-table/ascan/cscan 6 个子图路径, 试样大小, 缺陷表格 (从 OCR 拿到的 list[dict])

- [ ] **Step 2.2**: 写 `save_json` (类似 zhongban 的 DataMerger.save_json)

- [ ] **Step 2.3**: 写 `save_db_records`,插入 SQLite `cscan_records` 表

## Task 3: 数据库加 `cscan_records` 表

**Files:** Modify `core/database.py`

**Steps:**

- [ ] **Step 3.1**: 加 `CREATE TABLE IF NOT EXISTS cscan_records`:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `task_id TEXT NOT NULL`
  - `row_index INTEGER NOT NULL`
  - `序号 TEXT, 生产厂 TEXT, 钢板号 TEXT, 钢种 TEXT, 类别 TEXT, 缺陷分析 TEXT, 试样大小 TEXT`
  - `F_table TEXT, F_ascan TEXT, F_cscan TEXT`
  - `G_table TEXT, G_ascan TEXT, G_cscan TEXT`
  - `defect_table_json TEXT`  (存 13 列表格 JSON)
  - `created_at REAL`
  - `UNIQUE(task_id, row_index)`

- [ ] **Step 3.2**: 加 `insert_cscan_records(conn, task_id, records)` 和 `get_cscan_records(conn, task_id)` 函数

## Task 4: pipeline 加 cscan 分支

**Files:** Modify `core/pipeline.py`

**Steps:**

- [ ] **Step 4.1**: `ProcessConfig` 加 `task_type: str = "zhongban"` 字段

- [ ] **Step 4.2**: `ProcessPipeline.run()` 在 `if not self.config.enable_ocr` 后加:
  ```python
  if self.config.task_type == "cscan":
      return self._run_cscan(progress_callback)
  ```

- [ ] **Step 4.3**: 加 `_run_cscan()` 方法:
  - 读 xlsx → 取 5.1 sheet (索引 1) → 提取 F/G 列图片 (`extract_cscan_from_xlsx`, 切图 + OCR 表格 + OCR 试样大小)
  - merge + save JSON + save DB
  - progress 回调: 4 个阶段 (extract / ocr / merge / database)

- [ ] **Step 4.4**: 取消点 (cancel_event) 在 cscan 流程里同样检查

## Task 5: app.py + cli.py 加 task_type

**Files:** Modify `app.py`, `cli.py`

**Steps:**

- [ ] **Step 5.1**: `app.py` `api_upload` 接收 `form.get("task_type", "zhongban")`,存入 TASKS 和传给 run_task

- [ ] **Step 5.2**: `run_task(task_id, file_path, output_dir, enable_ocr, enable_split, use_gpu, task_type="zhongban")` 把 task_type 传给 config

- [ ] **Step 5.3**: `api_list` 在每个 task dict 里返回 `task_type` 字段

- [ ] **Step 5.4**: 加 `GET /api/cscan_records/<task_id>` 路由,返回 cscan 格式数据

- [ ] **Step 5.5**: `cli.py` 加 `--type` 参数,默认 `zhongban`

## Task 6: Web UI 加文档类型 + cscan 展示

**Files:** Modify `templates/index.html`, `static/app.js`, `static/style.css`

**Steps:**

- [ ] **Step 6.1**: 上传弹窗加 `radio`: `○ 中板厂(默认)  ● 中厚板卷厂(cscan)`,提交时附带 `task_type` 字段

- [ ] **Step 6.2**: 加 `<div class="cscan-result-section" id="cscan-result-section">`,默认隐藏。结构:
  ```
  主表: 序号 | 钢板号 | 钢种 | 试样大小 | F子图×3 (table/ascan/cscan) | G子图×3 (table/ascan/cscan) | 缺陷表格
  ```
  每行点击展开详情,显示 6 张子图 + 13 列缺陷表格

- [ ] **Step 6.3**: `static/app.js` 加 `loadCscanRecords(taskId)`,从 `/api/cscan_records/<task_id>` 拉数据并渲染到 cscan-result-section

- [ ] **Step 6.4**: `refreshTaskList` 在 option label 里加 task_type 前缀: `[中板厂] 41 条 — file.xlsx` vs `[cscan] 0 条 — file.xlsx`

- [ ] **Step 6.5**: `selectTask` 根据 task_type 决定调 `loadRecords` 还是 `loadCscanRecords`

- [ ] **Step 6.6**: `static/style.css` 加 `.cscan-table` 样式,跟现有 `.record-table` 类似但简化

## Task 7: 端到端验证

**Steps:**

- [ ] **Step 7.1**: 用一个真实样本 xlsx 跑 cscan pipeline,确认 output/<task_id>/images/ 下有 6×N 张子图 (F_table/ascan/cscan + G_table/ascan/cscan),且 view_splitter 找出的 3 个矩形确实对应 [table, ascan, cscan]

- [ ] **Step 7.2**: 确认 OCR 识别缺陷表格得到 ≥1 行 13 列,试样大小能从图中识别出来

- [ ] **Step 7.3**: 确认 output/<task_id>/cscan_records.json 字段齐全

- [ ] **Step 7.4**: 浏览器上传样本 (选"中厚板卷厂"),确认任务跑完后能看到 6 张子图 + 13 列缺陷表格

- [ ] **Step 7.5**: 浏览器上传旧"中板厂"文件,确认 zhongban 流程没坏

## Self-Review Notes

- Spec coverage: 用户需求 (新文档类型/并存/cut图出 A 扫和 C 扫/OCR 表格/试样大小/标尺) → 全部在 Task 1-4 实现
- Placeholder scan: 没有 TBD/TODO
- Type consistency: cscan_records 表 / cscan_records.json / cscan_ocr 模块,命名一致
- Scope: 切图+OCR,符合"分步进行,先做图像识别文字"的要求;不做 xlsx 导出
- 复用: view_splitter 现有算法复用,只换标签
- 待确认: view_splitter 找出的 3 个矩形是否真的是 [table(左上), ascan(右上), cscan(下面)] (Task 1.5 + Task 7.1)
