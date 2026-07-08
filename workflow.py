import json
import operator
import re
from typing import Annotated, Any, TypedDict

from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

from deepseek_client import DeepSeekClient
from prompts import DIVIDER_PROMPT, QA_PROMPT, QC_PROMPT, REVISION_PROMPT, SUMMARY_PROMPT


class Section(TypedDict):
    index: int
    time_range: str
    approx_chars: int
    topic: str
    split_reason: str
    text: str


class ProcessedSection(TypedDict):
    index: int
    time_range: str
    text: str


class PipelineState(TypedDict, total=False):
    raw_transcript: str
    background_materials: str
    sections: list[Section]
    section: Section
    revised_sections: Annotated[list[ProcessedSection], operator.add]
    qa_sections: Annotated[list[ProcessedSection], operator.add]
    final_summary: str
    qc_report: str


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _sort_processed(items: list[ProcessedSection]) -> list[ProcessedSection]:
    return sorted(items, key=lambda item: item["index"])


def _fallback_sections(raw_transcript: str, target_chars: int = 2200, max_chars: int = 3000) -> list[Section]:
    lines = raw_transcript.splitlines()
    header: list[str] = []
    blocks: list[str] = []
    current: list[str] = []
    time_pattern = re.compile(r"^(?:发言人\d*\s+)?\d{1,2}:\d{2}(?::\d{2})?$")

    for line in lines:
        stripped = line.strip()
        if time_pattern.match(stripped) or re.match(r"^发言人\d*\s+\d{1,2}:\d{2}", stripped):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        else:
            if current:
                current.append(line)
            elif stripped:
                header.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    if not blocks:
        blocks = [raw_transcript]
        header = []

    sections: list[Section] = []
    bucket: list[str] = []
    header_text = "\n".join(header).strip()

    def time_range(text: str) -> str:
        times = re.findall(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", text)
        if not times:
            return "未标注"
        return times[0] if len(times) == 1 else f"{times[0]}—{times[-1]}"

    def flush() -> None:
        if not bucket:
            return
        section_body = "\n".join(bucket).strip()
        text = section_body
        if header_text and not sections:
            text = header_text + "\n" + text
        sections.append(
            {
                "index": len(sections) + 1,
                "time_range": time_range(section_body),
                "approx_chars": len(text),
                "topic": "按时间戳和约2000字规则自动划分",
                "split_reason": "划分模型未返回可用多分区结果，使用本地兜底切分；按时间顺序在发言时间戳边界切分。",
                "text": text,
            }
        )
        bucket.clear()

    for block in blocks:
        current_len = len("\n".join(bucket))
        if bucket and current_len >= target_chars and current_len + len(block) > max_chars:
            flush()
        bucket.append(block)
    flush()
    if len(sections) > 1 and sections[-1]["approx_chars"] < 500:
        tail = sections.pop()
        sections[-1]["text"] = sections[-1]["text"].rstrip() + "\n" + tail["text"]
        sections[-1]["approx_chars"] = len(sections[-1]["text"])
        sections[-1]["time_range"] = time_range(sections[-1]["text"])
    return sections


def build_graph(client: DeepSeekClient):
    def divide_transcript(state: PipelineState) -> PipelineState:
        result = client.chat(
            DIVIDER_PROMPT,
            "请帮我对以下会议转录稿进行区域划分处理：\n\n" + state["raw_transcript"],
            temperature=0.1,
        )
        try:
            payload = _extract_json_object(result)
            sections = payload["sections"]
        except Exception:
            sections = _fallback_sections(state["raw_transcript"])
        if len(sections) <= 1 and len(state["raw_transcript"]) > 3500:
            sections = _fallback_sections(state["raw_transcript"])
        return {"sections": sections, "revised_sections": [], "qa_sections": []}

    def send_to_revision(state: PipelineState) -> list[Send]:
        return [Send("revise_section", {"section": section, "background_materials": state.get("background_materials", "")}) for section in state["sections"]]

    def revise_section(state: PipelineState) -> PipelineState:
        section = state["section"]
        user_prompt = (
            f"【背景材料】\n{state.get('background_materials') or '未提供'}\n\n"
            f"【当前分区】\n"
            f"分区编号：{section['index']}\n"
            f"时间范围：{section.get('time_range', '未标注')}\n\n"
            f"{section['text']}"
        )
        revised = client.chat(REVISION_PROMPT, user_prompt, temperature=0.1)
        return {
            "revised_sections": [
                {"index": section["index"], "time_range": section.get("time_range", "未标注"), "text": revised}
            ]
        }

    def send_to_qa(state: PipelineState) -> list[Send]:
        return [Send("qa_section", {"section": section}) for section in _sort_processed(state["revised_sections"])]

    def qa_section(state: PipelineState) -> PipelineState:
        section = state["section"]
        user_prompt = (
            f"【当前分区修正稿】\n"
            f"分区编号：{section['index']}\n"
            f"时间范围：{section.get('time_range', '未标注')}\n\n"
            f"{section['text']}"
        )
        qa_text = client.chat(QA_PROMPT, user_prompt, temperature=0.2)
        return {
            "qa_sections": [
                {"index": section["index"], "time_range": section.get("time_range", "未标注"), "text": qa_text}
            ]
        }

    def summarize(state: PipelineState) -> PipelineState:
        qa_bundle = "\n\n".join(
            f"【分区 {item['index']}｜{item.get('time_range', '未标注')}】\n{item['text']}"
            for item in _sort_processed(state["qa_sections"])
        )
        final_summary = client.chat(SUMMARY_PROMPT, "以下是全部按时间顺序排列的分区 Q&A 稿：\n\n" + qa_bundle, temperature=0.2)
        return {"final_summary": final_summary}

    def quality_check(state: PipelineState) -> PipelineState:
        original_bundle = "\n\n".join(
            f"【原始分区 {item['index']}｜{item.get('time_range', '未标注')}】\n{item['text']}"
            for item in sorted(state.get("sections", []), key=lambda item: item["index"])
        )
        revised_bundle = "\n\n".join(
            f"【修正分区 {item['index']}｜{item.get('time_range', '未标注')}】\n{item['text']}"
            for item in _sort_processed(state.get("revised_sections", []))
        )
        qa_bundle = "\n\n".join(
            f"【分区 {item['index']}｜{item.get('time_range', '未标注')}】\n{item['text']}"
            for item in _sort_processed(state["qa_sections"])
        )
        user_prompt = (
            "请只基于以下流程产物做质检，不要补写纪要，也不要把原始分区或修正稿中的信息补进最终纪要。\n\n"
            f"【原始分区】\n{original_bundle}\n\n"
            f"【修正稿】\n{revised_bundle}\n\n"
            f"【全部 Q&A】\n{qa_bundle}\n\n"
            f"【最终会议纪要】\n{state['final_summary']}"
        )
        qc_report = client.chat(QC_PROMPT, user_prompt, temperature=0.1)
        return {"qc_report": qc_report}

    graph = StateGraph(PipelineState)
    graph.add_node("divide_transcript", divide_transcript)
    graph.add_node("revise_section", revise_section)
    graph.add_node("qa_section", qa_section)
    graph.add_node("summarize", summarize)
    graph.add_node("quality_check", quality_check)

    graph.add_edge(START, "divide_transcript")
    graph.add_conditional_edges("divide_transcript", send_to_revision, ["revise_section"])
    graph.add_conditional_edges("revise_section", send_to_qa, ["qa_section"])
    graph.add_edge("qa_section", "summarize")
    graph.add_edge("summarize", "quality_check")
    graph.add_edge("quality_check", END)
    return graph.compile()
