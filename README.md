# 论文轻校对·通用版

想让 AI 少改几句，又能逐段查到改过什么？这个版本从一份英文原稿出发，连续做三轮英中往返，保存六次原始译文。你可以交整篇论文、指定章节，也可以只交 Turnitin 标蓝的字句。

| 怎么用 | 从哪里开始 |
| --- | --- |
| 在 Codex 中使用，一个技能覆盖所有选项 | [下载通用技能 ZIP](https://github.com/BiwayTong/paper-proofread/releases/latest/download/paper-proofread.zip) |
| 在其他 AI 对话里直接使用 | [打开通用提示词并复制](PROMPT.md) · [下载单文件](https://github.com/BiwayTong/paper-proofread/releases/latest/download/PROMPT.md) |

**在 Codex 中**，解压 ZIP，把里面含有 `SKILL.md` 的 `paper-proofread` 文件夹放到 `~/.codex/skills/`（自定义了 `CODEX_HOME` 时放到其 `skills/`）。新开一个对话，附上文件，像这样写：

```text
请用 $paper-proofread 和苹果翻译校对这份 Word 的讨论部分，跑完三轮，尽量保留原句。
```

```text
请用 $paper-proofread，只处理报告中标蓝的字句。用 Google 翻译，开启表达复核，完成后放回所附的同版 Word 副本。
```

**在其他 AI 对话中**，打开提示词文件，在 GitHub 文件页复制原文，粘贴到对话并附上稿件。填好修改范围、翻译服务和表达复核选项。若对话工具无法直接使用指定服务，它会交付当前待译表；你把从该服务取得的译文贴回去，即可接着上一轮继续。

## 选哪一个

| 名称 | 适合什么情况 |
| --- | --- |
| [论文轻校对](https://github.com/BiwayTong/paper-revision-translation-only) | 想固定只做内容核对和必要校对。 |
| [论文轻校对·表达复核](https://github.com/BiwayTong/apple-translate-paper-revision) | 想固定在第三轮英文回译后用 Humanizer 再看一次措辞。 |
| **论文轻校对·通用版** | 想只装一次，在同一个对话入口选苹果或 Google、普通正文或标蓝范围；表达复核默认关闭，按次开启。 |

## 准备材料

普通稿支持 Word（.docx）、UTF-8 文本或直接粘贴。标蓝回填需要报告 PDF 和送检时的同版 Word；仅有摘录时可以先拿到编号定稿。苹果翻译可用 Mac 快捷指令或手动回传。Google 可使用翻译网页，或使用自己的 Google Cloud Translation 项目（可能计费）。用于处理 Word 和 PDF 的 Python 环境需要相应依赖。[操作说明](references/operations.md)

最终会得到英文定稿、每轮四份稿件、重点段落三栏对照、修改记录与待核实项、正文词数与统计范围。三轮结束后，你可以按编号追溯任何一个改动。内置表达复核采用 Humanizer 3.1.0。[指南与许可证](references/humanizer/)
