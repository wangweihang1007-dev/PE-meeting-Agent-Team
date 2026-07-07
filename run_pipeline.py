import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from deepseek_client import DeepSeekClient
from md_to_docx import markdown_to_docx
from workflow import build_graph


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def safe_filename_part(value: str) -> str:
    cleaned = "".join("_" if ch in r'\/:*?"<>|' else ch for ch in value.strip())
    return cleaned or "公司"


def current_chinese_date() -> str:
    return datetime.now().strftime("%Y年%m月%d日")


def build_prefix(company: str, date_text: str) -> str:
    return f"{date_text}_{safe_filename_part(company)}"


def load_participants(value: str | None, file_path: str | None) -> str:
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    return (value or "").strip()


def add_summary_front_matter(summary: str, participants: str, date_text: str) -> str:
    lines: list[str] = []
    if participants:
        lines.append("参会人")
        lines.append(participants)
        lines.append("")
    lines.append(f"日期：{date_text}")
    lines.append("")
    lines.append(summary.strip())
    return "\n".join(lines).strip() + "\n"


def format_partitioned(items: list[dict]) -> str:
    return "\n\n".join(
        f"## 分区 {item['index']}｜{item.get('time_range', '未标注')}\n\n{item['text']}"
        for item in sorted(items, key=lambda x: x["index"])
    )


def concat_by_time(items: list[dict]) -> str:
    return "\n\n".join(item["text"] for item in sorted(items, key=lambda x: x["index"]))


def write_section_files(out_dir: Path, prefix: str, items: list[dict], file_type: str) -> None:
    for item in sorted(items, key=lambda x: x["index"]):
        write_text(out_dir / f"{prefix}_{file_type}第{item['index']}部分.md", item["text"])


def main() -> None:
    parser = argparse.ArgumentParser(description="投资访谈会议纪要多智能体流水线（LangGraph + DeepSeek）")
    parser.add_argument("--transcript", required=True, help="会议原始转录文本文件，UTF-8")
    parser.add_argument("--background", help="BP/公司简介/补充资料文本文件，UTF-8；只提供给修正智能体")
    parser.add_argument("--out-dir", default="outputs", help="输出目录")
    parser.add_argument("--max-concurrency", type=int, default=4, help="并行修正/QA 的最大并发数")
    parser.add_argument("--env", default=".env", help="环境变量文件路径")
    parser.add_argument("--docx-template", help="最终会议纪要 DOCX 模板路径；不传则读取 SUMMARY_DOCX_TEMPLATE")
    parser.add_argument("--company", default=os.getenv("MEETING_COMPANY", "公司"), help="公司名称，用于文件命名")
    parser.add_argument("--date", dest="date_text", default=os.getenv("MEETING_DATE"), help="会议日期，默认使用运行当天，格式如 2026年07月07日")
    parser.add_argument("--participants", help="参会人文本，会写入最终纪要标题下方")
    parser.add_argument("--participants-file", help="参会人文本文件，UTF-8")
    args = parser.parse_args()

    load_env_file(Path(args.env))

    transcript = Path(args.transcript).read_text(encoding="utf-8")
    background = Path(args.background).read_text(encoding="utf-8") if args.background else ""

    client = DeepSeekClient()
    graph = build_graph(client)
    result = graph.invoke(
        {"raw_transcript": transcript, "background_materials": background},
        config={"max_concurrency": args.max_concurrency},
    )

    out_dir = Path(args.out_dir)
    date_text = args.date_text or current_chinese_date()
    prefix = build_prefix(args.company, date_text)
    participants = load_participants(args.participants, args.participants_file)
    revised_sections = result.get("revised_sections", [])
    qa_sections = result.get("qa_sections", [])

    write_text(out_dir / f"{prefix}_分区结果.json", json.dumps(result.get("sections", []), ensure_ascii=False, indent=2))
    write_section_files(out_dir, prefix, revised_sections, "录音修正")
    write_text(out_dir / f"{prefix}_录音修正汇总.md", concat_by_time(revised_sections))
    write_section_files(out_dir, prefix, qa_sections, "QA整理")
    write_text(out_dir / f"{prefix}_QA整理汇总.md", concat_by_time(qa_sections))
    final_summary_path = out_dir / f"{prefix}_会议纪要.md"
    write_text(final_summary_path, add_summary_front_matter(result.get("final_summary", ""), participants, date_text))
    docx_template = args.docx_template or os.getenv("SUMMARY_DOCX_TEMPLATE")
    if docx_template:
        markdown_to_docx(final_summary_path, Path(docx_template), out_dir / f"{prefix}_会议纪要.docx")
    write_text(out_dir / f"{prefix}_质检报告.md", result.get("qc_report", ""))

    print(f"完成。输出目录：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
