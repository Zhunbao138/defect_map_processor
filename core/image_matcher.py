"""图片与记录智能关联模块。

xls 文件中的图片没有明确的行-图片映射信息。需要通过启发式方法关联:

策略 1: 文件名约定
    如果图片命名为 row_007_img_1.png, row_007_img_2.png 等,可直接对应到行
策略 2: 文件夹命名约定
    图片放在 records/26102421340201/ 文件夹中,文件夹名是钢板号
策略 3: 钢板号前缀匹配
    如果图片元数据中包含钢板号或类似标识
策略 4: 顺序分配 (最后手段)
    按顺序将图片分配给有图片的记录
策略 5: 模板识别
    通过图片 OCR 识别钢板号 (材料尺寸里包含)

提供手动指定 API,允许用户在前端拖拽/上传后绑定。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def match_images_to_records(
    images: list[dict],
    records: list[dict],
    strategy: str = "order",
) -> dict[int, list[dict]]:
    """将图片关联到记录。

    Parameters
    ----------
    images : list[dict]
        图片列表, 每项含 row_index (可能为 None), file_path, image_index
    records : list[dict]
        记录列表, 每项含 row_index
    strategy : str
        关联策略:
        - "order": 按顺序分配给所有有图片的记录
        - "by_row": 按 row_index 精确匹配
        - "by_filename": 按文件名解析 row_index
        - "by_folder": 按文件夹名匹配钢板号

    Returns
    -------
    dict[int, list[dict]]
        {row_index: [image, ...]}
    """
    # 过滤有 row_index 的图片
    images_with_row = [img for img in images if img.get("row_index") is not None]
    images_without_row = [img for img in images if img.get("row_index") is None]

    result: dict[int, list[dict]] = {}

    if strategy == "by_row":
        for img in images_with_row:
            row = img["row_index"]
            result.setdefault(row, []).append(img)

    elif strategy == "by_filename":
        for img in images:
            row = _parse_row_from_filename(img["file_path"])
            if row is not None:
                result.setdefault(row, []).append(img)

    elif strategy == "by_folder":
        for img in images:
            row = _parse_row_from_folder(img["file_path"], records)
            if row is not None:
                result.setdefault(row, []).append(img)

    elif strategy == "order":
        # 按顺序分配: 每行最多 2 张图
        # 优先取有 row_index 的图, 然后填充无 row_index 的图
        record_indices = [r["row_index"] for r in records if r.get("钢板号")]

        idx = 0
        for img in images_with_row + images_without_row:
            if idx >= len(record_indices):
                break
            row = record_indices[idx]
            result.setdefault(row, []).append(img)
            if len(result[row]) >= 2:
                idx += 1

    else:
        raise ValueError(f"未知策略: {strategy}")

    return result


def _parse_row_from_filename(file_path: str) -> int | None:
    """从文件名解析行号。
    支持的格式:
        row_007_img_1.png
        row7_1.png
        缺陷图谱_行7_图1.png
    """
    path = Path(file_path)
    name = path.stem

    # row_007 / row7
    m = re.search(r"row[_\-]?(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 行7
    m = re.search(r"行[_\-]?(\d+)", name)
    if m:
        return int(m.group(1))

    # r07
    m = re.search(r"\br[_\-]?(\d+)\b", name, re.IGNORECASE)
    if m:
        return int(m.group(1))

    return None


def _parse_row_from_folder(file_path: str, records: list[dict]) -> int | None:
    """从文件夹名匹配钢板号。"""
    path = Path(file_path)
    parent_name = path.parent.name  # 例如 26102421340201

    for rec in records:
        plate_no = rec.get("钢板号", "").strip()
        if plate_no and plate_no in parent_name:
            return rec.get("row_index")

    return None


def match_by_plate_no(
    image_ocr_text: str,
    records: list[dict],
) -> int | None:
    """通过 OCR 文本中的钢板号匹配记录。"""
    if not image_ocr_text:
        return None

    for rec in records:
        plate_no = rec.get("钢板号", "").strip()
        if plate_no and plate_no in image_ocr_text:
            return rec.get("row_index")
    return None


def suggest_image_assignments(
    images: list[dict],
    records: list[dict],
    max_per_row: int = 2,
) -> list[dict]:
    """生成图片分配建议,供前端展示给用户手动确认。

    返回每个建议分配:
    {
        "image": image_info,
        "suggested_row": int | None,
        "reason": str,    # 为什么这样分配
        "alternatives": list[int],  # 其他可能行
    }
    """
    matched = match_images_to_records(images, records, strategy="order")
    suggestions = []

    for img in images:
        # 查找当前分配
        current_row = None
        for row, imgs in matched.items():
            if any(i["file_path"] == img["file_path"] for i in imgs):
                current_row = row
                break

        # 计算备选
        alternatives = list(matched.keys())[:5]

        suggestions.append(
            {
                "image": img,
                "suggested_row": current_row,
                "reason": "按顺序自动分配" if current_row else "未分配",
                "alternatives": alternatives,
            }
        )

    return suggestions