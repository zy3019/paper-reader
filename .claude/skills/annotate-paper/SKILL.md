---
name: annotate-paper
description: 把学术论文（PDF 路径或粘贴的文本）做成双栏批注 HTML：英中对照、五类高亮、逐段批注、论证结构总览。用户说“批注这篇”“精读这篇论文”“把论文做成批注 HTML”时使用。
argument-hint: <论文 PDF 路径> [课程信息]
---

把这篇论文做成双栏批注 HTML：$ARGUMENTS

1. 完整阅读项目根目录的 `GUIDE.md`（和 `build.py` 在同一个目录），严格按其中的流程和格式做。`notes/demo-ethics-of-belief.md` 是一份完整的示例。
2. 不手写 HTML，也不改 `template.html`。只写 `notes/<名字>.md`，用 `build.py` 生成 `output/<名字>.html`。
3. 没有给论文时，先向用户要 PDF 路径（或请他把 PDF 放进 `papers/`）。没有给课程信息时问一次，用户不想填就留空。
4. 构建通过后，告诉用户输出文件的路径、节数和段数、没有收录的内容及原因。
