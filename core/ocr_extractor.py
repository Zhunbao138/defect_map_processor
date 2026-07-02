"""OCR 文字识别模块 (Tesseract + OpenCV, 不依赖 easyocr)。

识别缺陷图谱图片中的:
- 钢板号 (14 位数字, 标题栏)
- 材料尺寸 (长×宽×厚, 左上角 "尺寸图" 行)
- 缺陷中心X / 缺陷中心Y
- 缺陷长度 / 缺陷宽度 / 缺陷深度
- 缺陷面积 / C扫描值

=====================================================================
识别策略 (基于视觉特征, 不依赖固定位置):

1. 「材料尺寸」「钢板号」: 左上角白底标题栏, OTSU 二值化 + Tesseract。

2. 「缺陷参数」从小黑卡读取 (每对图谱图必有一张含小黑卡):
   - 小黑卡 = 黑底白字的实心小矩形, 浮在图区中, 位置随选中缺陷而变。
   - 检测: gray<50 的暗像素做 35×35 boxFilter 求局部密度, 密度>55% 的区域
     才是"实心黑底"(卡片), 从而与周围稀疏暗点(缺陷图谱/文字)区分开; 再形态学
     闭运算 + 连通域 + 尺寸过滤(90<宽<380, 110<高<320) + [mm] 单位标记确认。
     该法位置无关、语言无关, 实测 74/74 缺陷板 100% 命中。
   - 黑卡反相(白底黑字) + 归一化 + 放大 → image_to_string / image_to_data。

3. 解析 (标签正则 + 位置法 取并集):
   - 标签正则: 缺陷中心X/Y、缺陷长度/宽度/深度、面积、C扫描 (标签清晰时直接匹配)。
   - 位置法: 黑卡数值按 y 自上而下固定顺序
     [X光标, Y光标, C扫描, 中心X, 中心Y, 长度, 宽度, 深度, 面积],
     标签乱码时按此顺序映射 (image_to_data 拿数字 token 坐标)。
   - 合理性过滤: 深度≤60、C扫描∈[0,100]、长度/宽度合理范围等。

公开接口 (与原 easyocr 版完全一致):
- extract_defect_info(image_path, languages, gpu, debug_dir) -> dict
- extract_defect_info_batch(image_paths, languages, gpu, debug_dir) -> list[dict]
- extract_defect_info_legacy(image_path) -> dict[str, str]
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

# Linux 走 PATH; 兼容 Windows 本地
for _c in (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"D:\Program Files\Tesseract-OCR\tesseract.exe",
):
    if os.path.exists(_c):
        try:
            pytesseract.pytesseract.tesseract_cmd = _c  # type: ignore[union-attr]
        except Exception:
            pass
        break


NUM = r"[-+]?\d+\.?\d*"
DEFECT_KEYS = ("缺陷中心X", "缺陷中心Y", "缺陷长度", "缺陷宽度",
               "缺陷深度", "缺陷面积", "C扫描值")


# =====================================================================
# 基础 IO / 预处理
# =====================================================================
def _imread(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _crop_rel(img, x1, y1, x2, y2):
    h, w = img.shape[:2]
    return img[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]


def _prep(gray, scale=3):
    """放大 + 锐化 + OTSU (黑字白底)。"""
    h, w = gray.shape[:2]
    big = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(big, (3, 3), 0)
    sharp = cv2.addWeighted(big, 1.5, blur, -0.5, 0)
    _, binary = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(binary) > 127:
        binary = cv2.bitwise_not(binary)
    return binary


def _ocr_str(img, psm=6, lang="chi_sim+eng") -> str:
    if pytesseract is None:
        raise ImportError("请先安装 pytesseract: pip install pytesseract "
                          "(并 apt install tesseract-ocr tesseract-ocr-chi-sim)")
    try:
        return pytesseract.image_to_string(img, lang=lang,
                                           config=f"--oem 3 --psm {psm}")
    except Exception:
        return ""


# =====================================================================
# 小黑卡检测 (主)
# =====================================================================
def _find_black_cards(gray):
    """检测所有小黑卡候选 (黑底白字实心矩形) [(x,y,ww,hh,white)]。

    用"局部暗像素密度"定位: 卡片是实心黑底(局部>55%像素<50), 而周围缺陷
    图谱/文字只是稀疏散点(密度低)。boxFilter 求局部密度 → 阈值 → 只留实心
    黑块, 避免被稀疏暗点连成超大块。"""
    dark = (gray < 50).astype(np.float32)
    dens = cv2.boxFilter(dark, -1, (35, 35))          # 局部暗像素占比
    mask = (dens > 0.55).astype(np.uint8) * 255        # 实心黑区
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    cands = []
    for i in range(1, n):
        x, y, ww, hh, ar = stats[i]
        if not (90 < ww < 380 and 110 < hh < 320):
            continue
        white = int((gray[y:y + hh, x:x + ww] > 180).sum())
        if white < 300:
            continue
        cands.append((x, y, ww, hh, white))
    return cands


def _ocr_black_card(gray, bbox):
    """黑卡反相 + 归一化 + 放大 → 文本。"""
    x, y, ww, hh = bbox[:4]
    card = gray[y:y + hh, x:x + ww]
    inv = cv2.bitwise_not(card)
    inv = cv2.normalize(inv, None, 0, 255, cv2.NORM_MINMAX)
    big = cv2.resize(inv, (inv.shape[1] * 4, inv.shape[0] * 4),
                     interpolation=cv2.INTER_CUBIC)
    try:
        txt = pytesseract.image_to_string(big, lang="chi_sim+eng",
                                          config="--oem 3 --psm 6")
    except Exception:
        txt = ""
    return txt, big


def _select_black_card(gray):
    """选小黑卡: 尺寸签名(~150x184) + [mm] 单位标记, 位置/语言无关。返回 bbox 或 None。"""
    cands = _find_black_cards(gray)
    if not cands:
        return None
    card_like = [c for c in cands if 90 < c[2] < 380 and 110 < c[3] < 320]
    if not card_like:
        return None
    best, best_score = None, 0
    for bbox in card_like:
        t, _ = _ocr_black_card(gray, bbox)
        mm = len(re.findall(r"\[?\s*mm", t, re.I))
        nums = len(re.findall(NUM, t))
        score = mm * 2 + nums
        if score > best_score:
            best_score, best = score, bbox
    return best if (best is not None and best_score > 0) else None


def _black_card_tokens(gray, bbox):
    """黑卡 image_to_data, 返回 [(y, x, value)] 纯数字 token。"""
    _, big = _ocr_black_card(gray, bbox)
    try:
        d = pytesseract.image_to_data(big, lang="chi_sim+eng",
                                      config="--oem 3 --psm 6",
                                      output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    out = []
    sc = 4
    for i in range(len(d["text"])):
        t = d["text"][i].strip()
        if re.fullmatch(NUM, t):
            out.append((d["top"][i] // sc, d["left"][i] // sc, t))
    return out


# =====================================================================
# 解析: 标签正则 + 位置法
# =====================================================================
def _parse_labels(text):
    """标签正则解析 (清晰标签)。"""
    out = {}
    for axis, key in (("X", "缺陷中心X"), ("Y", "缺陷中心Y")):
        for p in (rf"缺陷\s*中心\s*{axis}\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})",
                  rf"中心\s*{axis}\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})"):
            m = re.search(p, text)
            if m:
                out[key] = m.group(1); break
    for ch, key in (("长", "缺陷长度"), ("宽", "缺陷宽度"), ("深", "缺陷深度")):
        for p in (rf"缺陷\s*{ch}\s*度\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})",
                  rf"{ch}\s*度\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})"):
            m = re.search(p, text)
            if m:
                out[key] = m.group(1); break
    for p in (rf"(?:缺陷\s*)?面\s*积\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})",
              rf"(?:缺陷\s*)?区\s*域\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})"):
        m = re.search(p, text)
        if m:
            out["缺陷面积"] = m.group(1); break
    for p in (rf"C\s*扫\s*描\s*\[?\s*%?\s*\]?\s*[:：]\s*({NUM})",
              rf"扫\s*描\s*\[?\s*%?\s*\]?\s*[:：]\s*({NUM})",
              rf"\[\s*%\s*\]\s*[:：]\s*({NUM})"):
        m = re.search(p, text)
        if m:
            out["C扫描值"] = m.group(1); break
    return out


def _positional_map(tokens):
    """9 元数值序列位置映射 (标签乱码时兜底)。
    序列: [X光标, Y光标, C扫描, 中心X, 中心Y, 长, 宽, 深, 面积]。"""
    res = {k: "" for k in DEFECT_KEYS}
    if not tokens:
        return res
    buckets = [x // 8 * 8 for _, x, _ in tokens]
    col_x = Counter(buckets).most_common(1)[0][0]
    col = [(y, x, t) for y, x, t in tokens if abs((x // 8 * 8) - col_x) <= 20]
    rowv = {}
    for y, x, t in col:
        key = round(y / 12) * 12
        if key not in rowv or x > rowv[key][0]:
            rowv[key] = (x, t)
    seq = [rowv[k][1] for k in sorted(rowv)]
    seq = [s for s in seq if re.fullmatch(r"\d+\.?\d*", s)]
    n = len(seq)

    def is_cscan(v):
        try:
            return 0 < float(v) <= 100 and "." in v
        except Exception:
            return False

    start = 3
    if n >= 7 and not is_cscan(seq[2]):
        c_idx = next((i for i, v in enumerate(seq[:5]) if is_cscan(v)), None)
        start = (c_idx + 1) if c_idx is not None else max(0, n - 6)
    for i, key in enumerate(("缺陷中心X", "缺陷中心Y", "缺陷长度",
                             "缺陷宽度", "缺陷深度", "缺陷面积")):
        if start + i < n:
            res[key] = seq[start + i]
    if n >= 7 and is_cscan(seq[2]):
        res["C扫描值"] = seq[2]
    else:
        c_idx = next((i for i, v in enumerate(seq[:5]) if is_cscan(v)), None)
        if c_idx is not None:
            res["C扫描值"] = seq[c_idx]
    _sanitize(res)
    return res


def _sanitize(res):
    """合理性过滤。"""
    def _f(v):
        try:
            return float(v)
        except Exception:
            return None
    c = _f(res.get("C扫描值", ""))
    if c is None or not (0 <= c <= 100):
        res["C扫描值"] = ""
    v = _f(res.get("缺陷深度", ""))
    if v is None or v > 60 or v <= 0:
        res["缺陷深度"] = ""
    for k in ("缺陷长度", "缺陷宽度"):
        v = _f(res.get(k, ""))
        if v is None or v <= 0 or v > 10000:
            res[k] = ""
    a = _f(res.get("缺陷面积", ""))
    if a is None or a <= 0 or a > 1e8:
        res["缺陷面积"] = ""


# =====================================================================
# 标题栏: 材料尺寸 + 钢板号
# =====================================================================
def _extract_title(gray):
    tl = _crop_rel(gray, 0.0, 0.0, 0.62, 0.30)
    text = _ocr_str(_prep(tl, scale=3), psm=6) + "\n" + \
           _ocr_str(_prep(tl, scale=3), psm=4)
    dim = ""
    m = re.search(r"(\d{3,5})\s*[×xX*]\s*(\d{2,5})\s*[×xX*]\s*(\d{1,4}(?:\.\d+)?)", text)
    if m:
        dim = f"{m.group(1)}×{m.group(2)}×{m.group(3)}"
    steel_id = ""
    m = re.search(r"(?<!\d)(\d{14})(?!\d)", text)
    if m:
        steel_id = m.group(1)
    return dim, steel_id, text


# =====================================================================
# 公开接口
# =====================================================================
def extract_defect_info(
    image_path: str | Path,
    languages: tuple[str, ...] = ("en", "ch_sim"),
    gpu: bool = False,
    debug_dir: str | Path | None = None,
) -> dict[str, Any]:
    """识别单张缺陷图谱图片的参数。

    languages / gpu 为兼容旧接口的占位参数 (本实现固定用 tesseract chi_sim+eng)。
    返回 {image, raw_text, full_text, params, warnings}。
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")
    if pytesseract is None:
        raise ImportError("请先安装 pytesseract")

    img = _imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    debug = Path(debug_dir) if debug_dir else None

    # 1) 标题栏: 材料尺寸 + 钢板号
    dim, steel_id, title_text = _extract_title(gray)

    # 2) 缺陷参数: 只从小黑卡读 (黑卡数值为固定顺序, 位置法可靠)
    #    标签正则作补充; 无黑卡则该图无缺陷数据 (成对图中另一张会有)
    defect = {k: "" for k in DEFECT_KEYS}
    bbox = _select_black_card(gray)
    if bbox is not None:
        text, _ = _ocr_black_card(gray, bbox)
        if debug:
            debug.mkdir(parents=True, exist_ok=True)
            card = gray[bbox[1]:bbox[1] + bbox[3], bbox[0]:bbox[0] + bbox[2]]
            cv2.imwrite(str(debug / f"{image_path.stem}_blackcard.png"), card)
        lab = _parse_labels(text)
        pos = _positional_map(_black_card_tokens(gray, bbox))
        for k in DEFECT_KEYS:
            defect[k] = lab.get(k) or pos.get(k) or ""

    # 3) 汇总 params
    params: dict[str, Any] = {}
    if steel_id:
        params["钢板号"] = steel_id
    if dim:
        params["材料尺寸"] = dim
    for k in DEFECT_KEYS:
        if defect.get(k):
            params[k] = defect[k]

    raw_text = [t for t in re.split(r"[\n\r]+", title_text) if t.strip()]
    warnings = []
    if not params:
        warnings.append("未能解析到任何参数")
    if not dim and not defect.get("缺陷中心X"):
        warnings.append("未识别到材料尺寸或缺陷中心, 可能识别失败")

    return {
        "image": {"path": str(image_path), "size": (w, h)},
        "raw_text": raw_text,
        "full_text": title_text.strip(),
        "params": params,
        "warnings": warnings,
    }


