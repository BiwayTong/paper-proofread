# 运行与恢复

从技能目录调用下列脚本，示例路径按实际文件调整。使用 Python 3.9 或以上。普通 TXT 和手动翻译表只需标准库；Word 需要 lxml，报告矩形提取还需要支持 `extract_text_lines` 的 pdfplumber。使用干净的任务目录，原件另存。安装文档依赖可在自己的 Python 环境中运行 `python -m pip install lxml 'pdfplumber>=0.10'`。

## 准备选区

普通稿先列出段落，再按章节与上下文选取编号。粘贴文字先原样保存为 UTF-8 TXT。纯正文可选 `--blocks all`。指定半句时用精确的起止位置和原格式编辑工具，不能直接选整段回填。

```sh
python scripts/manuscript.py list paper.docx
python scripts/manuscript.py prepare paper.docx job --blocks B003-B005,B009
```

标蓝报告先查看正文范围、填色和页边距。下例页码、高度和颜色须换为实际测得的值。程序处理填色矩形，逐字核对整篇 Word；仅有批注、扫描件或复杂版面时，人工核实图面与 Word 精确位置后再处理。遇到歧义时保留原句并标出位置。

```sh
mkdir job
python scripts/highlights.py inspect report.pdf
python scripts/highlights.py extract report.pdf submitted.docx job/scope.json --pages 3 8 --y 50 790 --rgb 0.3203 0.7773 0.8555
```

已有编号摘录时可新建 `job/scope.json`，如 `{"spans":[{"id":"P001","text":"The study covered two sites.","pages":[]}]}`。页码已知时填实际页码。该清单可翻译并打包；回填须补齐核实过的准确位置和同版底稿指纹。

按选区建立 `job/baseline.json`，格式为 `{"P001":"The study covered two sites."}`。编号须与选区完全一致。把保留清单和核实依据写入 `job/review.md`。用文件表达调整稿，勿在服务的原始输出中修改。

## 每轮两个方向

每条命令只执行一个方向。以下以第一轮为例。先选择对应服务的操作方式。

| 操作方式 | 英译中的命令 |
| --- | --- |
| Mac 苹果翻译 | `python scripts/rounds.py job 1 zh --provider apple --shortcut "英译中"` |
| Google Cloud | `python scripts/rounds.py job 1 zh --provider google --cloud` |
| 手动往返，示例为 Google | `python scripts/rounds.py job 1 zh --provider google --export-form r1-zh.json` |

苹果快捷指令应接收文本，调用苹果的「翻译文本」动作，返回普通文本；为两个方向分别指定真实的快捷指令名称，先用短句核实语言方向。Google Cloud 需已启用 Cloud Translation 的项目，在本地设置 `GOOGLE_TRANSLATE_API_KEY`，或安装 `google-auth[requests]` 并配置应用默认凭据。用户选择网页方式时直接打开实际的 [Google 翻译网页](https://translate.google.com/)。

手动方式对 Apple 和 Google 均可用。导出后，按表中方向逐段把 `source` 交给所选服务，完整原样填入对应 `translation`。导入使用 `--import-form r1-zh.json` 替代导出参数，保留轮次、方向、服务与源文。仅导入真实取得、来源已确认的译文。命令会保存已返回的编号，列出尚缺的编号。再次运行同一步可接续进度，每个方向使用独立表名。

1. 完成英译中后，从 `r1-zh-raw.json` 另存中文调整稿 `r1-zh-edit.json`，保持全部编号，并在记录中标明作者稿或建议稿。
2. 将命令中的 `zh` 换为 `en`；快捷指令换为中译英，手动表换为 `r1-en.json`。程序读取本轮中文调整稿，取得英文回译后写入 `r1-en-raw.json`。对照基准稿纠正偏移，再写 `r1-en-edit.json`。
3. 第二、三轮将数字换为 `2`、`3`。程序逐段复核前序记录，并自动读取上一轮调整后的英文。第三轮英文原始文件保存之后，才按所选模式执行一次表达复核。保留服务原文的空白、标点及字符实体；必要纠正在编辑稿中进行。若必须更改已完成步骤的输入，保留旧任务，并在新任务目录根据实际新输入重做受影响的翻译。

## 回填及打包

最后对照检查稿写为 `job/check.json`，最小校对后的定稿写为 `job/final.json`。两者编号与基准稿相同。先回填原件副本，核对正文、修改边界、样式和引用域。普通 Word 自动保留域、链接等保护元素；跨格式或未能自动处理的局部选区按原格式精确编辑并核对。只有摘录时直接交付编号定稿。

```sh
# 普通稿
python scripts/manuscript.py merge paper.docx job revised.docx
# 有完整定位的标蓝稿
python scripts/highlights.py merge submitted.docx job/scope.json job/final.json revised.docx
```

将修改记录、作者/建议稿来源、选用的表达复核方式、待核实项、最终词数和统计口径写进 `job/review.md`。最后运行 `python scripts/package_process.py job process.zip`。它按实际服务验证六组翻译来源和输入，归档每轮四份稿件、逐段对照及原文选区。交付定稿和过程包，并列出未完成事项。
