import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow import build_graph


class FakeClient:
    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        if "严格 JSON" in system_prompt:
            return """{
              "sections": [
                {
                  "index": 1,
                  "time_range": "00:00-01:00",
                  "approx_chars": 20,
                  "topic": "测试1",
                  "split_reason": "测试",
                  "text": "投资人：问题一\\n公司：回答一"
                },
                {
                  "index": 2,
                  "time_range": "01:00-02:00",
                  "approx_chars": 20,
                  "topic": "测试2",
                  "split_reason": "测试",
                  "text": "投资人：问题二\\n公司：回答二"
                }
              ]
            }"""
        if "转录修正智能体" in system_prompt:
            return "修正稿"
        if "Q&A 整理智能体" in system_prompt:
            return "【时间范围：测试】\nQ：测试问题？\nA：测试回答。"
        if "会议总结智能体" in system_prompt:
            return "最终纪要"
        return "质检报告"


def main() -> None:
    graph = build_graph(FakeClient())
    result = graph.invoke(
        {"raw_transcript": "测试转录", "background_materials": "测试背景"},
        config={"max_concurrency": 2},
    )
    assert len(result["sections"]) == 2
    assert len(result["revised_sections"]) == 2
    assert len(result["qa_sections"]) == 2
    assert result["final_summary"] == "最终纪要"
    assert result["qc_report"] == "质检报告"
    print("smoke ok")


if __name__ == "__main__":
    main()