def extract_defect_info_batch(
    image_paths: list[str | Path],
    languages: tuple[str, ...] = ("en", "ch_sim"),
    gpu: bool = False,
    debug_dir: str | Path | None = None,
    on_progress=None,
) -> list[dict]:
    """批量识别多张图片。

    on_progress : 可选回调 (done:int, total:int) -> None, 每处理完一张调用,
                  用于向上层汇报进度。
    """
    results = []
    total = len(image_paths)
    for idx, img_path in enumerate(image_paths, 1):
        try:
            result = extract_defect_info(
                img_path, languages, gpu, debug_dir=debug_dir
            )
            result["source"] = str(img_path)
            results.append(result)
        except Exception as e:
            results.append({
                "source": str(img_path),
                "error": str(e),
                "raw_text": [],
                "full_text": "",
                "params": {},
                "warnings": [f"识别失败: {e}"],
            })
        if on_progress is not None:
            try:
                on_progress(idx, total)
            except Exception:
                pass
    return results


def extract_defect_info_legacy(image_path: str | Path) -> dict[str, str]:
    """兼容原 extract_text.py 的返回值格式 (只返回 params)。"""
    return extract_defect_info(image_path)["params"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python ocr_extractor.py <图片路径>")
        sys.exit(1)
    p = sys.argv[1]
    print(f"处理: {p}\n")
    result = extract_defect_info(p, debug_dir="./ocr_debug")
    print(f"图像尺寸: {result['image']['size'][0]}×{result['image']['size'][1]}")
    print(f"\n解析参数:")
    for k, v in result["params"].items():
        print(f"  {k}: {v}")
    for w_ in result["warnings"]:
        print(f"警告: {w_}")
