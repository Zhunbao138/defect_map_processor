# -*- coding: utf-8 -*-
"""
提取 F7_F80_images/ 所有图片的检测参数 (Tesseract, 不使用 easyocr)
=====================================================================
关键思路:
1. 「材料尺寸」(如 12396×1859×17.27) 出现在左上角白底标注行
   "尺寸图 12396 x 1859 x 17.27"。
2. 「缺陷参数卡片」是一块**灰度均匀的中灰面板** (像素值 ~195-220),
   通过灰度连通域定位 —— 卡片背景深度一致, 与周围背景不同。
   卡片含: 缺陷中心X/Y, 缺陷长度/宽度/深度, 缺陷区域(面积), C扫描值。
3. 卡片可能在 F#_1 或 F#_2 任一图中, 两图都跑, 再按板材编号合并。

纯 OpenCV (读图/灰度/裁剪/二值化/连通域) + Tesseract (chi_sim+eng 读字)。
"""

from __future__ import annotations
import os, re, sys, json, time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np
import pandas as pd
import pytesseract

# ---------- Tesseract 路径 ----------
TESS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"D:\Program Files\Tesseract-OCR\tesseract.exe",
    r"D:\Tesseract-OCR\tesseract.exe",
]
for _c in TESS_CANDIDATES:
    if os.path.exists(_c):
        pytesseract.pytesseract.tesseract_cmd = _c
        break

# ---------- 路径 ----------
BASE       = Path(__file__).parent
IMAGE_DIR  = BASE / "F7_F80_images"
OUTPUT_DIR = BASE / "extract_results_card"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------- IO ----------
def imread_unicode(path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def crop_rel(img, x1, y1, x2, y2):
    h, w = img.shape[:2]
    return img[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]


# ---------- 预处理 ----------
def prep(gray, scale=3):
    """放大 + 锐化 + OTSU 二值化 (Tesseract 中英读字友好)."""
    h, w = gray.shape[:2]
    big = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(big, (3, 3), 0)
    sharp = cv2.addWeighted(big, 1.5, blur, -0.5, 0)
    _, binary = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(binary) > 127:          # 保证黑字白底
        binary = cv2.bitwise_not(binary)
    return binary


# ---------- OCR ----------
def ocr(img, psm=6, lang="chi_sim+eng") -> str:
    try:
        return pytesseract.image_to_string(img, lang=lang, config=f"--oem 3 --psm {psm}")
    except Exception as e:
        return f""


# ---------- 灰度均匀卡片面板定位 ----------
# 多个灰度带, 卡片中灰面板 ~195-220 最常见, 也覆盖其它色调
GRAY_BANDS = [(195, 220), (180, 200), (140, 175), (210, 230),
              (120, 150), (225, 245), (85, 115)]


def find_card_panels(gray):
    """返回所有候选均匀灰面板 bbox 列表 (x1,y1,x2,y2)。按面积降序。"""
    h, w = gray.shape[:2]
    cands = []
    for lo, hi in GRAY_BANDS:
        mask = cv2.inRange(gray, lo, hi)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1, n):
            x = stats[i, cv2.CC_STAT_LEFT]; y = stats[i, cv2.CC_STAT_TOP]
            ww = stats[i, cv2.CC_STAT_WIDTH]; hh = stats[i, cv2.CC_STAT_HEIGHT]
            ar = stats[i, cv2.CC_STAT_AREA]; fill = ar / (ww * hh)
            # 卡片约束: 较大、宽矩形、中上部、填充率高
            if not (ar > 15000 and fill > 0.45
                    and 0.35 * w < ww < 0.97 * w
                    and 0.06 * h < hh < 0.75 * h):
                continue
            cands.append((x, y, x + ww, y + hh, ar))
    cands.sort(key=lambda c: -c[4])          # 面积大的优先
    # 去重叠: 若被更大的面板大幅包含则丢弃 (保留最大、最完整那块)
    kept = []
    for c in cands:
        cx1, cy1, cx2, cy2, _ = c
        contained = False
        for k in kept:
            kx1, ky1, kx2, ky2, _ = k
            # 当前面板中心落在已保留面板内, 且面积 < 已保留 -> 跳过
            kcx, kcy = (kx1 + kx2) / 2, (ky1 + ky2) / 2
            if (kx1 <= cx1 and cy2 <= ky2 and cx2 <= kx2 and cy1 >= ky1):
                contained = True; break
        if not contained:
            kept.append(c)
    return kept


