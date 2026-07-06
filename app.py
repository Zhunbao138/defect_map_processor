"""Flask Web 应用。

提供以下路由:
- GET  /                          主页 (前端展示)
- POST /api/upload                上传并处理 Excel 文件
- POST /api/process               处理本地文件
- GET  /api/records               获取所有缺陷记录 (JSON)
- GET  /api/records/<row_index>   获取单条记录
- GET  /api/progress/<task_id>    获取处理进度
- GET  /api/image/<path:filepath> 提供图片访问

使用:
    python cli.py serve
    python cli.py serve --port 8080 --debug
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)

from core.pipeline import run_pipeline, ProcessPipeline, ProcessConfig

import os
from functools import wraps


# 全局任务状态
TASKS: dict[str, dict] = {}
TASK_LOCK = threading.Lock()
# 每个任务的取消标志 (threading.Event). cancel API 设置 Event, run_task 在每个 progress 回调里检查.
CANCEL_FLAGS: dict[str, threading.Event] = {}

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"



# ============= HTTP Basic Auth =============
import base64
import secrets as _secrets
from pathlib import Path as _Path

def _load_credentials():
    user = os.environ.get("ADMIN_USER", "admin")
    pwd = os.environ.get("ADMIN_PASSWORD")
    if not pwd:
        for auth_file in [_Path(__file__).parent / ".auth", _Path("/home/ubuntu/.defect_auth")]:
            if auth_file.exists():
                try:
                    content = auth_file.read_text(encoding="utf-8-sig").strip()
                    if ":" in content:
                        u, p = content.split(":", 1)
                        user = u.strip()
                        pwd = p.strip()
                        break
                except Exception:
                    pass
    if not pwd:
        raise RuntimeError("ADMIN_PASSWORD not set, use env var or .auth file")
    return user, pwd

_AUTH_USER, _AUTH_PASS = _load_credentials()

def _check_auth(auth_header):
    if not auth_header:
        return False
    try:
        scheme, credentials = auth_header.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        decoded = base64.b64decode(credentials).decode("utf-8", errors="ignore")
        if ":" not in decoded:
            return False
        u, p = decoded.split(":", 1)
        return _secrets.compare_digest(u, _AUTH_USER) and _secrets.compare_digest(p, _AUTH_PASS)
    except Exception:
        return False

def _unauthorized():
    return Response(
        "<!doctype html><html><head><meta charset=utf-8>" +
        "<title>需要登录 - 钢材缺陷图像知识库</title>" +
        "<style>body{font-family:sans-serif;display:flex;align-items:center;" +
        "justify-content:center;height:100vh;margin:0;background:#1a202c;color:#fff;}" +
        ".box{text-align:center;padding:2rem;}" +
        "h1{margin:0 0 1rem;font-size:1.5rem;}" +
        "p{opacity:0.7;}</style></head><body>" +
        "<div class=box><h1>钢材缺陷图像知识库 - 需要登录</h1>" +
        "<p>Please use account and password (browser will prompt)</p></div></body></html>",
        status=401,
        headers={"WWW-Authenticate": "Basic realm=Steel-Defect-Knowledge-Base"}
    )

def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.path == "/api/health":
            return f(*args, **kwargs)
        if not _check_auth(request.headers.get("Authorization")):
            return _unauthorized()
        return f(*args, **kwargs)
    return decorated

# ============= /HTTP Basic Auth =============


def _load_cscan_from_db(conn, task_id: str) -> list[dict]:
    """从 SQLite cscan_records 读 records, 反序列化 缺陷表格 JSON."""
    import json as _json
    rows = conn.execute(
        "SELECT * FROM cscan_records WHERE task_id = ? ORDER BY row_index",
        (task_id,),
    ).fetchall()
    # PRAGMA table_info 返回 (cid, name, type, notnull, dflt_value, pk), name 在 index 1
    cols = [d[1] for d in conn.execute("PRAGMA table_info(cscan_records)").fetchall()]
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        for fld in ("缺陷表格_F", "缺陷表格_G"):
            try:
                d[fld] = _json.loads(d.get(fld) or "[]")
            except Exception:
                d[fld] = []
        try:
            d["warnings"] = _json.loads(d.get("warnings") or "[]")
        except Exception:
            d["warnings"] = []
        results.append(d)
    return results


def create_app() -> Flask:
    """创建 Flask 应用。"""
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB 上限

    register_routes(app)
    return app


def register_routes(app: Flask):
    """注册路由。"""

    @app.route("/")
    @auth_required
    def index():
        """主页。"""
        return render_template("index.html")

    @app.route("/api/upload", methods=["POST"])
    @auth_required
    def api_upload():
        """上传并处理 Excel 文件。"""
        if "file" not in request.files:
            return jsonify({"error": "未提供文件"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "文件名为空"}), 400

        # 检查扩展名 - 只支持 .xlsx
        ext = Path(file.filename).suffix.lower()
        if ext == ".xls":
            return jsonify({
                "error": "不支持 .xls 格式! 请先用 WPS/Excel 打开并另存为 .xlsx 后再上传。"
            }), 400
        if ext != ".xlsx":
            return jsonify({"error": f"不支持的格式: {ext}, 仅支持 .xlsx"}), 400

        # 保存到 input 目录
        input_dir = PROJECT_ROOT / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = Path(file.filename).stem
        saved_path = input_dir / f"{safe_name}_{timestamp}{ext}"
        file.save(str(saved_path))

        # 创建任务
        task_id = str(uuid.uuid4())[:8]
        output_dir = DEFAULT_OUTPUT_DIR / task_id
        with TASK_LOCK:
            TASKS[task_id] = {
                "status": "pending",
                "progress": 0.0,
                "stage": "init",
                "message": "等待处理...",
                "file": str(saved_path),
                "output_dir": str(output_dir),
                "created_at": time.time(),
            }

        # 后台线程处理
        recognition = request.form.get("recognition", "ocr")
        task_type = request.form.get("task_type", "zhongban").lower()
        if task_type not in ("zhongban", "cscan"):
            task_type = "zhongban"

        with TASK_LOCK:
            TASKS[task_id]["task_type"] = task_type

        thread = threading.Thread(
            target=run_task,
            args=(task_id, str(saved_path), str(output_dir), recognition, task_type),
            daemon=True,
        )
        thread.start()

        return jsonify({"task_id": task_id, "status": "processing"})

    @app.route("/api/process", methods=["POST"])
    @auth_required
    def api_process():
        """处理已存在的本地文件路径。"""
        data = request.get_json()
        file_path = data.get("file_path") if data else None
        if not file_path:
            return jsonify({"error": "未提供 file_path"}), 400

        if not Path(file_path).exists():
            return jsonify({"error": f"文件不存在: {file_path}"}), 404

        # 检查扩展名 - 只支持 .xlsx
        ext = Path(file_path).suffix.lower()
        if ext == ".xls":
            return jsonify({
                "error": "不支持 .xls 格式! 请先用 WPS/Excel 打开并另存为 .xlsx 后再处理。"
            }), 400
        if ext != ".xlsx":
            return jsonify({"error": f"不支持的格式: {ext}, 仅支持 .xlsx"}), 400

        task_id = str(uuid.uuid4())[:8]
        output_dir = DEFAULT_OUTPUT_DIR / task_id
        with TASK_LOCK:
            TASKS[task_id] = {
                "status": "pending",
                "progress": 0.0,
                "stage": "init",
                "message": "等待处理...",
                "file": file_path,
                "output_dir": str(output_dir),
                "created_at": time.time(),
            }

        recognition = data.get("recognition", "ocr")

        thread = threading.Thread(
            target=run_task,
            args=(task_id, file_path, str(output_dir), recognition, "zhongban"),
            daemon=True,
        )
        thread.start()

        return jsonify({"task_id": task_id, "status": "processing"})

    @app.route("/api/progress/<task_id>")
    @auth_required
    def api_progress(task_id: str):
        """查询任务进度。"""
        with TASK_LOCK:
            task = TASKS.get(task_id)
            if not task:
                return jsonify({"error": "任务不存在"}), 404
            return jsonify(task)

    @app.route("/api/records/<task_id>")
    @auth_required
    def api_records(task_id: str):
        """获取任务的缺陷记录。"""
        # 1. 内存中
        with TASK_LOCK:
            task = TASKS.get(task_id)

        if task:
            output_dir = Path(task["output_dir"])
            status = task["status"]
        else:
            # 2. 磁盘上
            output_dir = DEFAULT_OUTPUT_DIR / task_id
            if not output_dir.exists():
                return jsonify({"error": "任务不存在"}), 404
            status = "completed"

        json_path = output_dir / "defect_records.json"
        if not json_path.exists():
            return jsonify({"error": "记录尚未生成", "status": status}), 404

        with open(json_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        return jsonify(
            {
                "task_id": task_id,
                "status": status,
                "count": len(records),
                "records": records,
            }
        )

    @app.route("/api/image/<task_id>/<path:filepath>")
    @auth_required
    def api_image(task_id: str, filepath: str):
        """提供图片访问。"""
        with TASK_LOCK:
            task = TASKS.get(task_id)
        if task:
            output_dir = Path(task["output_dir"])
        else:
            output_dir = DEFAULT_OUTPUT_DIR / task_id
            if not output_dir.exists():
                abort(404)

        # 安全检查：防止路径穿越
        try:
            img_path = (output_dir / filepath).resolve()
            output_dir_resolved = output_dir.resolve()
            if not str(img_path).startswith(str(output_dir_resolved)):
                abort(403)
            if not img_path.exists():
                abort(404)
            return send_from_directory(str(img_path.parent), img_path.name)
        except Exception:
            abort(404)

    @app.route("/api/list")
    @auth_required
    def api_list():
        """列出所有任务。

        数据源:
        1. 内存中的 TASKS dict (本次进程内的任务, 含实时进度)
        2. 磁盘 output/<task_id>/defect_records.json (历史任务, 重启后仍可见)
        """
        tasks = []
        seen = set()

        # 1. 内存中的活跃任务
        with TASK_LOCK:
            for tid, t in TASKS.items():
                tasks.append(
                    {
                        "task_id": tid,
                        "status": t["status"],
                        "stage": t.get("stage", ""),
                        "progress": t.get("progress", 0),
                        "file": Path(t["file"]).name if t.get("file") else "",
                        "created_at": t.get("created_at", 0),
                        "task_type": t.get("task_type", "zhongban"),
                        "source": "memory",
                    }
                )
                seen.add(tid)

        # 2. 磁盘上的历史任务
        for task_dir in DEFAULT_OUTPUT_DIR.iterdir():
            if not task_dir.is_dir():
                continue
            tid = task_dir.name
            if tid in seen:
                continue
            json_path = task_dir / "defect_records.json"
            # cscan 任务用 cscan_records.json, 兼容两种
            cscan_path = task_dir / "cscan_records.json"
            json_path_eff = cscan_path if cscan_path.exists() else json_path
            if not json_path_eff.exists():
                continue
            detected_type = "cscan" if cscan_path.exists() else "zhongban"
            # 读取元数据
            # 读取元数据
            try:
                with open(json_path_eff, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 文件可能是 list 也可能是 dict (带 count/records 字段)
                records = data.get("records", data) if isinstance(data, dict) else data
                count = len(records) if isinstance(records, list) else 0
            except Exception:
                count = 0
            # 从数据库查文件名 (按 output_dir 匹配 tasks 表)
            file_name = ""
            try:
                import sqlite3
                db_path = PROJECT_ROOT / "data" / "defect_map.db"
                with sqlite3.connect(str(db_path)) as conn:
                    row = conn.execute(
                        """SELECT f.filename FROM tasks t
                           LEFT JOIN files f ON f.id = t.file_id
                           WHERE t.output_dir = ?
                           LIMIT 1""",
                        (str(task_dir),),
                    ).fetchone()
                    if row and row[0]:
                        file_name = row[0]
            except Exception:
                pass
            if not file_name:
                # 从 task_info.json 读文件名
                try:
                    ti_path = task_dir / "task_info.json"
                    if ti_path.exists():
                        with open(ti_path) as tf:
                            ti = json.load(tf)
                        file_name = ti.get("source_file", "")
                except Exception:
                    pass
            if not file_name:
                file_name = f"任务 {tid} ({count} 条)"

            # 创建时间 = 目录 mtime
            created_at = task_dir.stat().st_mtime
            tasks.append(
                {
                    "task_id": tid,
                    "status": "completed",
                    "stage": "database",
                    "progress": 1.0,
                    "file": file_name,
                    "created_at": created_at,
                    "count": count,
                    "task_type": detected_type,
                    "source": "disk",
                }
            )

        tasks.sort(key=lambda x: x["created_at"], reverse=True)
        return jsonify({"tasks": tasks})

    @app.route("/api/cancel/<task_id>", methods=["POST"])
    @auth_required
    def api_cancel(task_id: str):
        """取消正在跑的任务。会在下一个 progress 回调处终止 (通常 1 张图内)。"""
        with TASK_LOCK:
            event = CANCEL_FLAGS.get(task_id)
            if event is None:
                # 任务不在跑(可能已完成/失败/从未存在)
                task = TASKS.get(task_id)
                if task and task.get("status") in ("completed", "failed", "cancelled"):
                    return jsonify({"ok": True, "message": f"任务已是 {task.get('status')} 状态, 无需取消"}), 200
                return jsonify({"ok": False, "error": f"任务 {task_id} 不在跑"}), 404
            event.set()
        return jsonify({"ok": True, "message": f"已请求取消 {task_id}, 将在下次 progress 回调中停止"}), 200

    @app.route("/api/cscan_records/<task_id>")
    @auth_required
    def api_cscan_records(task_id: str):
        """读 cscan_records (中厚板卷厂 schema). 从 SQLite 优先, fallback JSON."""
        try:
            # 优先从内存里的 TASKS (实时) 拿 output_dir
            output_dir = None
            with TASK_LOCK:
                t = TASKS.get(task_id)
                if t:
                    output_dir = Path(t.get("output_dir", ""))
            # 兜底: 磁盘路径
            if not output_dir or not output_dir.exists():
                output_dir = DEFAULT_OUTPUT_DIR / task_id
            if not output_dir.exists():
                return jsonify({"error": f"任务 {task_id} 不存在"}), 404

            # 优先从 SQLite 读
            import sqlite3
            db_path = PROJECT_ROOT / "data" / "defect_map.db"
            db_records = None
            if db_path.exists():
                try:
                    conn = sqlite3.connect(str(db_path))
                    try:
                        db_records = _load_cscan_from_db(conn, task_id)
                    finally:
                        conn.close()
                except Exception:
                    pass  # DB 表不存在/损坏 → 回退到 JSON
            if db_records:
                return jsonify({"task_id": task_id, "count": len(db_records), "records": db_records})

            # Fallback 从 JSON 读
            json_path = output_dir / "cscan_records.json"
            if not json_path.exists():
                return jsonify({"error": f"任务 {task_id} 没有 cscan_records"}), 404
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify({"task_id": task_id, **data})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cscan_records_xlsx/<task_id>", methods=["GET", "POST"])
    @auth_required
    def api_cscan_xlsx(task_id: str):
        """提供 cscan_records.xlsx 下载.

        GET  → 全量 (无 filter)
        POST → body: {"row_indexes": [8,9,11,...]} 按 filter 导出
        """
        import json as _json
        from core.cscan_merger import save_excel
        with TASK_LOCK:
            task = TASKS.get(task_id)
        output_dir = Path(task["output_dir"]) if task else DEFAULT_OUTPUT_DIR / task_id
        json_path = output_dir / "cscan_records.json"
        if not json_path.exists():
            abort(404)
        with open(json_path, "r", encoding="utf-8") as f:
            all_data = _json.load(f)
        all_records = all_data.get("records", [])
        if not all_records:
            abort(404)

        # 如果前端发了 row_indexes (filter+sort 后的行), 只导出这些
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            wanted = set(body.get("row_indexes") or [])
            if wanted:
                all_records = [r for r in all_records if r.get("row_index") in wanted]

        xlsx_path = output_dir / "cscan_records.xlsx"
        save_excel(all_records, output_dir)
        return send_file(str(xlsx_path), as_attachment=True,
                         download_name=f"cscan_records_{task_id}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


    @app.route("/api/cscan_records/<task_id>/<int:row_index>", methods=["PUT"])
    @auth_required
    def api_update_cscan_record(task_id: str, row_index: int):
        """更新 cscan 记录的缺陷表格数据."""
        data = request.get_json(silent=True) or {}
        with TASK_LOCK:
            task = TASKS.get(task_id)
        output_dir = Path(task["output_dir"]) if task else DEFAULT_OUTPUT_DIR / task_id
        json_path = output_dir / "cscan_records.json"
        if not json_path.exists():
            return jsonify({"error": "cscan_records not found"}), 404
        with open(json_path, "r", encoding="utf-8") as f:
            all_data = json.load(f)
        records = all_data.get("records", [])
        updated = None
        for r in records:
            if r.get("row_index") == row_index:
                for k, v in data.items():
                    r[k] = v
                updated = r
                break
        if updated is None:
            return jsonify({"error": f"row_index {row_index} not found"}), 404
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        # 重新生成 xlsx
        from core.cscan_merger import save_excel
        save_excel(records, output_dir)
        return jsonify({"ok": True, "row_index": row_index})

    @app.route("/api/records/<task_id>/<int:row_index>", methods=["POST", "PUT"])
    @auth_required
    def api_update_record(task_id: str, row_index: int):
        """更新某条记录的缺陷数据 (用户手动编辑)。"""
        # 找输出目录
        with TASK_LOCK:
            task = TASKS.get(task_id)
        if task:
            output_dir = Path(task["output_dir"])
        else:
            output_dir = DEFAULT_OUTPUT_DIR / task_id
        if not output_dir.exists():
            return jsonify({"error": "任务不存在"}), 404

        json_path = output_dir / "defect_records.json"
        if not json_path.exists():
            return jsonify({"error": "记录尚未生成"}), 404

        # 读现有数据
        with open(json_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        # 找 row
        target = None
        for r in records:
            if r.get("row_index") == row_index:
                target = r
                break
        if target is None:
            return jsonify({"error": f"未找到 row_index={row_index}"}), 404

        # 取 POST body
        data = request.get_json() or {}
        defects = data.get("缺陷数据", {})
        if not isinstance(defects, dict):
            return jsonify({"error": "缺陷数据必须是对象"}), 400

        # 更新该 row 的 缺陷数据
        target["缺陷数据"] = defects

        # 写回
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        # 重新生成 Excel, 让编辑反映到下载的 excel
        try:
            from core.data_merger import DataMerger
            merger = DataMerger(output_dir)
            merger.save_excel(records)
        except Exception as e:
            # Excel 生成失败不阻塞保存
            print(f"重新生成 Excel 失败: {e}")

        return jsonify({
            "success": True,
            "row_index": row_index,
            "缺陷数据": defects,
        })

    @app.route("/api/health")
    @auth_required
    def api_health():
        """健康检查。"""
        return jsonify({"status": "ok", "time": datetime.now().isoformat()})


def run_task(
    task_id: str,
    file_path: str,
    output_dir: str,
    recognition: str = "ocr",
    task_type: str = "zhongban",
):
    """后台执行处理任务。"""

    # 创建取消标志并加入全局表
    cancel_event = threading.Event()
    with TASK_LOCK:
        CANCEL_FLAGS[task_id] = cancel_event

    try:
        def progress(stage, percent, message):
            # 检查是否被用户取消
            if cancel_event.is_set():
                raise InterruptedError("任务被用户取消")
            with TASK_LOCK:
                if task_id in TASKS:
                    TASKS[task_id].update(
                        {
                            "stage": stage,
                            "progress": percent,
                            "message": message,
                            "status": "processing",
                        }
                    )

        config = ProcessConfig(
            file_path=file_path,
            output_dir=output_dir,
            enable_ocr=(task_type == "zhongban"),
            enable_split=(task_type == "zhongban"),
            task_type=task_type,
            recognition=recognition,
        )
        pipeline = ProcessPipeline(config)
        pipeline.cancel_event = cancel_event
        try:
            result = pipeline.run(progress_callback=progress)
        except InterruptedError:
            with TASK_LOCK:
                if task_id in TASKS:
                    TASKS[task_id].update(
                        {
                            "status": "cancelled",
                            "message": "已取消",
                        }
                    )
            return

        with TASK_LOCK:
            if task_id in TASKS:
                TASKS[task_id].update(
                    {
                        "status": "completed" if result.success else "failed",
                        "progress": 1.0,
                        "message": (
                            "处理完成"
                            if result.success
                            else f"失败: {result.error}"
                        ),
                        "stats": result.stats,
                        "json_path": result.json_path,
                        "excel_path": result.excel_path,
                    }
                )
            # 保存文件名到 task_info.json (重启后能恢复)
            try:
                import json as _json
                ti = {"source_file": Path(file_path).name}
                with open(Path(output_dir) / "task_info.json", "w", encoding="utf-8") as tf:
                    _json.dump(ti, tf, ensure_ascii=False)
            except Exception:
                pass
    finally:
        # 清理
        with TASK_LOCK:
            CANCEL_FLAGS.pop(task_id, None)


# ============================================================================
# 入口
# ============================================================================
app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)