"""LLM 识别模块 — 把图片发给本地大模型 (127.0.0.1:8080), 让它识别结构化数据.

接口与 cscan_ocr 的 ocr_defect_table / ocr_board_info 保持一致.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any


LLM_URL = "http://127.0.0.1:8080"  # 可改


def _image_to_base64(image_path: str | Path) -> str:
    """读图片, 压缩到 1024px 宽 JPEG, 返回 base64. 原图太大 LLM 会拒绝."""
    from PIL import Image
    import io
    im = Image.open(image_path)
    w, h = im.size
    if w > 1024:
        scale = 1024 / w
        im = im.resize((1024, int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    fmt = "JPEG" if im.mode == "RGB" else "PNG"
    im.save(buf, format=fmt, quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _call_llm(prompt: str, image_path: str | Path) -> str:
    """调用本地大模型, 传入图片 + 提示词, 返回原始文本响应."""
    import urllib.request

    b64 = _image_to_base64(image_path)
    body = json.dumps({
        "model": "default",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 10000,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"LLM_ERROR: {e}"


def llm_ocr_defect_table(image_path: str | Path) -> list[dict[str, Any]]:
    """用大模型识别 13 列缺陷表格."""
    prompt = """你是工业检测数据提取助手。请读取图片中的表格，提取每一行数据。

表格有13列：序号、X起始、X终止、X中点、X长度、Y起始、Y终止、Y中点、Y长度、面积、类型、深度、幅值。

请只返回一个 JSON 数组，每个元素是一行的数据。不要返回其他内容。
格式示例：[{"序号":18,"X起始":868.0,"X终止":971.0,...,"幅值":100.0}]"""
    try:
        raw = _call_llm(prompt, image_path)
        # 尝试从响应中提取 JSON
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return []
    except Exception:
        return []


def llm_ocr_board_info(image_path: str | Path) -> dict[str, Any]:
    """用大模型识别板信息 (板号/厚度/长度/宽度等)."""
    prompt = """你是工业检测数据提取助手。请读取图片中右下角的"板信息"面板，提取以下字段：
板号 (14位数字)、探伤代号、钢种、生产日期 (8位数字)、检测日期、标准号、厚度 (mm, 数字)、长度 (mm, 数字)、宽度 (mm, 数字)。

请只返回一个 JSON 对象，使用英文 key: plate_no, test_code, grade, prod_date, test_date, standard, thickness, length, width。
没有值的字段填 null。

示例：{"plate_no":"26302650370101","thickness":20.00,"length":12760,"width":2740,...}"""
    try:
        raw = _call_llm(prompt, image_path)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {}
    except Exception:
        return {}


# ============================================================
# 模板一 (zhongban) LLM 接口 — 与 cscan_ocr 的 extract_defect_info 对齐
# ============================================================
def llm_extract_defect_info(image_path: str | Path) -> dict[str, Any]:
    """用大模型从缺陷图谱中提取 6 项参数.

    返回格式: {"钢板号": ..., "材料尺寸": ..., "缺陷中心X": ..., ..., "raw_text": ..., "params": {...}}
    """
    prompt = """你是工业检测数据提取助手。从缺陷图谱图片中提取以下数据:

1. 钢板号: 14位数字
2. 材料尺寸: 格式如 "12000×2430×30"
3. 缺陷中心X (mm), 缺陷中心Y (mm)
4. 缺陷长度 (mm), 缺陷宽度 (mm), 缺陷深度 (mm)

请只返回一个 JSON 对象，用中文 key: "钢板号", "材料尺寸", "缺陷中心X", "缺陷中心Y", "缺陷长度", "缺陷宽度", "缺陷深度"。
没有值的填 null。"""
    try:
        raw = _call_llm(prompt, image_path)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {
                "钢板号": data.get("钢板号") or "",
                "材料尺寸": data.get("材料尺寸") or "",
                "缺陷中心X": str(data.get("缺陷中心X") or ""),
                "缺陷中心Y": str(data.get("缺陷中心Y") or ""),
                "缺陷长度": str(data.get("缺陷长度") or ""),
                "缺陷宽度": str(data.get("缺陷宽度") or ""),
                "缺陷深度": str(data.get("缺陷深度") or ""),
                "raw_text": [json.dumps(data, ensure_ascii=False)],
                "full_text": json.dumps(data, ensure_ascii=False),
                "params": {
                    "钢板号": data.get("钢板号") or "",
                    "材料尺寸": data.get("材料尺寸") or "",
                    "缺陷中心X": str(data.get("缺陷中心X") or ""),
                    "缺陷中心Y": str(data.get("缺陷中心Y") or ""),
                    "缺陷长度": str(data.get("缺陷长度") or ""),
                    "缺陷宽度": str(data.get("缺陷宽度") or ""),
                    "缺陷深度": str(data.get("缺陷深度") or ""),
                },
                "warnings": [],
            }
        return {"error": "no JSON found", "raw_text": [], "params": {}, "warnings": ["LLM 返回格式错误"]}
    except Exception as e:
        return {"error": str(e), "raw_text": [], "params": {}, "warnings": [f"LLM 调用失败: {e}"]}


def llm_extract_defect_info_batch(
    image_paths: list[str | Path],
    **kwargs,
) -> list[dict]:
    """批量 LLM 识别 (串行, 和 Tesseract 版接口一致)."""
    results = []
    total = len(image_paths)
    on_progress = kwargs.get("on_progress")
    for idx, p in enumerate(image_paths, 1):
        try:
            r = llm_extract_defect_info(p)
            r["source"] = str(p)
            results.append(r)
        except Exception as e:
            results.append({"source": str(p), "error": str(e), "raw_text": [], "params": {}, "warnings": [str(e)]})
        if on_progress:
            on_progress(idx, total)
    return results
