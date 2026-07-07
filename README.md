# 投资访谈会议纪要多智能体流水线

这是一个纯代码版 LangGraph 工作流，用 DeepSeek API 执行：

1. 划分智能体：只看原始转录，按完整问答边界切分。
2. 修正智能体：并行处理，每个分区可看 BP/背景材料 + 当前原始分区。
3. Q&A 智能体：在所有修正完成后启动，并行处理；每个 Q&A 节点只看对应修正稿。
4. 总结智能体：只看全部 Q&A，不看 BP、原文或修正稿。
5. 质检智能体：检查流程隔离、格式和事实一致性。

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env`，填写：

```text
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

## 运行

把会议原始转录保存为 UTF-8 文本，例如 `inputs/transcript.txt`；把 BP/背景资料保存为 `inputs/background.txt`。

```powershell
python run_pipeline.py --transcript inputs/transcript.txt --background inputs/background.txt --out-dir outputs --max-concurrency 4
```

如果需要同时生成 Word 版最终纪要，传入模板：

```powershell
python run_pipeline.py --transcript inputs/transcript.txt --background inputs/background.txt --out-dir outputs --max-concurrency 4 --company 联芯科技 --date 2026年07月07日 --participants-file inputs/participants.txt --docx-template "C:\Users\27851\xwechat_files\wxid_212yrh4z0oft22_bea2\msg\file\2026-07\新样式.docx"
```

`participants.txt` 示例：

```text
冯源资本    任路遥    张凯 王伟航
洪启（公司）    洪总
```

如果没有背景资料：

```powershell
python run_pipeline.py --transcript inputs/transcript.txt --out-dir outputs
```

## 输出

`outputs` 下会生成：

文件名统一为“日期_公司_文件类型”：

- `2026年07月07日_联芯科技_分区结果.json`：划分结果
- `2026年07月07日_联芯科技_录音修正第1部分.md`：单分区修正稿
- `2026年07月07日_联芯科技_录音修正汇总.md`：全部修正稿按时间顺序拼接版
- `2026年07月07日_联芯科技_QA整理第1部分.md`：单分区 Q&A
- `2026年07月07日_联芯科技_QA整理汇总.md`：全部 Q&A 按时间顺序拼接版
- `2026年07月07日_联芯科技_会议纪要.md`：最终会议纪要 Markdown
- `2026年07月07日_联芯科技_会议纪要.docx`：套用指定 Word 模板后的最终会议纪要
- `2026年07月07日_联芯科技_质检报告.md`：质检报告
