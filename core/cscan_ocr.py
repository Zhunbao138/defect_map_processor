"""cscan 文档处理模块 (中厚板卷厂).

- 提取 F/G 列原图 → 切出 4 个子图 (table / ascan / cscan / board) → 保存
- OCR 13 列缺陷表格 → 13 个字段每行
- OCR 板信息 panel → 板号/钢种/厚度/长度/宽度 等字段

复用 core/view_splitter.detect_and_crop_cscan_views 的算法.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook


# ============================================================
# 13 列缺陷表格列定义
# ============================================================
DEFECT_TABLE_COLS = (
    "序号", "X起始", "X终止", "X中点", "X长度",
    "Y起始", "Y终止", "Y中点", "Y长度",
    "面积", "类型", "深度", "幅值",
)


# ============================================================
# 单张原图切图 (包装 view_splitter.detect_and_crop_cscan_views)
# ============================================================
def split_cscan_views(
    image_path: str | Path,
    output_dir: str | Path,
    prefix: str = "",
) -> dict[str, Path]:
    """切出 cscan 原图里的 4 个子图, 加 prefix 前缀 (F/G) 保存.

    Args:
        image_path: 原图路径
        output_dir: 子图保存目录
        prefix: 文件名前缀 (如 "F" / "G", 留空则不加)

    Returns:
        {"table": Path, "ascan": Path, "cscan": Path, "board": Path, "warnings": [...]}
    """
    from .view_splitter import detect_and_crop_cscan_views

    image_path = Path(image_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = detect_and_crop_cscan_views(image_path, output_dir, draw_annotations=False)
    out: dict[str, Any] = {"warnings": result.get("warnings", [])}
    for en_name, src_path in result.get("views", {}).items():
        out[en_name] = Path(src_path)
    return out


# ============================================================
# 提取 F/G 列所有原图并切图
# ============================================================
def extract_cscan_from_xlsx(
    xlsx_path: str | Path,
    images_dir: str | Path,
) -> dict[int, dict[str, str]]:
    """从 cscan xlsx 的 5.1 sheet (索引 1) 提取 F/G 列原图, 切出 8 个子图/行.

    Returns:
        {
            row_idx: {
                "F_table": "path", "F_ascan": "path", "F_cscan": "path", "F_board": "path",
                "G_table": "path", "G_ascan": "path", "G_cscan": "path", "G_board": "path",
            },
            ...
        }
    """
    xlsx_path = Path(xlsx_path)
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    wb = load_workbook(str(xlsx_path), data_only=True)
    if len(wb.sheetnames) < 2:
        raise ValueError(
            f"cscan 文件至少需要 2 个 sheet, 当前 {len(wb.sheetnames)} 个: {wb.sheetnames}"
        )
    ws = wb[wb.sheetnames[1]]   # 5.1

    # 收集 F/G 列的所有图, 按 (row, col, sort) 排序
    targets = []
    for img_idx, img_obj in enumerate(ws._images):
        anchor = img_obj.anchor
        if not hasattr(anchor, "_from"):
            continue
        col_idx = anchor._from.col
        if col_idx not in (5, 6):     # F=5, G=6
            continue
        row_idx = anchor._from.row + 1   # 0-based → 1-based
        targets.append((row_idx, col_idx, img_idx, img_obj))

    targets.sort(key=lambda t: (t[0], t[1], t[2]))

    # 按行分组, 切图保存
    result: dict[int, dict[str, str]] = {}
    for row_idx, col_idx, img_idx, img_obj in targets:
        prefix = "F" if col_idx == 5 else "G"
        # 拿到原图字节, 写到临时文件 (view_splitter 需要文件路径)
        raw = img_obj._data()
        tmp_path = images_dir / f"_tmp_{prefix}_{row_idx:03d}_{img_idx}.png"
        tmp_path.write_bytes(raw)

        views = split_cscan_views(tmp_path, images_dir, prefix=prefix)

        row_dict = result.setdefault(row_idx, {})
        for en_name, src_path in views.items():
            if en_name == "warnings":
                continue
            src = Path(src_path)
            new_name = f"{prefix}_{en_name}-{row_idx:03d}{src.suffix}"
            new_path = images_dir / new_name
            if src != new_path:
                src.rename(new_path)
            row_dict[f"{prefix}_{en_name}"] = str(new_path)

        # 清理临时文件
        if tmp_path.exists():
            tmp_path.unlink()

    return result


# ============================================================
# OCR: 13 列缺陷表格
# ============================================================
def ocr_defect_table(table_image_path: str | Path) -> list[dict[str, Any]]:
    """对切出的 13 列缺陷表格子图跑 pytesseract, 提取行数据.

    Returns:
        [
            {"序号": 18, "X起始": 868.0, "X终止": 971.0, ..., "幅值": 100.0},
            ...
        ]
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return []

    table_image_path = Path(table_image_path)
    if not table_image_path.exists():
        return []

    img = Image.open(table_image_path)
    # 放大 2x 提升 OCR 准确率
    w, h = img.size
    if w < 1500:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)

    # 把彩色单元格(红/绿警告色) 转成黑字白底, 提升 OCR 准确率
    try:
        import numpy as np
        arr = np.array(img)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            # 取 max(R,G,B): 红色文字变深, 背景(白) 仍接近 255
            gray = arr.max(axis=2)
        else:
            gray = arr if arr.ndim == 2 else arr[..., 0]
        # 二值化: 文字 (暗) -> 黑 (0), 背景 (亮) -> 白 (255)
        bw = np.where(gray < 160, 0, 255).astype('uint8')
        # PIL 期望 L 模式 (灰度)
        from PIL import Image as _PILImage
        img = _PILImage.fromarray(bw, mode='L')
    except Exception:
        img = img.convert('L')

    try:
        data = pytesseract.image_to_data(
            img,
            lang="chi_sim+eng",
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
        )
    except Exception as e:
        return [{"error": f"OCR 失败: {e}"}]

    # 收集所有 numeric token (去掉汉字标签)
    items = []
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf < 30:
            continue
        t = text.replace(",", "").replace("，", "")
        try:
            float(t)
            items.append({
                "text": text,
                "value": float(t) if "." in t else int(t),
                "left": data["left"][i],
                "top": data["top"][i],
            })
        except ValueError:
            continue

    if not items:
        return []

    # 算法: 从 items 中找出每一条数据行.
    # 关键观察: 表头行在最上面 (Y 起始值 = 2733.3 之类), 实际数据行在表头下面.
    # 表里 "Y 起始/终止/中点" 列的值集中在头几列有大量相同值 (2733.3 等), 用于识别表头.
    # 用更稳的策略: 按 top 聚类, 然后每行按 left 排序, 找最长的那个数组 (≥13 个数字).
    items.sort(key=lambda x: (x["top"], x["left"]))

    # 按 top 间隔聚类 (60 px 容差, 表格行高约 60 px)
    clusters = []
    for it in items:
        if clusters and abs(clusters[-1][0]["top"] - it["top"]) < 60:
            clusters[-1].append(it)
        else:
            clusters.append([it])

    # 找每行 cluster 中前 13 个数值
    results = []
    for cluster in clusters:
        # 按 left 排序 (行内的列顺序)
        cluster.sort(key=lambda x: x["left"])
        # 去重 (OCR 偶尔把同一数字拆成两个 token, left < 5 px 视为重复)
        deduped = []
        for it in cluster:
            if deduped and abs(it["left"] - deduped[-1]["left"]) < 5:
                continue
            deduped.append(it)
        vals = [it["value"] for it in deduped]
        if len(vals) < 13:
            continue
        nums = vals[:13]
        row = {"序号": int(nums[0])}
        for col_name, val in zip(DEFECT_TABLE_COLS[1:], nums[1:13]):
            row[col_name] = val
        results.append(row)

    return results


