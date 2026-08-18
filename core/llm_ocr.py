"""LLM 识别模块 — 把图片发给本地大模型 (127.0.0.1:8080), 让它识别结构化数据.

接口与 cscan_ocr 的 ocr_defect_table / ocr_board_info 保持一致.
"""
from __future__ import annotations

import base64
import http.client
import json
import re
import time
from pathlib import Path
from typing import Any


LLM_URL = "http://127.0.0.1:8080"  # 可改

# 持久 HTTP 连接 (复用避免每次 TCP 握手)
_llm_conn: http.client.HTTPConnection | None = None


def _get_conn() -> http.client.HTTPConnection:
    global _llm_conn
    if _llm_conn is None:
        _llm_conn = http.client.HTTPConnection("127.0.0.1", 8080, timeout=120)
    return _llm_conn


def _reset_conn():
    """连接断开时重置."""
    global _llm_conn
    if _llm_conn:
        try:
            _llm_conn.close()
        except Exception:
            pass
    _llm_conn = None


def _image_to_base64(image_path: str | Path) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_llm(prompt: str, image_path: str | Path, retries: int = 3,
             prefill: str = "") -> str:
    """调用本地大模型. prefill 预填 assistant 回复以跳过 Qwen 思考块."""
    b64 = _image_to_base64(image_path)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]
    if prefill:
        messages.append({"role": "assistant", "content": prefill})
    body = json.dumps({
        "model": "default",
        "messages": messages,
        "max_tokens": 10000,
        "temperature": 0,
    }).encode("utf-8")

    for attempt in range(retries):
        try:
            conn = _get_conn()
            conn.request(
                "POST", "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json", "Connection": "keep-alive"},
            )
            resp = conn.getresponse()
            raw_body = resp.read().decode("utf-8")
            result = json.loads(raw_body)
            raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if raw and raw.strip():
                return raw
            # 空响应 → 重置连接后重试
            _reset_conn()
            if attempt < retries - 1:
                time.sleep(2)
        except (http.client.HTTPException, ConnectionError, OSError, TimeoutError) as e:
            _reset_conn()  # 连接坏了, 下次重建
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return f"LLM_ERROR: {e}"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return f"LLM_ERROR: {e}"
    return ""


def _image_has_content(image_path: str | Path) -> bool:
    """检测图片是否包含有意义的内容 (暗像素 > 1.5%)."""
    try:
        import cv2, numpy as np
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None: return False
        return (img < 128).mean() > 0.015
    except Exception:
        return True  # 读不了就当有内容


def llm_ocr_defect_table(image_path: str | Path) -> list[dict[str, Any]]:
    """用大模型识别 13 列缺陷表格.

    返回空列表时检查图片: 若图片有内容但 LLM 未识别, 返回警告标记.
    """
    prompt = "提取表格每行: 序号,X起始,X终止,X中点,X长度,Y起始,Y终止,Y中点,Y长度,面积,类型,深度,幅值。只返回JSON数组。"
    try:
        raw = _call_llm(prompt, image_path, prefill="[")
        # LLM 有时返回 "100." 这样的非法 JSON, 补 0
        raw = re.sub(r'(?<!\d)(\d+)\.(?!\d)', r'\1.0', raw)
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            last_complete = re.search(r"(\[.*\})", raw, re.DOTALL)
            if last_complete:
                raw = last_complete.group(1) + "]"
                m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            rows = json.loads(m.group(0))
            result = []
            for r in rows:
                if isinstance(r, dict):
                    if str(r.get("序号", "")).strip().isdigit():
                        result.append(r)
                elif isinstance(r, list):
                    if len(r) >= 10 and str(r[0]).strip().isdigit():
                        result.append(dict(zip(DEFECT_TABLE_COLS, r)))
            if result:
                return result
            # JSON 解析成功但全是表头/无效行 → 图片可能无数据, 不标记

        # LLM 未返回有效数据 → 检查图片是否有内容
        if _image_has_content(image_path):
            return [{"warning": "LLM 识别失败，图片有内容但未读出"}]
        return []
    except Exception:
        return []


def llm_ocr_board_info(image_path: str | Path) -> dict[str, Any]:
    """用大模型识别板信息 (板号/厚度/长度/宽度等)."""
    prompt = "提取板信息: plate_no,test_code,grade,prod_date,test_date,standard,thickness,length,width。只返回JSON。"
    try:
        raw = _call_llm(prompt, image_path, prefill="{")
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {}
    except Exception:
        return {}


# ============================================================
# 模板一 (zhongban) LLM 接口 — 与 cscan_ocr 的 extract_defect_info 对齐
# ============================================================
def _extract_json(raw: str) -> dict | None:
    """从 LLM 原始响应中提取 JSON 对象, 兼容 markdown 代码块、前后多余文本."""
    if not raw or raw.startswith("LLM_ERROR"):
        return None
    # 去掉 markdown 代码块包裹 (先取代码块内容)
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if m:
        cleaned = m.group(1)
    else:
        cleaned = raw
    # 优先精确匹配含 "钢板号" 的 JSON 对象
    m = re.search(r'\{[^{}]*"钢板号"[^{}]*\}', cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # fallback: 非贪婪匹配任意 JSON 对象
    m = re.search(r'\{.*?\}', cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # 最后尝试贪婪匹配
    m = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def llm_extract_defect_info(image_path: str | Path) -> dict[str, Any]:
    """用大模型从缺陷图谱中提取 6 项参数.

    返回格式: {"钢板号": ..., "材料尺寸": ..., "缺陷中心X": ..., ..., "raw_text": ..., "params": {...}}
    """
    prompt = (
        "分析这张钢材缺陷图谱。左上角标题栏有钢板号(14位数字)和材料尺寸(如12000×2430×30)。"
        "图中可能还有一块黑底白字的小卡片写着缺陷参数(中心X/Y、长度/宽度/深度, mm)。\n\n"
        "规则:\n"
        "1. 缺陷参数必须且只能从黑底白字小卡片读取，不可用图中其他位置的数字\n"
        "2. 若图中没有黑底白字卡片→缺陷参数全部设为\"\"(空字符串, 不要填N/A/None等占位)\n"
        "3. 钢板号和材料尺寸从左上角标题栏读\n"
        "4. 只输出纯JSON，不要markdown/```/解释文字。"
        "格式:{\"钢板号\":\"\",\"材料尺寸\":\"\",\"缺陷中心X\":\"\","
        "\"缺陷中心Y\":\"\",\"缺陷长度\":\"\",\"缺陷宽度\":\"\",\"缺陷深度\":\"\"}"
    )
    try:
        raw = _call_llm(prompt, image_path, prefill="{")
        data = _extract_json(raw)
        if data:
            p = {
                "钢板号": str(data.get("钢板号", "") or "").strip(),
                "材料尺寸": str(data.get("材料尺寸", "") or "").strip(),
                "缺陷中心X": str(data.get("缺陷中心X", "") or "").strip(),
                "缺陷中心Y": str(data.get("缺陷中心Y", "") or "").strip(),
                "缺陷长度": str(data.get("缺陷长度", "") or "").strip(),
                "缺陷宽度": str(data.get("缺陷宽度", "") or "").strip(),
                "缺陷深度": str(data.get("缺陷深度", "") or "").strip(),
            }
            return {
                **p,
                "raw_text": [json.dumps(data, ensure_ascii=False)],
                "full_text": json.dumps(data, ensure_ascii=False),
                "params": p,
                "warnings": [],
            }
        return {"error": "no JSON found", "raw_text": [raw], "params": {}, "warnings": ["LLM 返回格式错误"]}
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