def _bin_for_card(card):
    """卡片二值化 → 黑字白底 (Tesseract 友好)。
    卡片底色均匀(常见 ~211), 文字可能是"比底色暗"或"比底色亮"两种。
    用 OCR 实读的数字个数来选 —— 哪版读出更多数字就是正确方向。"""
    mean = float(np.mean(card))
    inv = cv2.bitwise_not(card) if mean < 90 else card   # 黑底白字先反相
    dark = np.where(inv < 130, 0, 255).astype(np.uint8)   # 暗字
    light = np.where(inv > 225, 0, 255).astype(np.uint8)  # 亮字

    def _ndig(b):
        try:
            big = cv2.resize(b, (b.shape[1] * 3, b.shape[0] * 3),
                             interpolation=cv2.INTER_CUBIC)
            d = pytesseract.image_to_data(
                big, lang="chi_sim+eng", config="--oem 3 --psm 6",
                output_type=pytesseract.Output.DICT)
            return sum(1 for t in d["text"]
                       if t.strip() and re.fullmatch(r"[-+]?\d+\.?\d*", t.strip()))
        except Exception:
            return 0

    return dark if _ndig(dark) >= _ndig(light) else light


def _ocr_panel(card):
    """对单块卡片面板: 暗文字二值化 + 放大, psm6/4 各读一遍, 拼成文本。"""
    if card.shape[0] < 20 or card.shape[1] < 40:
        return ""
    b = _bin_for_card(card)
    big = cv2.resize(b, (b.shape[1] * 3, b.shape[0] * 3),
                     interpolation=cv2.INTER_CUBIC)
    return "\n".join([ocr(big, psm=6), ocr(big, psm=4)])


def _is_defect_panel(gray, panel):
    """判断该面板是否为缺陷参数卡片 (OCR 含缺陷关键字)。"""
    x1, y1, x2, y2, _ = panel
    card = gray[y1:y2, x1:x2]
    if card.shape[0] < 20 or card.shape[1] < 40:
        return False
    txt = _ocr_panel(card)
    return bool(re.search(r"中心\s*[XY]|缺陷|深度|长度|宽度|面积|区域", txt))


def get_card_text(gray):
    """定位卡片面板并 OCR; 合并所有含缺陷参数关键字的面板文本。

    关键: 不做激进去重 —— 重叠的子面板各自 OCR 出的文本互相补充
    (有的子面板读出标签, 有的读出数值), 全部拼起来再统一解析。
    """
    panels = find_card_panels(gray)
    texts = []
    for (x1, y1, x2, y2, _) in panels:
        card = gray[y1:y2, x1:x2]
        if card.size == 0 or card.shape[0] < 20 or card.shape[1] < 40:
            continue
        merged = _ocr_panel(card)
        # 只保留含缺陷参数关键字的面板 (丢弃纯坐标轴/图表面板)
        if re.search(r"中心\s*[XY]|缺陷|深度|长度|宽度|面积|区域", merged):
            texts.append(merged)
    return "\n".join(texts)


# ---------- 字段解析 ----------
NUM = r"[-+]?\d+\.?\d*"

def _first_num_after(text, label_re):
    m = re.search(label_re, text)
    if not m:
        return ""
    tail = text[m.start():]
    nums = re.findall(NUM, tail)
    # 取标签之后第一个纯数字 (标签本身可能含 X/Y 字母, 排除)
    for n in nums:
        if re.fullmatch(r"[-+]?\d+\.?\d*", n):
            return n
    return ""


