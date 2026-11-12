# paper-reader

把学术论文做成双栏批注 HTML：英中对照、五类高亮、逐段批注、论证结构总览。

- 用户给出论文（PDF 路径、`papers/` 里的文件，或粘贴的文本）并要求批注或精读时，先完整阅读 `GUIDE.md`，再按它的流程做。
- 不手写 HTML。只写 `notes/<名字>.md`，用 `python build.py` 生成 `output/<名字>.html`。
- 用户没要求时，不改 `template.html`、`build.py`、`extract.py`。
