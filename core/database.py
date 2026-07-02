"""SQLite 数据库模块。

存储缺陷记录、文件元数据,支持:
- 任务的增删改查
- 缺陷记录的 CRUD
- 图片与记录的关联
- 历史查询

数据模型:

    files                  -- 源文件记录
    +--- tasks             -- 一次处理任务
         +--- records      -- 缺陷记录
              +--- images  -- 每条记录关联的图片
              +--- views   -- 切分后的视图
              +--- ocr     -- OCR 识别结果
"""
from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from datetime import datetime


class Database:
    """SQLite 数据库管理器。"""

    DEFAULT_PATH = Path(__file__).parent.parent / "data" / "defect_map.db"

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        """获取数据库连接 (自动关闭)。"""
        c = sqlite3.connect(str(self.db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _init_schema(self):
        """初始化数据库表结构。"""
        with self.conn() as c:
            c.executescript("""
                -- 源文件
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    original_path TEXT,
                    file_format TEXT,
                    file_size INTEGER,
                    md5 TEXT,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- 处理任务
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER REFERENCES files(id),
                    task_uuid TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'pending',
                    output_dir TEXT,
                    elapsed_seconds REAL,
                    stats_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );

                -- 缺陷记录
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                    row_index INTEGER,
                    sequence TEXT,
                    factory TEXT,
                    plate_no TEXT,
                    steel_grade TEXT,
                    category TEXT,
                    defect_analysis TEXT,
                    extra_notes TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_records_task ON records(task_id);
                CREATE INDEX IF NOT EXISTS idx_records_plate ON records(plate_no);

                -- 图片 (一张原图)
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER REFERENCES records(id) ON DELETE CASCADE,
                    image_index INTEGER,        -- 第几张图 (1 或 2)
                    file_path TEXT NOT NULL,
                    image_format TEXT,
                    width INTEGER,
                    height INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- 视图 (切分后的三视图)
                CREATE TABLE IF NOT EXISTS views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                    view_type TEXT,            -- top / long / short / annotated
                    view_label TEXT,           -- 1-俯视图 / 2-长边侧视图 / ...
                    file_path TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER
                );

                -- OCR 识别结果
                CREATE TABLE IF NOT EXISTS ocr_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                    material_size TEXT,
                    defect_center_x TEXT,
                    defect_center_y TEXT,
                    defect_length TEXT,
                    defect_width TEXT,
                    defect_depth TEXT,
                    raw_text TEXT,
                    warnings TEXT,
                    confidence REAL
                );
            """)

    # ===== 文件 =====

    def add_file(
        self, filename: str, original_path: str, file_format: str, file_size: int, md5: str = ""
    ) -> int:
        """添加源文件记录。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO files (filename, original_path, file_format, file_size, md5)
                   VALUES (?, ?, ?, ?, ?)""",
                (filename, original_path, file_format, file_size, md5),
            )
            return cur.lastrowid

    # ===== 任务 =====

    def create_task(self, file_id: int, task_uuid: str, output_dir: str) -> int:
        """创建处理任务。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO tasks (file_id, task_uuid, status, output_dir)
                   VALUES (?, ?, 'processing', ?)""",
                (file_id, task_uuid, output_dir),
            )
            return cur.lastrowid

    def update_task_status(self, task_uuid: str, status: str, **kwargs):
        """更新任务状态。"""
        with self.conn() as c:
            fields = ["status = ?"]
            values = [status]
            for key, val in kwargs.items():
                if key == "stats":
                    fields.append("stats_json = ?")
                    values.append(json.dumps(val, ensure_ascii=False))
                else:
                    fields.append(f"{key} = ?")
                    values.append(val)
            if status in ("completed", "failed"):
                fields.append("completed_at = CURRENT_TIMESTAMP")
            values.append(task_uuid)
            c.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE task_uuid = ?", values)

    def get_task(self, task_uuid: str) -> dict | None:
        """获取任务详情。"""
        with self.conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE task_uuid = ?", (task_uuid,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("stats_json"):
                d["stats"] = json.loads(d["stats_json"])
            return d

    def list_tasks(self, limit: int = 50) -> list[dict]:
        """列出最近的任务。"""
        with self.conn() as c:
            rows = c.execute(
                """SELECT t.*, f.filename as file_name
                   FROM tasks t
                   LEFT JOIN files f ON f.id = t.file_id
                   ORDER BY t.created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ===== 记录 =====

    def add_record(
        self,
        task_id: int,
        row_index: int,
        sequence: str,
        factory: str,
        plate_no: str,
        steel_grade: str,
        category: str,
        defect_analysis: str,
        extra_notes: str = "",
        notes: str = "",
    ) -> int:
        """添加缺陷记录。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO records
                   (task_id, row_index, sequence, factory, plate_no,
                    steel_grade, category, defect_analysis, extra_notes, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, row_index, sequence, factory, plate_no,
                    steel_grade, category, defect_analysis, extra_notes, notes,
                ),
            )
            return cur.lastrowid

    def get_records(self, task_uuid: str) -> list[dict]:
        """获取任务的所有记录 (含图片、视图、OCR 数据)。"""
        with self.conn() as c:
            task = c.execute(
                "SELECT id FROM tasks WHERE task_uuid = ?", (task_uuid,)
            ).fetchone()
            if not task:
                return []

            records = c.execute(
                "SELECT * FROM records WHERE task_id = ? ORDER BY row_index",
                (task["id"],),
            ).fetchall()

            result = []
            for rec in records:
                d = dict(rec)
                # 关联图片
                images = c.execute(
                    "SELECT * FROM images WHERE record_id = ? ORDER BY image_index",
                    (rec["id"],),
                ).fetchall()
                d["images"] = [dict(img) for img in images]

                # 每张图的视图和 OCR
                for img in d["images"]:
                    views = c.execute(
                        "SELECT * FROM views WHERE image_id = ?",
                        (img["id"],),
                    ).fetchall()
                    img["views"] = [dict(v) for v in views]

                    ocr = c.execute(
                        "SELECT * FROM ocr_results WHERE image_id = ?",
                        (img["id"],),
                    ).fetchone()
                    img["ocr"] = dict(ocr) if ocr else None

                result.append(d)
            return result

    def get_record(self, record_id: int) -> dict | None:
        """获取单条记录。"""
        with self.conn() as c:
            row = c.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
            return dict(row) if row else None

    def search_records(
        self,
        keyword: str = "",
        category: str = "",
        steel_grade: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """搜索记录。"""
        with self.conn() as c:
            sql = "SELECT * FROM records WHERE 1=1"
            params = []
            if keyword:
                sql += " AND (plate_no LIKE ? OR steel_grade LIKE ? OR defect_analysis LIKE ?)"
                kw = f"%{keyword}%"
                params.extend([kw, kw, kw])
            if category:
                sql += " AND category = ?"
                params.append(category)
            if steel_grade:
                sql += " AND steel_grade LIKE ?"
                params.append(f"%{steel_grade}%")
            sql += " ORDER BY row_index LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    # ===== 图片 =====

    def add_image(
        self,
        record_id: int,
        image_index: int,
        file_path: str,
        image_format: str,
        width: int = 0,
        height: int = 0,
    ) -> int:
        """添加图片关联。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO images
                   (record_id, image_index, file_path, image_format, width, height)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (record_id, image_index, file_path, image_format, width, height),
            )
            return cur.lastrowid

    # ===== 视图 =====

    def add_view(
        self,
        image_id: int,
        view_type: str,
        view_label: str,
        file_path: str,
        width: int = 0,
        height: int = 0,
    ) -> int:
        """添加视图关联。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO views
                   (image_id, view_type, view_label, file_path, width, height)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (image_id, view_type, view_label, file_path, width, height),
            )
            return cur.lastrowid

    # ===== OCR =====

    def add_ocr(
        self,
        image_id: int,
        params: dict,
        raw_text: str = "",
        warnings: str = "",
        confidence: float = 0.0,
    ) -> int:
        """添加 OCR 结果。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO ocr_results
                   (image_id, material_size, defect_center_x, defect_center_y,
                    defect_length, defect_width, defect_depth, raw_text, warnings, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    image_id,
                    params.get("材料尺寸", ""),
                    params.get("缺陷中心X", ""),
                    params.get("缺陷中心Y", ""),
                    params.get("缺陷长度", ""),
                    params.get("缺陷宽度", ""),
                    params.get("缺陷深度", ""),
                    raw_text,
                    warnings,
                    confidence,
                ),
            )
            return cur.lastrowid

    # ===== 统计 =====

    def get_stats(self) -> dict:
        """获取数据库统计信息。"""
        with self.conn() as c:
            return {
                "total_files": c.execute("SELECT COUNT(*) FROM files").fetchone()[0],
                "total_tasks": c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                "total_records": c.execute("SELECT COUNT(*) FROM records").fetchone()[0],
                "total_images": c.execute("SELECT COUNT(*) FROM images").fetchone()[0],
                "total_views": c.execute("SELECT COUNT(*) FROM views").fetchone()[0],
                "total_ocr": c.execute("SELECT COUNT(*) FROM ocr_results").fetchone()[0],
                "categories": [
                    r[0]
                    for r in c.execute(
                        "SELECT DISTINCT category FROM records WHERE category IS NOT NULL"
                    ).fetchall()
                ],
            }


def get_database(db_path: str | Path | None = None) -> Database:
    """获取数据库单例。"""
    return Database(db_path)


if __name__ == "__main__":
    db = Database()
    print(f"数据库: {db.db_path}")
    print("统计:", db.get_stats())