def card_tokens(gray, bbox):
    """对卡片面板 image_to_data, 返回 [(y, x, text)] token 列表 (已按 y,x 排序)。
    用暗文字二值化 (与 _ocr_panel 一致) 保证 token 位置稳定。"""
    x1, y1, x2, y2 = bbox
    card = gray[y1:y2, x1:x2]
    if card.shape[0] < 20 or card.shape[1] < 40:
        return []
    b = _bin_for_card(card)
    big = cv2.resize(b, (b.shape[1] * 3, b.shape[0] * 3),
                     interpolation=cv2.INTER_CUBIC)
    try:
        d = pytesseract.image_to_data(big, lang="chi_sim+eng",
                                      config="--oem 3 --psm 6",
                                      output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    toks = []
    for i in range(len(d["text"])):
        t = d["text"][i].strip()
        if not t:
            continue
        toks.append((d["top"][i] // 3, d["left"][i] // 3, t))
    toks.sort()
    return toks


def _value_tokens(card, psm=6):
    """对卡片 image_to_data, 返回 [(y, x, value)] (仅纯数字 token)。"""
    b = _bin_for_card(card)
    big = cv2.resize(b, (b.shape[1] * 3, b.shape[0] * 3),
                     interpolation=cv2.INTER_CUBIC)
    try:
        d = pytesseract.image_to_data(big, lang="chi_sim+eng",
                                      config=f"--oem 3 --psm {psm}",
                                      output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    out = []
    for i in range(len(d["text"])):
        t = d["text"][i].strip()
        if re.fullmatch(r"[-+]?\d+\.?\d*", t):
            out.append((d["top"][i] // 3, d["left"][i] // 3, t))
    return out


def extract_card_positional(gray, panels):
    """位置法解析卡片 (主方法, 确定性)。

    卡片数值按 y 自上而下固定顺序:
        [X光标, Y光标, C扫描, 中心X, 中心Y, 长度, 宽度, 深度, 面积]   (9 个)
    数值都在同一"数值列" (冒号右侧, x 接近)。每个 y 行取该列最右数字为 value。
    得到 9 元序列后, 取索引 3-8 = [中心X, 中心Y, 长度, 宽度, 深度, 面积],
    索引 2 = C扫描。
    """
    res = {k: "" for k in
           ["缺陷中心X", "缺陷中心Y", "缺陷长度", "缺陷宽度", "缺陷深度",
            "缺陷面积", "C扫描值"]}

    # 候选卡片区域 = 灰度检测到的面板 + 一个固定卡片框 (兜底, 卡片位置高度稳定)。
    # 卡片常被分割线断成上下两段, 固定框能覆盖完整卡片。
    h_full, w_full = gray.shape[:2]
    # 候选: 检测到的面板 (按面积降序) + 固定卡片框 (兜底)
    cands = sorted(panels, key=lambda p: -p[4])
    cands.append((int(w_full * 0.295), int(h_full * 0.21),
                  int(w_full * 0.88), int(h_full * 0.67), 0))

    # 对每个候选区域裁出卡片、二值化、image_to_data 拿数值 token,
    # 选"数值列数字最多"的区域作为真正的卡片。
    # 一旦某候选读出 ≥6 个数值列数字 (已是完整卡片), 立即采用, 跳过其余候选。
    best_seq = None
    for p in cands:
        x1, y1, x2, y2, _ = p
        x1 = max(0, x1 - 4); y1 = max(0, y1 - 6)
        x2 = min(w_full, x2 + 4)
        y2 = min(h_full, max(y2 + 6, y1 + 470))
        card = gray[y1:y2, x1:x2]
        vtoks = _value_tokens(card)
        if len(vtoks) < 4:
            continue
        from collections import Counter
        buckets = [x // 8 * 8 for _, x, _ in vtoks]
        col_x = Counter(buckets).most_common(1)[0][0]
        col = [(y, x, t) for y, x, t in vtoks
               if abs((x // 8 * 8) - col_x) <= 20]
        if len(col) > (len(best_seq) if best_seq is not None else 0):
            best_seq = col
        if len(best_seq) >= 6:     # 完整卡片, 无需再试
            break
    if best_seq is None:
        return res
    vtoks = best_seq

    # 找"数值列" x = 出现最多的数字 token x (聚类到 8px 桶)
    from collections import Counter
    buckets = [x // 8 * 8 for _, x, _ in vtoks]
    col_x = Counter(buckets).most_common(1)[0][0]
    # 只保留数值列内的 token (±20px)
    col = [(y, x, t) for y, x, t in vtoks if abs((x // 8 * 8) - col_x) <= 20]

    # 每个 y 行取一个值 (最右), 按 y 排序 → 纯字符串序列
    rowv = {}
    for y, x, t in col:
        key = round(y / 12) * 12
        if key not in rowv or x > rowv[key][0]:
            rowv[key] = (x, t)
    seq = [rowv[k][1] for k in sorted(rowv)]

    # 序列按 y 排序, 末尾固定为 [长度, 宽度, 深度, 面积],
    # 往前是 [中心Y, 中心X, C扫描, Y光标, X光标] (前面若干行可能被裁掉)。
    # 先去明显噪声 (单个数字 / 带多个小数点的破碎值), 再从末尾锚定。
    def _clean(v):
        v = v.strip()
        return v if re.fullmatch(r"\d+\.?\d*", v) else None

    seq = [c for c in (_clean(s) for s in seq) if c is not None]

    # 完整卡片序列 (自上而下):
    #   [X光标, Y光标, C扫描, 中心X, 中心Y, 长度, 宽度, 深度, 面积]   (9 个)
    # 前 3 个"光标"行有时缺失。先用合理性判定顶部是否有光标行:
    #   索引2 若是小数(0-100) → 那是 C扫描, 说明顶部 3 个光标行齐全。
    n = len(seq)

    def is_cscan(v):
        try:
            return 0 < float(v) <= 100 and "." in v
        except Exception:
            return False

    start = 3          # 默认假设有完整光标行, 中心X 从索引3 开始
    if n >= 7 and not is_cscan(seq[2]):
        # 索引2 不是 C扫描 → 顶部光标行可能只有部分/缺失
        # 找第一个像 C扫描 (小数, 0-100) 的位置作为 C扫描, 其后两位是中心X/中心Y
        c_idx = next((i for i, v in enumerate(seq[:5]) if is_cscan(v)), None)
        if c_idx is not None:
            start = c_idx + 1
        else:
            start = max(0, n - 6)   # 无 C扫描 线索 → 取末尾 6 个为目标字段

    # 目标字段: 中心X, 中心Y, 长度, 宽度, 深度, 面积 依次取
    tgt = ["缺陷中心X", "缺陷中心Y", "缺陷长度", "缺陷宽度",
           "缺陷深度", "缺陷面积"]
    for i, key in enumerate(tgt):
        if start + i < n:
            res[key] = seq[start + i]
    # C扫描: 光标行齐全时是 seq[2]; 否则用识别到的 C扫描 位置
    if n >= 7 and is_cscan(seq[2]):
        res["C扫描值"] = seq[2]
    else:
        c_idx = next((i for i, v in enumerate(seq[:5]) if is_cscan(v)), None)
        if c_idx is not None:
            res["C扫描值"] = seq[c_idx]

    # ---- 合理性过滤: 清掉明显串位/不可信的值 ----
    def _fnum(v):
        try:
            return float(v)
        except Exception:
            return None

    # C扫描应在 [0, 100] (0.00 表示无缺陷, 合法)
    c = _fnum(res["C扫描值"])
    if c is None or not (0 <= c <= 100):
        res["C扫描值"] = ""
    # 长度/宽度/深度: 正常板材缺陷 单位 mm, 深<厚(常见<50), 长宽可达几千
    for k, hi in (("缺陷深度", 60),):
        v = _fnum(res[k])
        if v is None or v > hi or v <= 0:
            res[k] = ""
    for k in ("缺陷长度", "缺陷宽度"):
        v = _fnum(res[k])
        if v is None or v <= 0 or v > 10000:
            res[k] = ""
    # 面积: >0
    a = _fnum(res["缺陷面积"])
    if a is None or a <= 0 or a > 1e8:
        res["缺陷面积"] = ""
    return res


def parse_fields(text):
    """从合并文本中解析各字段。"""
    out = {"材料尺寸": "", "缺陷中心X": "", "缺陷中心Y": "",
           "缺陷长度": "", "缺陷宽度": "", "缺陷深度": "",
           "缺陷面积": "", "C扫描值": ""}
    if not text:
        return out

    # 材料尺寸: A×B×C (A,B 3-5位整数, C 可带小数, 分隔 × x X *)
    m = re.search(r"(\d{3,5})\s*[×xX*×·.．]\s*(\d{2,5})\s*[×xX*×·.．]\s*(\d{1,4}(?:\.\d+)?)",
                  text)
    if m:
        out["材料尺寸"] = f"{m.group(1)}×{m.group(2)}×{m.group(3)}"

    # 中心X / 中心Y : 多种写法 "缺陷中心X [mm] : 10251" / "中心X : 10251" / "X [mm] : 10251"
    for axis, key in (("X", "缺陷中心X"), ("Y", "缺陷中心Y")):
        pats = [
            rf"缺陷\s*中心\s*{axis}\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})",
            rf"中心\s*{axis}\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})",
            rf"\b{axis}\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})",
        ]
        for p in pats:
            m = re.search(p, text)
            if m:
                out[key] = m.group(1); break

    # 长度/宽度/深度/面积/区域
    label_map = {
        "缺陷长度": [r"缺陷\s*长\s*度", r"长\s*度"],
        "缺陷宽度": [r"缺陷\s*宽\s*度", r"宽\s*度"],
        "缺陷深度": [r"缺陷\s*深\s*度", r"深\s*度"],
    }
    for key, lbls in label_map.items():
        for lbl in lbls:
            p = rf"{lbl}\s*\[?\s*m+\s*\]?\s*[:：]\s*({NUM})"
            m = re.search(p, text)
            if m:
                out[key] = m.group(1); break

    # 面积/区域
    for lbl in [r"缺陷\s*面\s*积", r"面\s*积", r"缺陷\s*区\s*域", r"区\s*域"]:
        p = rf"{lbl}\s*\[?\s*m+\s*\]?\s*[:：]?\s*({NUM})"
        m = re.search(p, text)
        if m:
            out["缺陷面积"] = m.group(1); break

    # C扫描值
    for lbl in [r"C\s*扫\s*描\s*值", r"C\s*扫\s*描", r"扫\s*描"]:
        p = rf"{lbl}\s*\[?\s*%?\s*\]?\s*[:：]\s*({NUM})"
        m = re.search(p, text)
        if m:
            out["C扫描值"] = m.group(1); break

    return out


# ---------- 单图提取 ----------
def extract_one(path: Path) -> dict:
    name = path.name
    res = {"文件名": name}
    res.update({"材料尺寸": "", "缺陷中心X": "", "缺陷中心Y": "",
                "缺陷长度": "", "缺陷宽度": "", "缺陷深度": "",
                "缺陷面积": "", "C扫描值": "", "OCR片段": ""})
    try:
        img = imread_unicode(path)
        if img is None:
            res["OCR片段"] = "无法读取"; return res
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1) 材料尺寸: 左上角 "尺寸图 A×B×C" 行
        tl = crop_rel(gray, 0.0, 0.0, 0.62, 0.30)
        tl_bin = prep(tl, scale=3)
        text_tl = ocr(tl_bin, psm=6) + "\n" + ocr(tl_bin, psm=4)
        dim = ""
        m = re.search(r"(\d{3,5})\s*[×xX*]\s*(\d{2,5})\s*[×xX*]\s*(\d{1,4}(?:\.\d+)?)", text_tl)
        if m:
            dim = f"{m.group(1)}×{m.group(2)}×{m.group(3)}"

        # 2) 卡片 → 缺陷参数 (位置法为主)
        panels = find_card_panels(gray)
        pos = extract_card_positional(gray, panels)
        f = {k: pos.get(k, "") for k in
             ("缺陷中心X", "缺陷中心Y", "缺陷长度", "缺陷宽度",
              "缺陷深度", "缺陷面积", "C扫描值")}
        f["材料尺寸"] = dim

        res.update(f)
        res["OCR片段"] = ""
    except Exception as e:
        res["OCR片段"] = f"异常: {e}"
    return res


# ---------- 合并 _1/_2 ----------
FIELD_KEYS = ["材料尺寸", "缺陷中心X", "缺陷中心Y",
              "缺陷长度", "缺陷宽度", "缺陷深度", "缺陷面积", "C扫描值"]


def merge_rows(rows):
    """按板材编号 (F7,F10,...) 合并 _1/_2; 每字段取两图任一非空值。"""
    # 编号 -> {field: value}
    buckets = {}
    order = []
    for r in rows:
        m = re.match(r"(F\d+)", r["文件名"])
        if not m:
            continue
        plate = m.group(1)
        if plate not in buckets:
            buckets[plate] = {}
            order.append(plate)
        for k in FIELD_KEYS:
            v = r.get(k)
            v = "" if v is None else str(v).strip()
            if v and v != "nan" and k not in buckets[plate]:
                buckets[plate][k] = v
    merged = []
    for plate in order:
        rec = {"板材编号": plate}
        rec.update({k: buckets[plate].get(k, "") for k in FIELD_KEYS})
        merged.append(rec)
    return merged


def plate_sort_key(plate):
    return int(re.search(r"\d+", plate).group())


# ---------- Main ----------
def main(workers: int = 6, limit=None):
    paths = sorted([p for p in IMAGE_DIR.glob("*.png") if "_views" not in str(p)],
                   key=lambda p: (int(re.search(r"F(\d+)", p.name).group(1)),
                                   int(re.search(r"_(\d+)\.png", p.name).group(1))))
    if limit:
        paths = paths[:limit]
    print(f"找到 {len(paths)} 张图片")

    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(extract_one, p): p for p in paths}
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            if i % 20 == 0 or i == len(paths):
                dt = time.time() - t0
                print(f"  {i}/{len(paths)}  用时{dt:.1f}s")

    rows.sort(key=lambda r: (int(re.search(r"F(\d+)", r["文件名"]).group(1)),
                             int(re.search(r"_(\d+)\.png", r["文件名"]).group(1))))
    df_raw = pd.DataFrame(rows)

    merged = merge_rows(rows)
    merged.sort(key=lambda r: plate_sort_key(r["板材编号"]))
    df = pd.DataFrame(merged)

    csv  = OUTPUT_DIR / "F7_F80_merged.csv"
    xlsx = OUTPUT_DIR / "F7_F80_merged.xlsx"
    js   = OUTPUT_DIR / "F7_F80_merged.json"
    raw_csv = OUTPUT_DIR / "F7_F80_raw_per_image.csv"
    df.to_csv(csv, index=False, encoding="utf-8-sig")
    df.to_json(js, orient="records", force_ascii=False, indent=2)
    df_raw.to_csv(raw_csv, index=False, encoding="utf-8-sig")
    try:
        df.to_excel(xlsx, index=False, engine="openpyxl")
    except Exception as e:
        print(f"xlsx 写入失败: {e}")

    # 统计
    def cnt(col): return int(df[col].astype(bool).sum())
    print()
    print(f"[done] 合并后 {len(df)} 个板材")
    for k in FIELD_KEYS:
        print(f"  {k:8s}: {cnt(k)} / {len(df)}")
    print(f"\n合并 CSV:  {csv}")
    print(f"合并 XLSX: {xlsx}")
    print(f"原始每图:  {raw_csv}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(workers=6, limit=limit)
