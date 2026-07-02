"""命令行入口。

使用示例:
    # 处理单个文件
    python cli.py process input.xlsx

    # 指定输出目录
    python cli.py process input.xls -o ./my_output

    # 禁用 OCR (加快速度)
    python cli.py process input.xlsx --no-ocr

    # 查看帮助
    python cli.py --help
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许从 defect_map_processor 目录运行
sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline import run_pipeline, ProcessPipeline, ProcessConfig


def cmd_process(args):
    """处理 Excel 文件。"""
    print(f"\n{'='*60}")
    print(f"钢材缺陷图像知识库")
    print(f"{'='*60}\n")
    print(f"输入: {args.input}")
    print(f"输出: {args.output}\n")

    def show_progress(stage, percent, message):
        bar = "█" * int(percent * 30) + "░" * (30 - int(percent * 30))
        print(f"  [{bar}] {stage:10s} {percent*100:5.1f}%  {message}")

    config = ProcessConfig(
        file_path=args.input,
        output_dir=args.output,
        sheet_name=args.sheet,
        enable_ocr=not args.no_ocr,
        enable_split=not args.no_split,
        ocr_gpu=args.gpu,
        ocr_languages=tuple(args.lang.split(",")) if args.lang else ("en", "ch_sim"),
    )

    pipeline = ProcessPipeline(config)
    result = pipeline.run(progress_callback=show_progress)

    print(f"\n{'='*60}")
    if result.success:
        print(f"✓ 处理成功! 耗时 {result.elapsed_seconds:.1f} 秒")
        print(f"\n统计信息:")
        print(f"  - 缺陷记录:  {result.stats['records_count']:>4d}")
        print(f"  - 提取图片:  {result.stats['images_count']:>4d}")
        print(f"  - 切分视图:  {result.stats['views_count']:>4d}")
        print(f"  - OCR 成功:  {result.stats['ocr_count']:>4d}")
        print(f"\n输出文件:")
        print(f"  - JSON:  {result.json_path}")
        print(f"  - Excel: {result.excel_path}")
        return 0
    else:
        print(f"✗ 处理失败")
        print(f"\n错误详情:\n{result.error}")
        return 1


def cmd_serve(args):
    """启动 Web 服务。"""
    from app import create_app

    app = create_app()
    print(f"\n启动 Web 服务: http://{args.host}:{args.port}")
    print(f"按 Ctrl+C 停止\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="钢材缺陷图像知识库 - 导入、提取、切分、OCR、整合、展示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s process input.xlsx                  处理单个 Excel 文件
  %(prog)s process input.xls -o ./output       指定输出目录
  %(prog)s process input.xlsx --no-ocr         跳过 OCR 加快速度
  %(prog)s serve --port 5000                   启动 Web 服务
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # process 子命令
    p_process = subparsers.add_parser("process", help="处理 Excel 文件")
    p_process.add_argument("input", help="输入 Excel 文件 (.xls 或 .xlsx)")
    p_process.add_argument(
        "-o", "--output", default="output", help="输出目录 (默认: output)"
    )
    p_process.add_argument(
        "-s", "--sheet", default="Sheet2", help="Sheet 名称 (默认: Sheet2)"
    )
    p_process.add_argument("--no-ocr", action="store_true", help="跳过 OCR 识别")
    p_process.add_argument(
        "--no-split", action="store_true", help="跳过三视图切分"
    )
    p_process.add_argument("--gpu", action="store_true", help="使用 GPU 加速 OCR")
    p_process.add_argument(
        "--lang", default="en,ch_sim", help="OCR 语言, 逗号分隔 (默认: en,ch_sim)"
    )
    p_process.set_defaults(func=cmd_process)

    # serve 子命令
    p_serve = subparsers.add_parser("serve", help="启动 Web 服务")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址")
    p_serve.add_argument("--port", type=int, default=5000, help="监听端口")
    p_serve.add_argument("--debug", action="store_true", help="调试模式")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())