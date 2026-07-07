import argparse
import os
import re
from pathlib import Path

from deepseek_client import DeepSeekClient
from md_to_docx import markdown_to_docx
from prompts import QA_PROMPT, QC_PROMPT, SUMMARY_PROMPT
from run_pipeline import (
    add_summary_front_matter,
    build_prefix,
    concat_by_time,
    current_chinese_date,
    load_env_file,
    load_participants,
    write_section_files,
    write_text,
)


def parse_revised_sections(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^## 分区 (\d+)｜(.+?)\s*$", re.M)
    matches = list(pattern.finditer(text))
    sections: list[dict] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append(
            {
                "index": int(match.group(1)),
                "time_range": match.group(2).strip(),
                "text": text[start:end].strip(),
            }
        )
    return sections


def main() -> None:
    parser = argparse.ArgumentParser(description="基于已有修正稿重跑 Q&A、总结和质检")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--docx-template", help="最终会议纪要 DOCX 模板路径；不传则读取 SUMMARY_DOCX_TEMPLATE")
    parser.add_argument("--company", default=os.getenv("MEETING_COMPANY", "公司"), help="公司名称，用于文件命名")
    parser.add_argument("--date", dest="date_text", default=os.getenv("MEETING_DATE"), help="会议日期，默认使用运行当天，格式如 2026年07月07日")
    parser.add_argument("--participants", help="参会人文本，会写入最终纪要标题下方")
    parser.add_argument("--participants-file", help="参会人文本文件，UTF-8")
    args = parser.parse_args()

    load_env_file(Path(args.env))
    source_dir = Path(args.source_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_text = args.date_text or current_chinese_date()
    prefix = build_prefix(args.company, date_text)
    participants = load_participants(args.participants, args.participants_file)

    client = DeepSeekClient()
    revised_sections = parse_revised_sections(source_dir / "02_revised_sections.md")
    qa_sections: list[dict] = []
    for section in revised_sections:
        user_prompt = (
            f"【当前分区修正稿】\n"
            f"分区编号：{section['index']}\n"
            f"时间范围：{section.get('time_range', '未标注')}\n\n"
            f"{section['text']}"
        )
        qa_text = client.chat(QA_PROMPT, user_prompt, temperature=0.15)
        qa_sections.append(
            {"index": section["index"], "time_range": section.get("time_range", "未标注"), "text": qa_text}
        )

    write_section_files(out_dir, prefix, revised_sections, "录音修正")
    write_text(out_dir / f"{prefix}_录音修正汇总.md", concat_by_time(revised_sections))
    write_section_files(out_dir, prefix, qa_sections, "QA整理")
    write_text(out_dir / f"{prefix}_QA整理汇总.md", concat_by_time(qa_sections))

    qa_bundle = "\n\n".join(
        f"【分区 {item['index']}｜{item.get('time_range', '未标注')}】\n{item['text']}"
        for item in sorted(qa_sections, key=lambda item: item["index"])
    )
    final_summary = client.chat(SUMMARY_PROMPT, "以下是全部按时间顺序排列的分区 Q&A 稿：\n\n" + qa_bundle, temperature=0.2)
    final_summary_path = out_dir / f"{prefix}_会议纪要.md"
    write_text(final_summary_path, add_summary_front_matter(final_summary, participants, date_text))
    docx_template = args.docx_template or os.getenv("SUMMARY_DOCX_TEMPLATE")
    if docx_template:
        markdown_to_docx(final_summary_path, Path(docx_template), out_dir / f"{prefix}_会议纪要.docx")

    revised_bundle = "\n\n".join(
        f"【修正分区 {item['index']}｜{item.get('time_range', '未标注')}】\n{item['text']}"
        for item in sorted(revised_sections, key=lambda item: item["index"])
    )
    qc_prompt = (
        "请只基于以下流程产物做质检，不要补写纪要，也不要把修正稿中的信息补进最终纪要。\n\n"
        f"【修正稿】\n{revised_bundle}\n\n"
        f"【全部 Q&A】\n{qa_bundle}\n\n"
        f"【最终会议纪要】\n{final_summary}"
    )
    qc_report = client.chat(QC_PROMPT, qc_prompt, temperature=0.1)
    write_text(out_dir / f"{prefix}_质检报告.md", qc_report)
    print(f"完成。输出目录：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
