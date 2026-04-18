# course-note-organizer

一个可配置、可追溯、可集成的课程笔记 Skill，用于把网课视频、Canvas 页面、PPT、字幕、OCR 内容和相关课程材料整理成适合复习的课堂笔记。

这个 Skill 面向 Codex / Agent 工作流，重点解决的是“课堂内容整理”而不是“泛化总结”。它强调：

- 保留真实授课顺序
- 在笔记开头生成时间戳知识点索引表
- 可选引入 Canvas 公告、作业、模块信息作为课程上下文
- 对 OCR 模糊、字幕断层做保守修补
- 在下载、转写、上传、清理中间文件前先征求用户确认
- 输出可继续流转给 NotebookLM、闪卡生成器、考试预测 Agent 的结构化结果

## 使用方式：激活这个skill并将已登录的canvas链接发给agent

## 这个 Skill 会产出什么

默认情况下，它会先生成一个 Markdown 主稿，内容固定包含：

1. 课程/本讲标题
2. 时间戳知识点索引表
3. 可选的 Canvas 课程上下文提示
4. 按真实授课顺序展开的课堂笔记正文
5. 本堂课总结
6. 可见 JSON 元数据代码块

如果用户要求，还可以在 Markdown 主稿基础上继续导出：

- `.docx`
- `.pdf`

## 核心能力

- 基于授课顺序整理课堂笔记
- 生成可回查的时间戳索引
- 按规则引入 Canvas 公告、作业、周次、模块等上下文
- 支持多种笔记风格模板
- 支持字幕归一化、本地 Whisper 转写、远程 API 转写
- 支持 Markdown、Word、PDF 三种交付方式
- 文末输出结构化 JSON 元数据
- 明确标记内容来源：视频、Canvas、转录补全
- 通过统一 schema、错误模型、回复模板提升 Agent 使用稳定性

## 目录结构

```text
course-note-organizer/
|-- SKILL.md
|-- README.md
|-- README.zh-CN.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   `-- rules/
|       |-- agent-response-templates.md
|       |-- canvas-preflight.md
|       |-- capability-boundaries.md
|       |-- error-codes.md
|       |-- export.md
|       |-- intake.md
|       |-- metadata-schema.md
|       |-- repair-and-transcription.md
|       |-- security.md
|       |-- style-presets.md
|       |-- timestamp-index.md
|       `-- transcription-options.md
`-- scripts/
    `-- commands/
        |-- assemble_notes.py
        |-- cleanup_artifacts.py
        |-- export_docx.py
        |-- export_pdf.py
        |-- extract_canvas_audio.py
        |-- inspect_canvas_context.py
        |-- orchestrate_course_notes.py
        |-- transcribe_audio.py
        |-- transcribe_via_assemblyai.py
        |-- transcribe_via_deepgram.py
        |-- transcribe_via_openai.py
        |-- _common.py
        |-- _errors.py
        |-- _markdown_blocks.py
        `-- _schemas.py
