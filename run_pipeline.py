import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from deepseek_client import DeepSeekClient
from md_to_docx import markdown_to_docx
from project_intake import generate_project_intake, write_intake_excel
from workflow import build_graph


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
QUESTION_LINE_PATTERN = re.compile(r"^(?P<prefix>\s*(?:(?:[-*]|\d+\.)\s*)?)(?P<label>(?:Q|问题)\s*[:：])(?P<body>.*)$", re.IGNORECASE)


class JsonCheckpoint:
    def __init__(self, root: Path, *, resume: bool) -> None:
        self.root = root
        self.resume = resume

    def _path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}.{suffix}"

    def _processed_path(self, key: str, index: int) -> Path:
        return self.root / key / f"{index:03d}.json"

    def load_json(self, key: str):
        if not self.resume:
            return None
        path = self._path(key, "json")
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_json(self, key: str, value) -> None:
        path = self._path(key, "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_text(self, key: str) -> str | None:
        if not self.resume:
            return None
        path = self._path(key, "md")
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return text if text.strip() else None

    def save_text(self, key: str, value: str) -> None:
        path = self._path(key, "md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def load_processed(self, key: str, index: int):
        if not self.resume:
            return None
        path = self._processed_path(key, index)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_processed(self, key: str, item: dict) -> None:
        path = self._processed_path(key, int(item["index"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")


def progress(message: str, enabled: bool = True) -> None:
    if enabled:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


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


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def collect_image_paths(paths: list[str]) -> list[Path]:
    images: list[Path] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        candidates = (
            sorted(item for item in path.rglob("*") if item.is_file())
            if path.is_dir()
            else [path]
        )
        for candidate in candidates:
            if candidate.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            digest = file_digest(candidate)
            if digest not in seen:
                seen.add(digest)
                images.append(candidate)
    return images


def copy_background_images(image_paths: list[Path], out_dir: Path) -> list[dict[str, str]]:
    image_dir = out_dir / "assets" / "background_images"
    copied: list[dict[str, str]] = []
    for index, source in enumerate(image_paths, 1):
        safe_name = safe_filename_part(source.stem)
        filename = f"{index:02d}_{safe_name}{source.suffix.lower()}"
        target = image_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(
            {
                "index": str(index),
                "source": str(source),
                "filename": filename,
                "relative_path": target.relative_to(out_dir).as_posix(),
                "path": str(target),
                "title": source.stem,
            }
        )
    return copied


def build_enhanced_background(background: str, images: list[dict[str, str]]) -> str:
    if not images:
        return background
    lines = [background.strip(), "", "# 图片补充材料", ""]
    lines.append("以下图片由用户作为 BP/背景补充材料提供；图片内容用于修正智能体参考，不直接提供给 QA 或总结智能体。")
    lines.append("")
    for image in images:
        lines.append(f"## 图片 {image['index']}：{image['title']}")
        lines.append(f"来源文件：{image['source']}")
        lines.append(f"![图片 {image['index']}：{image['title']}]({image['relative_path']})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def append_images_to_summary(summary: str, images: list[dict[str, str]]) -> str:
    if not images:
        return summary
    lines = [summary.rstrip(), "", "---", "", "# 附录：补充图片材料", ""]
    for image in images:
        lines.append(f"## 图片 {image['index']}：{image['title']}")
        lines.append(f"![图片 {image['index']}：{image['title']}]({image['relative_path']})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_image_appendix_pdf(images: list[dict[str, str]], output_path: Path) -> None:
    from reportlab.lib.pagesizes import A4, landscape, portrait
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    output_path.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = A4
    margin = 36
    title_height = 24
    pdf = canvas.Canvas(str(output_path), pagesize=A4)

    for image in images:
        image_path = Path(image["path"])
        reader = ImageReader(str(image_path))
        image_width, image_height = reader.getSize()
        page_size = landscape(A4) if image_width > image_height else portrait(A4)
        page_width, page_height = page_size
        pdf.setPageSize(page_size)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(margin, page_height - margin + 8, f"Image {image['index']}: {image['title']}")

        max_width = page_width - margin * 2
        max_height = page_height - margin * 2 - title_height
        scale = min(max_width / image_width, max_height / image_height)
        draw_width = image_width * scale
        draw_height = image_height * scale
        x = (page_width - draw_width) / 2
        y = (page_height - draw_height) / 2 - 6
        pdf.drawImage(reader, x, y, width=draw_width, height=draw_height, preserveAspectRatio=True, mask="auto")
        pdf.showPage()

    pdf.save()


def build_enhanced_bp_pdf(background_pdf: Path, images: list[dict[str, str]], output_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    original_reader = PdfReader(str(background_pdf))
    for page in original_reader.pages:
        writer.add_page(page)

    if images:
        with tempfile.TemporaryDirectory() as tmp_dir:
            appendix_pdf = Path(tmp_dir) / "image_appendix.pdf"
            build_image_appendix_pdf(images, appendix_pdf)
            appendix_reader = PdfReader(str(appendix_pdf))
            for page in appendix_reader.pages:
                writer.add_page(page)

    with output_path.open("wb") as file:
        writer.write(file)


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


def bold_qa_questions(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**") or "**Q" in stripped or "**问题" in stripped:
            lines.append(line)
            continue
        match = QUESTION_LINE_PATTERN.match(line)
        if not match:
            lines.append(line)
            continue
        question_text = f"{match.group('label')}{match.group('body')}".strip()
        lines.append(f"{match.group('prefix')}**{question_text}**")
    return "\n".join(lines)


def bold_qa_section_items(items: list[dict]) -> list[dict]:
    return [
        {**item, "text": bold_qa_questions(item.get("text", ""))}
        for item in items
    ]


def write_section_files(out_dir: Path, prefix: str, items: list[dict], file_type: str) -> None:
    for item in sorted(items, key=lambda x: x["index"]):
        write_text(out_dir / f"{prefix}_{file_type}第{item['index']}部分.md", item["text"])


def main() -> None:
    parser = argparse.ArgumentParser(description="投资访谈会议纪要多智能体流水线（LangGraph + DeepSeek）")
    parser.add_argument("--transcript", required=True, help="会议原始转录文本文件，UTF-8")
    parser.add_argument("--background", help="BP/公司简介/补充资料文本文件，UTF-8；只提供给修正智能体")
    parser.add_argument("--background-pdf", help="原始 BP PDF；传入后会在 PDF 末尾追加去重图片，生成增强BP.pdf")
    parser.add_argument("--out-dir", default="outputs", help="输出目录")
    parser.add_argument("--max-concurrency", type=int, default=4, help="并行修正/QA 的最大并发数")
    parser.add_argument("--env", default=".env", help="环境变量文件路径")
    parser.add_argument("--docx-template", help="最终会议纪要 DOCX 模板路径；不传则读取 SUMMARY_DOCX_TEMPLATE")
    parser.add_argument("--company", default=os.getenv("MEETING_COMPANY", "公司"), help="公司名称，用于文件命名")
    parser.add_argument("--date", dest="date_text", default=os.getenv("MEETING_DATE"), help="会议日期，默认使用运行当天，格式如 2026年07月07日")
    parser.add_argument("--participants", help="参会人文本，会写入最终纪要标题下方")
    parser.add_argument("--participants-file", help="参会人文本文件，UTF-8")
    parser.add_argument("--background-image", action="append", default=[], help="BP补充图片文件或目录，可重复传入；会生成增强BP并附到最终纪要末尾")
    parser.add_argument("--image-material", action="append", default=[], help="同 --background-image，便于按材料口径传参")
    parser.add_argument("--qcc-material", action="append", default=[], help="企查查/工商资料，仅用于项目录入阶段，可重复传入")
    parser.add_argument("--intake-material", action="append", default=[], help="项目录入补充资料，可重复传入")
    parser.add_argument("--intake-template", help="新版项目录入表模板；传入后生成项目录入 Excel")
    parser.add_argument("--intake-output", help="项目录入 Excel 输出路径；默认写入输出目录")
    parser.add_argument("--project-source", default="待补充", help="项目来源，写入项目录入表 O 列")
    parser.add_argument("--resume", action="store_true", help="启用断点续跑，复用输出目录下已有 checkpoint")
    parser.add_argument("--checkpoint-dir", help="checkpoint 目录；默认使用输出目录下的 .checkpoint")
    parser.add_argument("--clear-checkpoint", action="store_true", help="运行前清空 checkpoint，强制重新生成")
    parser.add_argument("--no-progress", action="store_true", help="关闭终端进度显示")
    args = parser.parse_args()
    show_progress = not args.no_progress

    load_env_file(Path(args.env))

    out_dir = Path(args.out_dir)
    date_text = args.date_text or current_chinese_date()
    prefix = build_prefix(args.company, date_text)
    participants = load_participants(args.participants, args.participants_file)
    checkpoint_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else out_dir / ".checkpoint"
    if args.clear_checkpoint and checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
        progress("已清空 checkpoint", show_progress)
    checkpoint = JsonCheckpoint(checkpoint_dir, resume=args.resume)
    if args.resume:
        progress(f"启用断点续跑：{checkpoint_dir}", show_progress)

    progress("读取输入材料", show_progress)
    transcript = Path(args.transcript).read_text(encoding="utf-8")
    background = Path(args.background).read_text(encoding="utf-8") if args.background else ""
    image_paths = collect_image_paths(args.background_image + args.image_material)
    copied_images = copy_background_images(image_paths, out_dir) if image_paths else []
    enhanced_background = build_enhanced_background(background, copied_images)
    if copied_images:
        progress(f"生成增强BP，追加 {len(copied_images)} 张图片", show_progress)
        write_text(out_dir / f"{prefix}_增强BP.md", enhanced_background)
    if args.background_pdf:
        enhanced_bp_pdf_path = out_dir / f"{prefix}_增强BP.pdf"
        progress("生成增强BP PDF", show_progress)
        build_enhanced_bp_pdf(Path(args.background_pdf), copied_images, enhanced_bp_pdf_path)

    client = DeepSeekClient()
    graph = build_graph(client, progress=show_progress, checkpoint=checkpoint)
    progress("启动 LangGraph 多智能体流程", show_progress)
    result = graph.invoke(
        {"raw_transcript": transcript, "background_materials": enhanced_background},
        config={"max_concurrency": args.max_concurrency},
    )

    progress("多智能体流程完成，开始写入输出文件", show_progress)
    revised_sections = result.get("revised_sections", [])
    qa_sections = bold_qa_section_items(result.get("qa_sections", []))

    progress("写入分区、修正和 Q&A 汇总文件", show_progress)
    write_text(out_dir / f"{prefix}_分区结果.json", json.dumps(result.get("sections", []), ensure_ascii=False, indent=2))
    write_section_files(out_dir, prefix, revised_sections, "录音修正")
    write_text(out_dir / f"{prefix}_录音修正汇总.md", concat_by_time(revised_sections))
    write_section_files(out_dir, prefix, qa_sections, "QA整理")
    write_text(out_dir / f"{prefix}_QA整理汇总.md", concat_by_time(qa_sections))
    final_summary_path = out_dir / f"{prefix}_会议纪要.md"
    final_summary_with_front_matter = add_summary_front_matter(result.get("final_summary", ""), participants, date_text)
    final_summary_with_front_matter = bold_qa_questions(final_summary_with_front_matter)
    final_summary_with_front_matter = append_images_to_summary(final_summary_with_front_matter, copied_images)
    progress("写入最终会议纪要 Markdown", show_progress)
    write_text(final_summary_path, final_summary_with_front_matter)
    docx_template = args.docx_template or os.getenv("SUMMARY_DOCX_TEMPLATE")
    if docx_template:
        progress("导出最终会议纪要 Word", show_progress)
        markdown_to_docx(final_summary_path, Path(docx_template), out_dir / f"{prefix}_会议纪要.docx")
    progress("写入质检报告", show_progress)
    write_text(out_dir / f"{prefix}_质检报告.md", result.get("qc_report", ""))

    if args.qcc_material or args.intake_material or args.intake_template:
        cached_intake = checkpoint.load_json("project_intake")
        if cached_intake:
            progress("项目录入智能体使用断点", show_progress)
            entry = cached_intake.get("entry", {})
            warnings = cached_intake.get("warnings", [])
        else:
            progress("启动项目录入智能体", show_progress)
            entry, warnings = generate_project_intake(
                client=client,
                final_summary=final_summary_with_front_matter,
                background=enhanced_background,
                qcc_paths=[Path(path) for path in args.qcc_material],
                other_paths=[Path(path) for path in args.intake_material],
                project_source=args.project_source,
                intake_date=date_text,
            )
            checkpoint.save_json("project_intake", {"entry": entry, "warnings": warnings})
        intake_json_path = out_dir / f"{prefix}_项目录入草稿.json"
        progress("写入项目录入草稿 JSON", show_progress)
        write_text(intake_json_path, json.dumps(entry, ensure_ascii=False, indent=2))
        if warnings:
            write_text(out_dir / f"{prefix}_项目录入校验提示.md", "\n".join(f"- {item}" for item in warnings))
        if args.intake_template:
            intake_output = Path(args.intake_output) if args.intake_output else out_dir / f"{prefix}_项目录入.xlsx"
            progress("写入项目录入 Excel", show_progress)
            write_intake_excel(entry, Path(args.intake_template), intake_output)

    progress("全部完成", show_progress)
    print(f"完成。输出目录：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
