"""cscan 文档的数据合并 (中厚板卷厂).

- merge_cscan_records: 从 xlsx 表格行 + 子图路径 + (后续 OCR 结果) 打包成 cscan_records 列表
- save_json: 写到 output/<task_id>/cscan_records.json
- save_to_db: 写到 SQLite cscan_records 表
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


# cscan_records.json 每条的 schema.
# OCR 字段 (缺陷表格/板信息) 暂时留 None 或空, 后续 Task 1.x 补 OCR 时填.
CSCAN_RECORD_FIELDS = (
    "序号", "生产厂", "钢板号", "钢种", "类别", "缺陷分析",
    # 子图路径 (8 张)
    "F_table", "F_ascan", "F_cscan",
    "G_table", "G_ascan", "G_cscan",
    # OCR 字段
    "缺陷表格",       # list[dict], 13 列每行
    "板号", "探伤代号", "钢种OCR", "生产日期", "检测日期",
    "标准号", "厚度", "长度", "宽度", "warnings",
)


def merge_cscan_records(
    xlsx_path: str | Path,
    image_map: dict[int, dict[str, str]],
    ocr_table_map: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """从 xlsx 的 5.1 sheet 提取基础字段, 与 image_map/OCR 结果合并.

    Args:
        xlsx_path: cscan xlsx 路径 (用 5.1 sheet, 索引 1)
        image_map: {row_idx: {"F_table": path, ...}} — cscan_ocr.extract_cscan_from_xlsx 的输出
        ocr_table_map: {row_idx: list[dict]} — 缺陷表格 OCR 结果 (可选)
        image_map: {row_idx: {F_table: path, ...}}

    Returns:
        list of cscan record dicts
    """
    xlsx_path = Path(xlsx_path)
    ocr_table_map = ocr_table_map or {}

    wb = load_workbook(str(xlsx_path), data_only=True)
    if len(wb.sheetnames) < 2:
        raise ValueError(
            f"cscan 文件至少需要 2 个 sheet, 当前 {len(wb.sheetnames)} 个: {wb.sheetnames}"
        )
    ws = wb[wb.sheetnames[1]]   # 5.1

    # 5.1 行 7+ 是真实数据 (行 1=标题, 2=表头, 3-4=要求, 5=示意, 6=空)
    DATA_START_ROW = 7

    records = []
    for row_idx in range(DATA_START_ROW, ws.max_row + 1):
        # 从 xlsx 取基础 8 列
        序号 = ws.cell(row_idx, 1).value
        if 序号 is None or 序号 == "":
            continue  # 跳过空行
        # column 2-8: 生产厂/钢板号/钢种/类别/缺陷图谱/缺陷照片/缺陷分析
        钢板号 = str(ws.cell(row_idx, 3).value or "").strip()
        钢种 = str(ws.cell(row_idx, 4).value or "").strip()
        if not 钢板号 and not 钢种:
            continue  # 钢板号和钢种都空 → 跳过
        record: dict[str, Any] = {
            "row_index": row_idx + 1,
            "序号": str(序号),
            "生产厂": str(ws.cell(row_idx, 2).value or "").strip(),
            "钢板号": 钢板号,
            "钢种": 钢种,
            "类别": str(ws.cell(row_idx, 5).value or "").strip(),
            "缺陷分析": str(ws.cell(row_idx, 8).value or "").strip(),
        }
        # 子图路径
        record.update(image_map.get(row_idx, {}))
        # 缺的子图设为 None (跨 F/G 列缺失的情况, 比如行只有 F 列图)
        for k in CSCAN_RECORD_FIELDS:
            if k.startswith(("F_", "G_")) and k not in record:
                record[k] = None
        # OCR 字段
        record["缺陷表格"] = ocr_table_map.get(row_idx, [])
        # 板信息字段暂留 None (OCR 还没做, 下步补)
        for cn in ("板号", "探伤代号", "钢种OCR", "生产日期", "检测日期",
                    "标准号", "厚度", "长度", "宽度"):
            record.setdefault(cn, None)
        record["warnings"] = []
        records.append(record)

    return records


def save_json(records: list[dict[str, Any]], output_dir: str | Path) -> Path:
    """写到 output_dir/cscan_records.json."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "cscan_records.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"count": len(records), "records": records}, f, ensure_ascii=False, indent=2)
    return json_path


# ============================================================
# 数据库 (SQLite)
# ============================================================
def ensure_cscan_table(conn: sqlite3.Connection) -> None:
    """确保 cscan_records 表存在."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cscan_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            "序号" TEXT, "生产厂" TEXT, "钢板号" TEXT, "钢种" TEXT,
            "类别" TEXT, "缺陷分析" TEXT,
            F_table TEXT, F_ascan TEXT, F_cscan TEXT,
            G_table TEXT, G_ascan TEXT, G_cscan TEXT,
            缺陷表格 TEXT,
            "板号" TEXT, "探伤代号" TEXT, "钢种OCR" TEXT, "生产日期" TEXT,
            "检测日期" TEXT, "标准号" TEXT, "厚度" REAL, "长度" REAL, "宽度" REAL,
            warnings TEXT,
            created_at REAL,
            UNIQUE(task_id, row_index)
        )
    """)
    conn.commit()


def save_to_db(conn: sqlite3.Connection, task_id: str, records: list[dict[str, Any]]) -> int:
    """写入 SQLite, 返回插入/更新的行数."""
    ensure_cscan_table(conn)
    import time
    now = time.time()
    count = 0
    for r in records:
        # 缺陷表格 序列化为 JSON 字符串
        defect_table_json = json.dumps(r.get("缺陷表格") or [], ensure_ascii=False)
        warnings_json = json.dumps(r.get("warnings") or [], ensure_ascii=False)
        # row_index 1-based (前端展示用)
        row_1based = r.get("row_index", 0)
        conn.execute("""
            INSERT OR REPLACE INTO cscan_records
            (task_id, row_index, "序号", "生产厂", "钢板号", "钢种", "类别", "缺陷分析",
             F_table, F_ascan, F_cscan,
             G_table, G_ascan, G_cscan,
             缺陷表格, "板号", "探伤代号", "钢种OCR", "生产日期", "检测日期",
             "标准号", "厚度", "长度", "宽度", warnings, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, row_1based,
            r.get("序号"), r.get("生产厂"), r.get("钢板号"), r.get("钢种"),
            r.get("类别"), r.get("缺陷分析"),
            r.get("F_table"), r.get("F_ascan"), r.get("F_cscan"),
            r.get("G_table"), r.get("G_ascan"), r.get("G_cscan"),
            defect_table_json,
            r.get("板号"), r.get("探伤代号"), r.get("钢种OCR"), r.get("生产日期"),
            r.get("检测日期"), r.get("标准号"),
            r.get("厚度"), r.get("长度"), r.get("宽度"),
            warnings_json, now,
        ))
        count += 1
    conn.commit()
    return count


def load_from_db(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """从 SQLite 读 cscan_records."""
    ensure_cscan_table(conn)
    rows = conn.execute(
        "SELECT * FROM cscan_records WHERE task_id = ? ORDER BY row_index",
        (task_id,),
    ).fetchall()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(cscan_records)").fetchall()]
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        # 反序列化 JSON
        try:
            d["缺陷表格"] = json.loads(d.get("缺陷表格") or "[]")
        except Exception:
            d["缺陷表格"] = []
        try:
            d["warnings"] = json.loads(d.get("warnings") or "[]")
        except Exception:
            d["warnings"] = []
        results.append(d)
    return results
