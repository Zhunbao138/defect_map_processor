"""主处理流水线 (v2 - 集成数据库)。

串联所有模块完成完整处理流程:
    xls/xlsx -> 导入 -> 提取图片 -> 切分视图 -> OCR识别 -> 数据整合 -> 输出 (JSON/Excel/DB)

可作为独立模块被 CLI 和 Web 共同调用。

数据持久化:
- 每条记录、图片、视图、OCR 结果都存入 SQLite 数据库
- JSON/Excel 仅作为便利导出
"""
from __future__ import annotations

import json
import time
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .importer import ExcelImporter
from .image_extractor import ImageExtractor
from .view_splitter import split_multiple_images
from .ocr_extractor import extract_defect_info_batch
from .data_merger import DataMerger
from .image_matcher import match_images_to_records
from .database import Database


@dataclass
class ProcessConfig:
    """处理配置。"""

    file_path: str
    output_dir: str = "output"
    sheet_name: str = "Sheet2"
    enable_ocr: bool = True
    enable_split: bool = True
    ocr_languages: tuple[str, ...] = ("en", "ch_sim")
    ocr_gpu: bool = False
    draw_annotations: bool = True
    image_match_strategy: str = "order"   # order / by_row / by_filename / by_folder
    save_to_db: bool = True
    db_path: str | None = None
    # 限制处理的记录数 (None = 全部, 2 = 只前2条, [3,5] = 指定行号)
    limit_records: int | list[int] | None = None


@dataclass
class ProcessResult:
    """处理结果汇总。"""

    success: bool
    file_path: str
    output_dir: str
    task_uuid: str | None = None
    json_path: str | None = None
    excel_path: str | None = None
    db_path: str | None = None
    records: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    error: str | None = None
    elapsed_seconds: float = 0.0


