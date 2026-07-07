import argparse
import re
from pathlib import Path

import mammoth
import pdfplumber


WATERMARK_TOKENS = ("阅", "审", "本", "资", "源", "冯", "供", "仅")


def normalize_lines(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def extract_docx(path: Path) -> str:
    with path.open("rb") as file:
        result = mammoth.convert_to_markdown(file)
    return normalize_lines(result.value)


def clean_bp_noise(text: str) -> str:
    for token in WATERMARK_TOKENS:
        text = text.replace(token, "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_lines(text)


def extract_pdf(path: Path) -> str:
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            text = page.extract_text(layout=True) or page.extract_text() or ""
            text = clean_bp_noise(text)
            if text:
                pages.append(f"## BP第{page_number}页\n{text}")
    return "\n\n".join(pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="抽取会议原文 DOCX 和 BP PDF 为流水线输入文本")
    parser.add_argument("--transcript-docx", required=True)
    parser.add_argument("--background-pdf", required=True)
    parser.add_argument("--out-dir", default="inputs")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = extract_docx(Path(args.transcript_docx))
    background = extract_pdf(Path(args.background_pdf))
    (out_dir / "transcript_extracted.md").write_text(transcript, encoding="utf-8")
    (out_dir / "background_extracted.md").write_text(background, encoding="utf-8")
    print(f"transcript_chars={len(transcript)}")
    print(f"background_chars={len(background)}")


if __name__ == "__main__":
    main()
