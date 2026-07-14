import argparse
import json
import os
from pathlib import Path

from deepseek_client import DeepSeekClient
from project_intake import generate_project_intake, write_intake_excel
from run_pipeline import load_env_file, write_text


def main() -> None:
    parser = argparse.ArgumentParser(description="仅根据已生成的会议纪要补跑项目录入")
    parser.add_argument("--final-summary", required=True, help="最终会议纪要 Markdown")
    parser.add_argument("--background", default="", help="BP/增强BP Markdown，可选")
    parser.add_argument("--out-dir", required=True, help="输出目录")
    parser.add_argument("--company", required=True, help="公司名，用于文件命名")
    parser.add_argument("--date", required=True, dest="date_text", help="日期，如 2026年07月14日")
    parser.add_argument("--qcc-material", action="append", default=[], help="企查查/工商资料，可重复传入")
    parser.add_argument("--intake-material", action="append", default=[], help="项目录入补充资料，可重复传入")
    parser.add_argument("--intake-template", required=True, help="项目录入 Excel 模板")
    parser.add_argument("--intake-output", help="项目录入 Excel 输出路径；默认写入输出目录")
    parser.add_argument("--project-source", default="待补充", help="项目来源")
    parser.add_argument("--env", default=".env", help="环境变量文件路径")
    args = parser.parse_args()

    load_env_file(Path(args.env))

    out_dir = Path(args.out_dir)
    prefix = f"{args.date_text}_{args.company}"
    final_summary = Path(args.final_summary).read_text(encoding="utf-8")
    background = Path(args.background).read_text(encoding="utf-8") if args.background else ""

    client = DeepSeekClient()
    entry, warnings = generate_project_intake(
        client=client,
        final_summary=final_summary,
        background=background,
        qcc_paths=[Path(path) for path in args.qcc_material],
        other_paths=[Path(path) for path in args.intake_material],
        project_source=args.project_source,
        intake_date=args.date_text,
    )

    write_text(out_dir / f"{prefix}_项目录入草稿.json", json.dumps(entry, ensure_ascii=False, indent=2))
    if warnings:
        write_text(out_dir / f"{prefix}_项目录入校验提示.md", "\n".join(f"- {item}" for item in warnings))

    intake_output = Path(args.intake_output) if args.intake_output else out_dir / f"{prefix}_项目录入.xlsx"
    write_intake_excel(entry, Path(args.intake_template), intake_output)
    print(f"完成。项目录入输出：{intake_output.resolve()}")


if __name__ == "__main__":
    main()
