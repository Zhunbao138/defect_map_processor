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
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


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
        "max_tokens": 2048,
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
