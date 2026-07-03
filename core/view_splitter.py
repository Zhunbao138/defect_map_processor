"""图片三视图切分模块。

封装原 extract_black_border.py 的逻辑为函数形式：
- 俯视图 (1_top)
- 长边方向侧视图 (2_long)
- 短边方向侧视图 (3_short)

输入：单张缺陷图谱图片
输出：3张切分后的视图图片 + 1张带标注的预览图
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def detect_and_crop_ultrasonic_views(
    image_path: str | Path,
    output_dir: str | Path | None = None,
    draw_annotations: bool = True,
) -> dict[str, Any]:
    """检测并截取超声图像中的三个视图。

    算法 (与 extract_black_border.py 一致):
    1. 灰度化 + threshold(100) 找深色区域
    2. 形态学闭运算填白点
    3. 找连通矩形 (w*h >= 10000)
    4. 俯视图: y 最小、面积最大的矩形
    5. 长边侧视图: 在俯视图下方, 宽度相近
    6. 短边侧视图: 在俯视图右侧, 高度相近

    Parameters
    ----------
    image_path : str | Path
        输入图片路径
    output_dir : str | Path | None
        输出目录, 默认为图片所在目录下创建 <stem>_views 子目录
    draw_annotations : bool
        是否在图片上绘制检测到的视图边框

    Returns
    -------
    dict
        {
            "image": {"path": str, "size": (w, h)},
            "views": {
                "1-俯视图": str,
                "2-长边侧视图": str,
                "3-短边侧视图": str,
            },
            "annotated": str | None,
            "warnings": list[str],
        }
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")

    img_h, img_w = img.shape[:2]

    # ---------- 预处理: 提取黑色边框 ----------
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # ---------- 查找并筛选有效矩形 ----------
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w * h < 10000:
            continue
        rects.append({"x": x, "y": y, "w": w, "h": h, "area": w * h, "aspect": w / h})

    rects.sort(key=lambda r: r["area"], reverse=True)

    # ---------- 分类三个视图 ----------
    # 俯视图: y 最小、面积最大的矩形
    # 长边侧视图: 在俯视图下方, 宽度与俯视图接近
    # 短边侧视图: 在俯视图右侧, 高度与俯视图接近
    view_top, view_long, view_short = None, None, None

    top_candidates = [r for r in rects if r["y"] < img_h * 0.6]
    if top_candidates:
        view_top = top_candidates[0]

    if view_top:
        long_cands = [
            r for r in rects
            if r["y"] > view_top["y"] + view_top["h"] * 0.5
            and abs(r["w"] - view_top["w"]) < view_top["w"] * 0.3
        ]
        if long_cands:
            view_long = max(long_cands, key=lambda r: r["area"])

        short_cands = [
            r for r in rects
            if r["x"] > view_top["x"] + view_top["w"] * 0.5
            and abs(r["h"] - view_top["h"]) < view_top["h"] * 0.3
        ]
        if short_cands:
            view_short = max(short_cands, key=lambda r: r["h"] / r["w"])

    # ---------- 准备输出目录 ----------
    out_dir = (
        Path(output_dir)
        if output_dir
        else image_path.parent / f"{image_path.stem}_views"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    views = [
        (view_top, "1_top", "1-俯视图", (0, 0, 255)),
        (view_long, "2_long", "2-长边侧视图", (0, 200, 0)),
        (view_short, "3_short", "3-短边侧视图", (255, 0, 0)),
    ]

    saved = {}
    warnings = []

    for view_dict, en_name, label, color in views:
        if view_dict is None:
            warnings.append(f"未检测到 {label}")
            continue
        x, y, w, h = (
            view_dict["x"],
            view_dict["y"],
            view_dict["w"],
            view_dict["h"],
        )
        cropped = img[y : y + h, x : x + w]
        output_path = out_dir / f"{image_path.stem}_{en_name}.png"
        cv2.imwrite(str(output_path), cropped)
        saved[label] = str(output_path)

    # ---------- 绘制标注 ----------
    annotated_path = None
    if draw_annotations:
        annotated = img.copy()
        for view_dict, en_name, label, color in views:
            if view_dict is None:
                continue
            x, y, w, h = (
                view_dict["x"],
                view_dict["y"],
                view_dict["w"],
                view_dict["h"],
            )
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 4)
            # 标签
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)
            cv2.rectangle(
                annotated,
                (x, y - label_size[1] - 10),
                (x + label_size[0] + 10, y),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (x + 5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (255, 255, 255),
                2,
            )
        annotated_path = out_dir / f"{image_path.stem}_annotated.png"
        cv2.imwrite(str(annotated_path), annotated)

    return {
        "image": {"path": str(image_path), "size": (img_w, img_h)},
        "views": saved,
        "annotated": str(annotated_path) if annotated_path else None,
        "warnings": warnings,
    }


def split_multiple_images(
    image_paths: list[str | Path],
    output_root: str | Path,
    draw_annotations: bool = True,
) -> list[dict]:
    """批量切分多张图片。

    每张图片单独输出到 output_root/<image_stem>/
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    results = []
    success = 0
    fail = 0
    for img_path in image_paths:
        try:
            result = detect_and_crop_ultrasonic_views(
                img_path,
                output_dir=output_root / Path(img_path).stem,
                draw_annotations=draw_annotations,
            )
            result["source"] = str(img_path)
            results.append(result)
            success += 1
        except Exception as e:
            results.append(
                {"source": str(img_path), "error": str(e), "views": {}}
            )
            fail += 1

    return {
        "results": results,
        "success": success,
        "fail": fail,
        "total": len(image_paths),
    }


# ============================================================================
# 兼容原 extract_black_border.py 接口
# ============================================================================
def detect_and_crop_ultrasonic_views_legacy(image_path, output_dir=None):
    """兼容原 extract_black_border.py 的返回值格式 (saved_dict, out_dir)。"""
    result = detect_and_crop_ultrasonic_views(image_path, output_dir)
    return result["views"], Path(image_path).parent / f"{Path(image_path).stem}_views"


# ============================================================================
# cscan 模式: 复用矩形检测, 但输出标签改为 table / ascan / cscan
# ============================================================================
# cscan 类型 xlsx 里的每张原图内部布局:
#   ┌──────────────┬─────────┐
#   │              │         │
#   │  13列缺陷表格  │  A 扫   │  ← top=table (左上), short=ascan (右上)
#   │              │         │
#   ├──────────────┴─────────┤
#   │         C 扫            │  ← long=cscan (下面)
#   └────────────────────────┘
# 复用 detect_and_crop_ultrasonic_views 的算法, 只换标签.

def detect_and_crop_cscan_views(
    image_path: str | Path,
    output_dir: str | Path | None = None,
    draw_annotations: bool = True,
) -> dict[str, Any]:
    """检测并截取 cscan 图像中的 3 个区域 (table / ascan / cscan).

    cscan 类型原图布局 (4 个黑色矩形, 按象限分类):
      ┌─────────────────┬──────────┐
      │  13列缺陷表格     │  A 扫    │  ← TR = table (小), BR = ascan (右)
      │  (TR)            │  (BR)    │
      ├─────────────────┴──────────┤
      │  C 扫结果图 (BL, 最大)        │  ← BL = cscan
      │  + 板信息面板 (BL 右下)        │
      └──────────────────────────────┘

    算法: 找黑色矩形, 按象限分类:
    - table  = TR 象限 (x > w/2, y < h/3) 面积最大的
    - cscan  = BL 象限 (x < w/2) 面积最大的
    - ascan  = BR 象限 (x > w/2, y > h/3) 面积最大的 (即右侧的 A 扫图)
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")

    img_h, img_w = img.shape[:2]

    # ---------- 预处理: cscan 表格有浅色边框, 用 threshold=200 捕获 ----------
    # (对比 detect_and_crop_ultrasonic_views 的 100: 那个找深色实心区域, 适用于三视图)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w * h < 10000:
            continue
        cx, cy = x + w / 2, y + h / 2
        # 象限: TL/TR/BL/BR (用图像中心和水平中线分)
        if cx < img_w * 0.5 and cy < img_h * 0.5:
            quad = "TL"
        elif cx >= img_w * 0.5 and cy < img_h * 0.5:
            quad = "TR"
        elif cx < img_w * 0.5 and cy >= img_h * 0.5:
            quad = "BL"
        else:
            quad = "BR"
        rects.append({
            "x": x, "y": y, "w": w, "h": h, "area": w * h, "aspect": w / h,
            "cx": cx, "cy": cy, "quad": quad,
        })

    # 按象限分类: 取每个象限里面积最大的矩形
    by_quad: dict[str, list[dict]] = {"TL": [], "TR": [], "BL": [], "BR": []}
    for r in rects:
        by_quad[r["quad"]].append(r)

    # table 在 TL (左上, 浅色边框表格)
    view_table = max(by_quad["TL"], key=lambda r: r["area"]) if by_quad["TL"] else None
    # cscan 在 BL (左下, C 扫大图)
    view_cscan = max(by_quad["BL"], key=lambda r: r["area"]) if by_quad["BL"] else None
    # ascan 在 TR (右上, A 扫波形)
    view_ascan = max(by_quad["TR"], key=lambda r: r["area"]) if by_quad["TR"] else None
    # 板信息 panel: 用固定裁剪, 在右下角 (其实际位置不在 threshold 找到的矩形里)
    # 经验值: 距右边 0~5%, 距底边 0~25%, 高度 25%
    # 简化: 整个 image 右下 25%x25% 区域就是 板信息
    view_board = {
        "x": int(img_w * 0.78),
        "y": int(img_h * 0.7),
        "w": int(img_w * 0.22),
        "h": int(img_h * 0.3),
        "area": 0,
    }

    # ---------- 输出目录 ----------
    out_dir = (
        Path(output_dir)
        if output_dir
        else image_path.parent / f"{image_path.stem}_views"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # cscan 业务标签 (3 个区域, 去掉 board)
    views = [
        (view_table, "table",  "13列缺陷表格 (左上)", (0, 0, 255)),
        (view_cscan, "cscan",  "C 扫 (左下)",         (0, 200, 0)),
        (view_ascan, "ascan",  "A 扫 (右上)",         (255, 0, 0)),
    ]

    saved = {}
    warnings = []

    for view_dict, en_name, label, color in views:
        if view_dict is None:
            warnings.append(f"未检测到 {label}")
            continue
        x, y, w, h = (
            view_dict["x"], view_dict["y"],
            view_dict["w"], view_dict["h"],
        )
        # 加 15px 外边距, 避免切掉边缘信息; 限制不超出原图
        MARGIN = 15
        x0 = max(0, x - MARGIN)
        y0 = max(0, y - MARGIN)
        x1 = min(img_w, x + w + MARGIN)
        y1 = min(img_h, y + h + MARGIN)
        cropped = img[y0:y1, x0:x1]
        output_path = out_dir / f"{image_path.stem}_{en_name}.png"
        cv2.imwrite(str(output_path), cropped)
        saved[en_name] = str(output_path)

    # ---------- 标注图 ----------
    annotated_path = None
    if draw_annotations:
        annotated = img.copy()
        for view_dict, en_name, label, color in views:
            if view_dict is None:
                continue
            x, y, w, h = (
                view_dict["x"], view_dict["y"],
                view_dict["w"], view_dict["h"],
            )
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 4)
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)
            cv2.rectangle(
                annotated,
                (x, y - label_size[1] - 10),
                (x + label_size[0] + 10, y),
                color, -1,
            )
            cv2.putText(
                annotated, label, (x + 5, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2,
            )
        annotated_path = out_dir / f"{image_path.stem}_annotated.png"
        cv2.imwrite(str(annotated_path), annotated)

    return {
        "image": {"path": str(image_path), "size": (img_w, img_h)},
        "views": saved,    # {"table": path, "cscan": path, "ascan": path}
        "annotated": str(annotated_path) if annotated_path else None,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python view_splitter.py <图片路径> [输出目录]")
        sys.exit(1)

    image_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    result = detect_and_crop_ultrasonic_views(image_path, output_dir)
    print(f"\n原图: {result['image']['path']} ({result['image']['size'][0]}×{result['image']['size'][1]})")
    print(f"\n切分结果:")
    for label, path in result["views"].items():
        print(f"  {label}: {path}")
    if result["annotated"]:
        print(f"\n标注预览: {result['annotated']}")
    for w in result["warnings"]:
        print(f"警告: {w}")
