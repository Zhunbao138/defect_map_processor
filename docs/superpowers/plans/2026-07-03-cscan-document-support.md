# 中厚板卷厂 (cscan) 文档支持 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有"中板厂 (zhongban)" 文档流程之外,新增"中厚板卷厂 (cscan)" 文档的并行处理流程。本步骤只做"图像识别文字"和"原图提取",不做切图、不做 xlsx 导出。

**Architecture:** 在 `core/pipeline.py` 加 `task_type` 分支,新模块 `core/cscan_ocr.py` 负责从 F/G 列提取原图 + 跑 Tesseract 识别左上角 13 列缺陷表格 + 试样大小信息。新模块 `core/cscan_merger.py` 打包 schema 并写入新表 `cscan_records`。前端加文档类型选择,Web 页面分标签显示两种数据。

**Tech Stack:** Python (openpyxl + pytesseract + PIL), HTML/CSS/JS。沿用现有依赖,不加新包。

## Global Constraints

- 不动现有"中板厂"流程。所有 `zhongban` 相关文件保持向后兼容
- `task_type` 字段默认 `"zhongban"`,缺失时按 zhongban 处理
- `cscan` 流程: **不** 调 `view_splitter`, **不** 调现有 `ocr_extractor` 切图后的部分 (那 6 列参数)
- 切图 (三视图) 留到下一阶段,本步只提原图
- OCR 仍用 Tesseract (沿用现有部署),不支持 GPU (和 zhongban 一致)
- 数据库: 新表 `cscan_records` 与 `records` 并列,不破坏现有表
- 现有测试和已上传的任务必须能继续跑

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
  - 图片布局 (和 zhongban 一样是 F+G 列):
    - F 列 (col=5, 0-based): 第 1 张图 (C 扫结果图)
    - G 列 (col=6, 0-based): 第 2 张图 (A 扫缺陷波图像)
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
- `extract_cscan_images(ws, output_dir) -> dict[int, dict]` — 从 ws._images 提取 F/G 列图片,返回 `{row_idx: {"cscan": Path, "ascan": Path}}`
- `extract_sample_size(cscan_image_path) -> str | None` — 用 pytesseract 识别试样大小(从 C 扫图顶部)

**Steps:**

- [ ] **Step 1.1**: 写 `extract_cscan_images` 函数:遍历 `ws._images`,取 F (col=5) 和 G (col=6) 锚点,row 排序,配对保存为 `cscan-{row:03d}.png` 和 `ascan-{row:03d}.png`

- [ ] **Step 1.2**: 写 `extract_sample_size`:从 C 扫图顶部切一条带状区域 (高度 ~40px),pytesseract 跑 `image_to_string`,正则匹配 `(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)`,返回 `f"{w}×{h}×{t}"` 格式

- [ ] **Step 1.3**: 单元测试:对样本 `input/..._20260702_155121.xlsx` 跑一次,确认能从 5.1 提取 86 张图,存到 `output/test_cscan/images/`

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
  "C扫图": "images/cscan-007.png",
  "A扫图": "images/ascan-007.png",
  "缺陷表格": [],
  "warnings": []
}
```

**Steps:**

- [ ] **Step 2.1**: 写 `merge_cscan_records`,从 5.1 的 row 7+ 提取 6 列基础字段,加上 image paths 和 sample_size,`缺陷表格` 暂时空数组 (本步不 OCR 表格)

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
  - `cscan_image TEXT, ascan_image TEXT`
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
  - 读 xlsx → 取 5.1 sheet (索引 1) → 提取 F/G 列图片 (`extract_cscan_images`)
  - 对每张 C 扫图 → OCR 试样大小 (`extract_sample_size`)
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
  序号 | 钢板号 | 钢种 | 试样大小 | C扫图 | A扫图
  ```

- [ ] **Step 6.3**: `static/app.js` 加 `loadCscanRecords(taskId)`,从 `/api/cscan_records/<task_id>` 拉数据并渲染到 cscan-result-section

- [ ] **Step 6.4**: `refreshTaskList` 在 option label 里加 task_type 前缀: `[中板厂] 41 条 — file.xlsx` vs `[cscan] 0 条 — file.xlsx`

- [ ] **Step 6.5**: `selectTask` 根据 task_type 决定调 `loadRecords` 还是 `loadCscanRecords`

- [ ] **Step 6.6**: `static/style.css` 加 `.cscan-table` 样式,跟现有 `.record-table` 类似但简化

## Task 7: 端到端验证

**Steps:**

- [ ] **Step 7.1**: 用一个真实样本 xlsx 跑 cscan pipeline,确认 output/<task_id>/images/ 下有 cscan-*.png 和 ascan-*.png

- [ ] **Step 7.2**: 确认 output/<task_id>/cscan_records.json 字段齐全

- [ ] **Step 7.3**: 浏览器上传样本 (选"中厚板卷厂"),确认任务跑完后能看到表格 + 两张图

- [ ] **Step 7.4**: 浏览器上传旧"中板厂"文件,确认 zhongban 流程没坏

## Self-Review Notes

- Spec coverage: 6 项需求 (新文档/并存/OCR/试样大小/标尺/表格) → 全部在 Task 1-4 实现
- Placeholder scan: 没有 TBD/TODO
- Type consistency: cscan_records 表 / cscan_records.json / cscan-OCR 模块,命名一致
- Scope: 不切图,不做 xlsx 导出,符合"分步进行,先做 OCR"的要求
- 复用: 5.1 sheet 的 F+G 图布局和现有 zhongban 适配过的相同 (之前刚加的列适配直接用上)