# ============================================================
# OCR: 板信息 panel
# ============================================================
BOARD_LABELS = {
    "板号": "plate_no",
    "探伤代号": "test_code",
    "钢种": "grade",
    "生产日期": "prod_date",
    "检测日期": "test_date",
    "标准号": "standard",
    "厚度": "thickness",
    "长度": "length",
    "宽度": "width",
}


def ocr_board_info(board_image_path: str | Path) -> dict[str, Any]:
    """识别板信息 panel, 返回 {plate_no, test_code, grade, thickness, length, width, ...}."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return {}

    board_image_path = Path(board_image_path)
    if not board_image_path.exists():
        return {}

    img = Image.open(board_image_path)
    # 放大提升 OCR 准确率
    w, h = img.size
    if w < 600:
        img = img.resize((w * 3, h * 3), Image.LANCZOS)

    try:
        # psm=6 (assume single block) 把每行作为一个 block,
        # 但每行的 token 都在 block_num=1, 用 top 区分行
        data = pytesseract.image_to_data(
            img, lang="chi_sim+eng",
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
        )
    except Exception:
        return {}

    # 收集所有 token
    items = []
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf < 30:
            continue
        items.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
        })

    if not items:
        return {}

    # 按 top 分组 (同一行的 token top 接近, ±20px 合并)
    items.sort(key=lambda x: (x["top"], x["left"]))
    rows: list[list[dict]] = []
    for it in items:
        if rows and abs(rows[-1][0]["top"] - it["top"]) < 25:
            rows[-1].append(it)
        else:
            rows.append([it])
    # 每行内按 left 排序
    for r in rows:
        r.sort(key=lambda x: x["left"])

    # 按 left 排序每行
    result: dict[str, Any] = {}
    for row in rows:
        # 找 label (BOARD_LABELS 里的)
        label_idx = -1
        label_key = None
        for idx, w in enumerate(row):
            lk = w["text"].replace("号", "").replace(":", "").replace("：", "")
            if lk in BOARD_LABELS:
                label_idx = idx
                label_key = lk
                break
        if label_idx < 0:
            continue
        # 拼 label 之后的 token 作为 value
        value_tokens = [w["text"] for w in row[label_idx + 1:]]
        value = "".join(value_tokens).strip()
        # 去掉可能的 [mm]/[单位] 后缀
        import re as _re
        value = _re.sub(r"\[[a-z]+\]:?", "", value).strip()
        # 尝试解析为数字
        try:
            v = float(value)
            if v == int(v):
                v = int(v)
            value = v
        except (ValueError, TypeError):
            pass
        result[BOARD_LABELS[label_key]] = value

    return result