```

## 命令层概览

| 命令 | 作用 |
|---|---|
| `inspect_canvas_context.py` | 解析本地 Canvas 导出文件、复制文本或快照，生成结构化课程上下文 |
| `extract_canvas_audio.py` | 从本地媒体文件或可直接访问的媒体 URL 准备音频 |
| `transcribe_audio.py` | 归一化字幕文件，或在本地 Whisper 可用时执行本地转写 |
| `transcribe_via_openai.py` | 通过 OpenAI Audio Transcriptions API 执行远程转写 |
| `transcribe_via_assemblyai.py` | 通过 AssemblyAI 执行远程转写 |
| `transcribe_via_deepgram.py` | 通过 Deepgram 执行远程转写 |
| `assemble_notes.py` | 根据结构化笔记 JSON 生成 Markdown 主稿 |
| `export_docx.py` | 将 Markdown 笔记导出为 Word |
| `export_pdf.py` | 将 Markdown 笔记导出为 PDF |
| `cleanup_artifacts.py` | 预览或删除课程目录下的临时文件 |
| `orchestrate_course_notes.py` | 统一调度组装和导出流程的主入口 |

## 规则层设计

这个 Skill 把“执行动作”和“决策规则”拆开了：

- `SKILL.md`
  - 定义 Skill 的目标、入口流程、调用时机
- `scripts/commands/`
  - 放可执行命令
- `references/rules/`
  - 放 intake、格式、边界、安全、错误码、回复模板等规则

其中几份最关键的规则文件是：

- `capability-boundaries.md`
  - 定义 Skill 能做什么、不能做什么
- `error-codes.md`
  - 定义统一错误码以及默认恢复动作
- `agent-response-templates.md`
  - 定义遇到登录边界、上传确认、抓取失败等情况时的标准回复模板
- `security.md`
  - 定义权限、隐私、文件落地与敏感信息处理规则

## 输入来源

这个 Skill 适合处理以下来源的课程材料：

- 课堂视频
- Canvas 课程主页、公告、作业、模块信息
- PPT 或课件截图
- 手写板书截图
- `.srt` / `.vtt` 字幕文件
- OCR 提取文本
- 教材节选或补充学习材料

## 转写模式

目前支持三种转写路径：

1. 只使用现有字幕
   - 最省依赖
   - 不需要本地模型，也不需要上传音频
2. 本地 Whisper
   - 音频留在本机
   - 适合注重隐私的场景
   - 可能需要安装 Python / 音频相关依赖
3. 远程 API 转写
   - OpenAI
   - AssemblyAI
   - Deepgram
   - 发送音频前必须先征得用户明确同意

## 默认输出目录结构

当用户没有指定输出目录时，Skill 会在当前工作目录下创建课程文件夹，并使用以下子目录：

- `笔记`
- `音频`
- `其他临时文件`

## 安全与权限原则

这是这个 Skill 最重要的设计部分之一。

- 只使用用户自己已登录的浏览器会话访问 Canvas
- 不要求用户提供密码
- 不在 Skill 文件中存储账号、密码、cookie、token
- 默认只读，不执行任何会改动 Canvas 状态的操作
- 下载、批量抓取、转写、远程上传前先征求用户确认
- 不把课程私有数据写入长期规则文件
- 在笔记中明确标注内容来源，避免“无痕混写”

## 错误处理设计

命令层已经统一到一套共享 schema 和错误模型，核心包括：

- `Pydantic` 请求校验
- 统一 manifest 输出
- 机器可读的 `error.code`
- 结构化的恢复建议
- 错误码到回复模板的默认映射

典型错误类别包括：

- `VALIDATION_ERROR`
- `MISSING_SOURCE`
- `MISSING_DEPENDENCY`
- `MISSING_API_KEY`
- `EXTRACTION_FAILED`
- `API_ERROR`
- `TIMEOUT`
- `EXPORT_FAILED`

## 典型工作流

1. 收集课程材料
2. 如果有可用的 Canvas 登录态或导出文件，先做 Canvas preflight
3. 进行 intake，确认笔记风格、导出格式等配置
4. 构建时间戳知识点索引表
5. 按授课顺序整理正文
6. 对模糊段落做保守修补
7. 如有必要，询问是否安装本地 Whisper 或使用远程转写
8. 生成 Markdown 主稿
9. 如有需要，导出 Word 或 PDF
10. 询问是否清理音频、文字稿、截图等中间文件

## 适合什么场景

这个 Skill 特别适合：

- 需要把网课内容整理成可复习笔记
- 需要快速回找知识点和视频位置
- 需要把课堂笔记继续交给下游 Agent 处理
- 需要高安全、低误操作的教育类 Agent 工作流

## 不适合什么场景

这个 Skill 不用于：

- 绕过 Canvas 认证
- 强行抓取受保护的视频流
- 在 Canvas 中执行提交、编辑、删除等状态变更操作
- 未经确认就把课程音频上传到第三方服务
- 把用户课程私有内容长期保留在规则文件中

## 当前状态

当前版本已经具备：

- 模块化命令层
- 分层规则系统
- 统一 schema 与标准错误模型
- 能力边界表
- 错误码文档
- Agent 回复模板
- 错误码到回复模板的默认映射

##局限
本人为纯文科专业，平时并无代码基础，纯兴趣与需求驱使创作此skill，大佬们轻喷！
有建议欢迎多多留言交流~