class ProcessPipeline:
    """主处理流水线。"""

    def __init__(self, config: ProcessConfig):
        self.config = config

    def run(self, progress_callback=None) -> ProcessResult:
        """执行完整处理流程。

        progress_callback: callable(stage: str, percent: float, message: str) -> None
            用于 Web 前端实时显示进度。
        """
        start_time = time.time()
        file_path = Path(self.config.file_path)
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        db = None
        task_uuid = None
        file_id = None
        task_id = None

        def report(stage: str, percent: float, message: str):
            if progress_callback:
                progress_callback(stage, percent, message)

        try:
            # ========== 数据库初始化 ==========
            if self.config.save_to_db:
                db = Database(self.config.db_path)
                # 计算文件 md5
                md5 = hashlib.md5(file_path.read_bytes()).hexdigest()
                file_id = db.add_file(
                    filename=file_path.name,
                    original_path=str(file_path),
                    file_format=file_path.suffix.lower(),
                    file_size=file_path.stat().st_size,
                    md5=md5,
                )

            # ========== 阶段 1: 导入 ==========
            report("import", 0.0, f"导入文件: {file_path.name}")
            importer = ExcelImporter(file_path)
            xlsx_path = importer.import_file()
            report("import", 0.7, f"已转换为: {xlsx_path.name}")

            records = importer.read_sheet2_records()

            # 限制处理的记录数 (用于开发调试)
            if self.config.limit_records is not None:
                if isinstance(self.config.limit_records, int):
                    # 取前 N 条
                    records = records[: self.config.limit_records]
                    report(
                        "import",
                        0.9,
                        f"限制处理: 只取前 {self.config.limit_records} 条",
                    )
                else:
                    # 按行号过滤
                    rows_set = set(self.config.limit_records)
                    records = [r for r in records if r.get("row_index") in rows_set]
                    report(
                        "import",
                        0.9,
                        f"限制处理: 只处理行 {sorted(rows_set)}",
                    )

            report("import", 1.0, f"读取 {len(records)} 条缺陷记录")

            # 创建任务
            if db:
                task_uuid = f"t{int(time.time()*1000) % 100000000:08x}"
                task_id = db.create_task(file_id, task_uuid, str(output_dir))

            # ========== 阶段 2: 提取图片 ==========
            image_dir = output_dir / "images"
            image_dir.mkdir(exist_ok=True)
            report("extract", 0.0, "开始提取图片...")

            extract_source = file_path
            try:
                extractor = ImageExtractor(extract_source)
                images = extractor.extract(image_dir, self.config.sheet_name)
            except Exception as e:
                report("extract", 0.5, f"从原文件提取失败: {e}, 尝试从转换后的xlsx提取")
                extractor = ImageExtractor(xlsx_path)
                images = extractor.extract(image_dir, self.config.sheet_name)
            report("extract", 1.0, f"提取了 {len(images)} 张图片")

            # ========== 阶段 2.5: 智能图片-记录关联 ==========
            if images:
                # 如果图片已经有 row_index (来自 image_extractor), 直接使用
                # 否则才使用 match_images_to_records 启发式匹配
                has_row_index = all(img.get("row_index") is not None for img in images)

                if has_row_index:
                    # 直接使用图片自带的 row_index
                    matched = {}
                    for img in images:
                        r = img["row_index"]
                        matched.setdefault(r, []).append(img)
                else:
                    matched = match_images_to_records(
                        images, records, strategy=self.config.image_match_strategy
                    )
                    # 给每张图打上 row_index 标签
                    for row, imgs in matched.items():
                        for img in imgs:
                            img["row_index"] = row

                # 没匹配的清除 row_index
                for img in images:
                    if not any(
                        img["file_path"] == m["file_path"]
                        for m_list in matched.values()
                        for m in m_list
                    ):
                        img["row_index"] = None
                matched_count = sum(1 for imgs in matched.values() for _ in imgs)
                report(
                    "match",
                    1.0,
                    f"已关联 {matched_count}/{len(images)} 张图片到 {len(matched)} 条记录",
                )
            else:
                matched = {}

            # ========== 阶段 3: 切分视图 ==========
            views = []
            if self.config.enable_split and images:
                view_root = output_dir / "views"
                view_root.mkdir(exist_ok=True)

                image_paths = list({img["file_path"] for img in images})
                report("split", 0.0, f"开始切分 {len(image_paths)} 张图片...")

                split_result = split_multiple_images(
                    image_paths,
                    view_root,
                    draw_annotations=self.config.draw_annotations,
                )
                views = split_result["results"]
                report(
                    "split",
                    1.0,
                    f"成功 {split_result['success']} / 失败 {split_result['fail']}",
                )
            else:
                report("split", 1.0, "跳过视图切分")

            # ========== 阶段 4: OCR 识别 ==========
            # 跑两次: 1) 1_top 切图拿缺陷数据 2) 原图顶部标题栏拿钢板号/尺寸
            # 合并两个结果
            ocr_results = []
            if self.config.enable_ocr and images:
                debug_dir = output_dir / "ocr_debug"
                # 与本地一致: 每行 _1 和 _2 原图都 OCR, 按行合并 (黑卡在任一张都用)
                # 黑卡检测在完整原图上进行, 同时拿到标题栏(钢板号/材料尺寸)和黑卡缺陷参数
                row_images = {}
                row_order = []
                for img in images:
                    row = img.get("row_index")
                    if row is None:
                        continue
                    if row not in row_images:
                        row_images[row] = []
                        row_order.append(row)
                    row_images[row].append(img["file_path"])

                all_paths = [p for row in row_order for p in row_images[row]]
                report("ocr", 0.0, f"开始 OCR 识别 {len(all_paths)} 张图 (每行 _1+_2)...")
                _ocr_total = len(all_paths)

                def _ocr_progress(done, total):
                    report("ocr", done / total if total else 1.0,
                            f"OCR 识别中 {done}/{total} 张...")

                all_results = extract_defect_info_batch(
                    all_paths,
                    languages=self.config.ocr_languages,
                    gpu=self.config.ocr_gpu,
                    debug_dir=debug_dir,
                    on_progress=_ocr_progress,
                )

                # 按行合并: 任一张图有值即取 (缺陷参数来自含黑卡那张, 尺寸/钢板号任一张)
                idx = 0
                for row in row_order:
                    nrow = len(row_images[row])
                    row_res = all_results[idx: idx + nrow]
                    idx += nrow
                    merged_params = {}
                    texts, raws, warns = [], [], []
                    for r in row_res:
                        for k, v in (r.get("params", {}) or {}).items():
                            if v and not merged_params.get(k):
                                merged_params[k] = v
                        if r.get("full_text"):
                            texts.append(r["full_text"])
                        raws += r.get("raw_text", [])
                        warns += r.get("warnings", [])
                    ocr_results.append({
                        "source": row_images[row][0],
                        "params": merged_params,
                        "full_text": " | ".join(texts),
                        "raw_text": raws,
                        "warnings": warns,
                    })
                report("ocr", 1.0, f"OCR 完成, 合并 {len(ocr_results)} 行")
            else:
                report("ocr", 1.0, "跳过 OCR 识别")

            # ========== 阶段 5: 数据整合 ==========
            report("merge", 0.0, "正在整合数据...")
            merger = DataMerger(output_dir)
            merged_records = merger.merge(records, images, views, ocr_results)
            json_path = merger.save_json(merged_records)
            excel_path = merger.save_excel(merged_records)
            report("merge", 1.0, f"已保存 {json_path.name} 和 {excel_path.name}")

            # ========== 阶段 6: 存入数据库 ==========
            if db and task_id is not None:
                report("database", 0.0, "正在存入数据库...")
                # records
                for rec in merged_records:
                    rec_id = db.add_record(
                        task_id=task_id,
                        row_index=rec.get("row_index", 0),
                        sequence=rec.get("序号", ""),
                        factory=rec.get("生产厂", ""),
                        plate_no=rec.get("钢板号", ""),
                        steel_grade=rec.get("钢种", ""),
                        category=rec.get("类别", ""),
                        defect_analysis=rec.get("缺陷分析", ""),
                        extra_notes=rec.get("ocr_raw_text", ""),
                        notes="; ".join(rec.get("warnings", [])),
                    )

                    # 图片
                    for img_num in (1, 2):
                        img_path = rec.get(f"图-{img_num}")
                        if not img_path:
                            continue
                        img_format = rec.get(f"图-{img_num}_format", "")
                        # 找出对应的 image 元数据
                        img_meta = next(
                            (i for i in images if i.get("file_path") == img_path),
                            None,
                        )
                        w = img_meta.get("width", 0) if img_meta else 0
                        h = img_meta.get("height", 0) if img_meta else 0
                        img_id = db.add_image(
                            record_id=rec_id,
                            image_index=img_num,
                            file_path=img_path,
                            image_format=img_format,
                            width=w,
                            height=h,
                        )

                        # 视图
                        view_mapping = [
                            ("俯视图", f"俯视图-{img_num}"),
                            ("长边侧视图", f"长边方向侧视图-{img_num}"),
                            ("短边侧视图", f"短边方向侧视图-{img_num}"),
                            ("annotated", f"视图标注预览-{img_num}"),
                        ]
                        for vtype, key in view_mapping:
                            vpath = rec.get(key)
                            if vpath:
                                from PIL import Image as PILImage
                                try:
                                    pim = PILImage.open(vpath)
                                    vw, vh = pim.size
                                except Exception:
                                    vw = vh = 0
                                db.add_view(
                                    image_id=img_id,
                                    view_type=vtype,
                                    view_label=key,
                                    file_path=vpath,
                                    width=vw,
                                    height=vh,
                                )

                        # OCR (只第一张图)
                        if img_num == 1:
                            params = rec.get("缺陷数据", {})
                            if params or rec.get("ocr_raw_text"):
                                db.add_ocr(
                                    image_id=img_id,
                                    params=params,
                                    raw_text=rec.get("ocr_raw_text", ""),
                                    warnings="; ".join(rec.get("warnings", [])),
                                )

                report("database", 1.0, f"数据库已更新: {db.db_path}")

            # ========== 完成 ==========
            elapsed = time.time() - start_time
            views_keys = [
                "俯视图-1", "长边方向侧视图-1", "短边方向侧视图-1",
                "俯视图-2", "长边方向侧视图-2", "短边方向侧视图-2",
            ]
            total_views = sum(
                sum(1 for k in views_keys if rec.get(k)) for rec in merged_records
            )
            stats = {
                "records_count": len(merged_records),
                "images_count": len(images),
                "views_count": total_views,
                "ocr_count": sum(1 for r in ocr_results if r.get("params")),
                "matched_images": sum(len(imgs) for imgs in matched.values()),
            }

            # 更新任务状态
            if db and task_uuid:
                db.update_task_status(
                    task_uuid, "completed",
                    elapsed_seconds=elapsed,
                    stats=stats,
                )

            return ProcessResult(
                success=True,
                file_path=str(file_path),
                output_dir=str(output_dir),
                task_uuid=task_uuid,
                json_path=str(json_path),
                excel_path=str(excel_path),
                db_path=str(db.db_path) if db else None,
                records=merged_records,
                stats=stats,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            import traceback

            # 标记任务失败
            if db and task_uuid:
                db.update_task_status(
                    task_uuid, "failed",
                    elapsed_seconds=time.time() - start_time,
                )

            return ProcessResult(
                success=False,
                file_path=str(file_path),
                output_dir=str(output_dir),
                task_uuid=task_uuid,
                db_path=str(db.db_path) if db else None,
                error=f"{e}\n\n{traceback.format_exc()}",
                elapsed_seconds=time.time() - start_time,
            )


def run_pipeline(
    file_path: str | Path,
    output_dir: str | Path = "output",
    enable_ocr: bool = True,
    enable_split: bool = True,
    progress_callback=None,
    save_to_db: bool = True,
    image_match_strategy: str = "order",
    db_path: str | None = None,
    limit_records: int | list[int] | None = None,
) -> ProcessResult:
    """便捷函数：运行完整流水线。

    Parameters
    ----------
    limit_records : int | list[int] | None
        限制处理的记录数 (None=全部, N=前N条, [7,8]=指定行号)
    """
    config = ProcessConfig(
        file_path=str(file_path),
        output_dir=str(output_dir),
        enable_ocr=enable_ocr,
        enable_split=enable_split,
        save_to_db=save_to_db,
        image_match_strategy=image_match_strategy,
        db_path=db_path,
        limit_records=limit_records,
    )
    pipeline = ProcessPipeline(config)
    return pipeline.run(progress_callback)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python pipeline.py <xls/xlsx文件路径> [输出目录]")
        sys.exit(1)

    file_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"

    print(f"处理文件: {file_path}")
    print(f"输出目录: {output_dir}\n")

    def show_progress(stage, percent, message):
        bar = "█" * int(percent * 30) + "░" * (30 - int(percent * 30))
        print(f"  [{bar}] {stage:10s} {percent*100:5.1f}%  {message}")

    result = run_pipeline(file_path, output_dir, progress_callback=show_progress)

    print(f"\n{'='*60}")
    if result.success:
        print(f"✓ 处理成功! 耗时 {result.elapsed_seconds:.1f} 秒")
        print(f"  - 缺陷记录: {result.stats['records_count']}")
        print(f"  - 提取图片: {result.stats['images_count']}")
        print(f"  - 切分视图: {result.stats['views_count']}")
        print(f"  - OCR 成功: {result.stats['ocr_count']}")
        print(f"  - 数据库:   {result.db_path}")
        print(f"\n输出文件:")
        print(f"  JSON:  {result.json_path}")
        print(f"  Excel: {result.excel_path}")
    else:
        print(f"✗ 处理失败: {result.error}")