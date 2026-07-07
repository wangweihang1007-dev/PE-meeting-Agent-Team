import argparse
import json
import os
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


def format_partitioned(items: list[dict]) -> str:
    return "\n\n".join(
        f"## 分区 {item['index']}｜{item.get('time_range', '未标注')}\n\n{item['text']}"
        for item in sorted(items, key=lambda x: x["index"])
    )


def concat_by_time(items: list[dict]) -> str:
    return "\n\n".join(item["text"] for item in sorted(items, key=lambda x: x["index"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="投资访谈会议纪要多智能体流水线（LangGraph + DeepSeek）")
    parser.add_argument("--transcript", required=True, help="会议原始转录文本文件，UTF-8")
    parser.add_argument("--background", help="BP/公司简介/补充资料文本文件，UTF-8；只提供给修正智能体")
    parser.add_argument("--out-dir", default="outputs", help="输出目录")
    parser.add_argument("--max-concurrency", type=int, default=4, help="并行修正/QA 的最大并发数")
    parser.add_argument("--env", default=".env", help="环境变量文件路径")
    parser.add_argument("--docx-template", help="最终会议纪要 DOCX 模板路径；不传则读取 SUMMARY_DOCX_TEMPLATE")
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
    revised_sections = result.get("revised_sections", [])
    qa_sections = result.get("qa_sections", [])

    write_text(out_dir / "01_sections.json", json.dumps(result.get("sections", []), ensure_ascii=False, indent=2))
    write_text(out_dir / "02_revised_sections.md", format_partitioned(revised_sections))
    write_text(out_dir / "03_revised_all_by_time.md", concat_by_time(revised_sections))
    write_text(out_dir / "04_qa_sections.md", format_partitioned(qa_sections))
    write_text(out_dir / "05_qa_all_by_time.md", concat_by_time(qa_sections))
    final_summary_path = out_dir / "06_final_summary.md"
    write_text(final_summary_path, result.get("final_summary", ""))
    docx_template = args.docx_template or os.getenv("SUMMARY_DOCX_TEMPLATE")
    if docx_template:
        markdown_to_docx(final_summary_path, Path(docx_template), out_dir / "06_final_summary.docx")
    write_text(out_dir / "07_qc_report.md", result.get("qc_report", ""))

    print(f"完成。输出目录：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
