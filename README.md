# 投资访谈会议纪要多智能体流水线

这是一个纯代码版 LangGraph 工作流，用 DeepSeek API 执行：

1. 划分智能体：只看原始转录，按完整问答边界切分。
2. 修正智能体：并行处理，每个分区可看 BP/背景材料 + 当前原始分区。
3. Q&A 智能体：在所有修正完成后启动，并行处理；每个 Q&A 节点只看对应修正稿。
4. 总结智能体：只看全部 Q&A，不看 BP、原文或修正稿。
5. 质检智能体：检查流程隔离、格式和事实一致性。
6. 项目录入智能体（可选）：只在会议纪要完成后启动，读取最终纪要 + BP + 企查查/工商 + 其他补充资料，生成新版项目录入 JSON 和 Excel。

注意：企查查/工商资料只用于项目录入阶段，不会进入会议纪要修正、Q&A 或总结链路。

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

运行时终端会默认显示进度，例如当前处于划分、修正、QA、总结、质检或 Word/项目录入导出阶段。若不需要进度显示，可加 `--no-progress`。

程序会默认把各阶段产物保存到输出目录下的 `.checkpoint`，包括分区、单分区修正、单分区 Q&A、最终总结、质检报告和项目录入 JSON。若中途失败，下一次使用同一个 `--out-dir` 并加 `--resume` 即可复用已完成阶段，避免重复调用 API：

```powershell
python run_pipeline.py --transcript inputs/transcript.txt --background inputs/background.txt --out-dir outputs --resume
```

如果要强制丢弃旧断点重新跑，加 `--clear-checkpoint`；如果要把断点放到指定位置，加 `--checkpoint-dir path\to\checkpoint`。

如果 BP 之外还有图片材料，可传入图片文件或图片目录。程序会生成一版增强 BP，修正智能体使用增强 BP；QA 和总结仍不直接读取 BP。最终会议纪要末尾会附上这些图片。
如果同时传入原始 BP PDF，程序会在原 PDF 后追加去重后的图片页，额外输出一版新的增强 BP PDF。

```powershell
python run_pipeline.py --transcript inputs/transcript.txt --background inputs/background.txt --background-pdf inputs/bp.pdf --background-image inputs/project_images --out-dir outputs
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

如果需要在生成会议纪要后同步生成项目录入表，额外传入企查查/工商资料和新版项目表模板：

```powershell
python run_pipeline.py `
  --transcript inputs/transcript.txt `
  --background inputs/background.txt `
  --out-dir outputs `
  --max-concurrency 4 `
  --company 硕成集团 `
  --date 2026年07月13日 `
  --participants-file inputs/participants.txt `
  --docx-template "C:\Users\27851\xwechat_files\wxid_212yrh4z0oft22_bea2\msg\file\2026-07\新样式.docx" `
  --background-pdf inputs/bp.pdf `
  --background-image inputs/project_images `
  --qcc-material inputs/qcc.xlsx `
  --intake-material inputs/other_material.docx `
  --intake-template "C:\Users\27851\Desktop\冯源资本\SKILL\PeSKILL-main\PeSKILL-main\investment-project-intake\assets\项目表-录入参考指引.xlsx" `
  --project-source 夏磊
```

`--qcc-material` 可以重复传入多个企查查/工商文件；`--intake-material` 可以重复传入其他只用于项目录入的补充资料。

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
- `2026年07月07日_联芯科技_增强BP.pdf`：可选，在原 BP PDF 后追加去重图片后的新版 BP
- `2026年07月07日_联芯科技_质检报告.md`：质检报告
- `2026年07月07日_联芯科技_项目录入草稿.json`：可选，项目录入 JSON
- `2026年07月07日_联芯科技_项目录入.xlsx`：可选，新版 A:Q 项目表
- `2026年07月07日_联芯科技_项目录入校验提示.md`：可选，项目录入校验提示
