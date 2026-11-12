#!/usr/bin/env python3
"""批注稿 (.md) -> 单文件双栏批注 HTML。

用法:
    python build.py notes/paper.md                       # 输出 output/paper.html
    python build.py notes/paper.md -o some/where.html
    python build.py notes/paper.md --source notes/paper.source.txt   # 顺带核对英文原文是否照录
    python build.py notes/paper.md --index               # 只列出段落编号，方便写 ¶N 引用

批注稿格式见 GUIDE.md。只用标准库。
"""
import argparse
import html
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DIMS = {
    "thesis": "核心论点",
    "concept": "关键概念",
    "evidence": "实证证据",
    "concession": "让步/反驳",
    "method": "方法论",
}
P_FIELDS = ("en", "zh", "func", "role", "note", "tag", "label")
P_REQUIRED = ("en", "zh", "func", "role", "note")
S_FIELDS = ("question", "thesis", "evidence", "rebuttal", "conclusion", "claim", "strongest", "weakest")
STEPS = (
    ("question", "问题", "q"),
    ("thesis", "论点", "t"),
    ("evidence", "证据", "e"),
    ("rebuttal", "反驳", "r"),
    ("conclusion", "结论", "c"),
)
PASS_TAGS = ("i", "em", "b", "strong", "sup", "sub")

DIM_TAG = re.compile(r"<(/?)(%s)>" % "|".join(DIMS))
ANY_TAG = re.compile(r"</?([A-Za-z][\w-]*)>")
FIELD = re.compile(r"^\[([a-z]+)\][ \t]*(.*)$")
META = re.compile(r"^([A-Za-z_]+)\s*[:：]\s*(.*)$")
PREF = re.compile(r"¶\s?(\d+)")


# ───────────────────────── 解析 ─────────────────────────

def join_lines(parts):
    """把一个字段的多行并成一段：中英文交界才补空格，纯中文换行不补。"""
    out = ""
    for s in (p.strip() for p in parts):
        if not s:
            continue
        if out and (out[-1].isascii() or s[0].isascii()):
            out += " "
        out += s
    return out


def split_heading(s):
    en, _, zh = s.partition("|")
    return en.strip(), zh.strip()


def parse(text):
    lines = text.lstrip("﻿").splitlines()
    errors = []
    meta = {}
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip() == "---":
        i += 1
        while i < len(lines) and lines[i].strip() != "---":
            m = META.match(lines[i].strip())
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
            elif lines[i].strip():
                errors.append(f"第 {i + 1} 行：文件头里无法识别「{lines[i].strip()[:30]}」（应为 key: value）")
            i += 1
        i += 1
    else:
        errors.append("缺少文件头：第一行应为 ---，其后是 title: / course: 等，再以 --- 结束")

    sections, summary = [], None
    block = None      # 当前 @p 或 @summary 的 dict
    allowed = ()
    field = None

    def flush():
        nonlocal block, field
        if block is not None:
            block["fields"] = {k: join_lines(v) for k, v in block["raw"].items()}
            del block["raw"]
        block, field = None, None

    for n in range(i, len(lines)):
        ln = lines[n]
        s = ln.strip()
        if s.startswith("## "):
            flush()
            if not sections:
                errors.append(f"第 {n + 1} 行：小节标题「{s}」之前还没有 # 章节")
                continue
            en, zh = split_heading(s[3:])
            sections[-1]["items"].append({"type": "h", "en": en, "zh": zh})
        elif s.startswith("# "):
            flush()
            en, zh = split_heading(s[2:])
            sections.append({"en": en, "zh": zh, "items": []})
        elif s.startswith("@skip"):
            flush()
            if sections:
                sections[-1]["items"].append({"type": "skip", "text": s[5:].strip() or "此处有省略"})
            else:
                errors.append(f"第 {n + 1} 行：@skip 之前还没有 # 章节")
        elif s == "@p":
            flush()
            block = {"type": "p", "line": n + 1, "raw": {}}
            allowed = P_FIELDS
            if not sections:
                errors.append(f"第 {n + 1} 行：@p 之前还没有 # 章节标题（没有分节的文章也请写一个，如 # Text | 正文）")
                sections.append({"en": "Text", "zh": "正文", "items": []})
            sections[-1]["items"].append(block)
        elif s == "@summary":
            flush()
            if summary is not None:
                errors.append(f"第 {n + 1} 行：@summary 出现了不止一次")
            block = summary = {"type": "summary", "line": n + 1, "raw": {}}
            allowed = S_FIELDS
        else:
            m = FIELD.match(s)
            if block is not None and m and m.group(1) in allowed:
                field = m.group(1)
                if field in block["raw"]:
                    errors.append(f"第 {n + 1} 行：[{field}] 在同一块里重复出现")
                block["raw"][field] = [m.group(2)]
            elif block is not None and field:
                block["raw"][field].append(ln)
            elif s:
                errors.append(f"第 {n + 1} 行：这行不属于任何字段「{s[:30]}」")
    flush()
    return {"meta": meta, "sections": sections, "summary": summary}, errors


# ───────────────────────── 校验 ─────────────────────────

def strip_tags(s):
    return ANY_TAG.sub("", s)


def check_highlight_tags(en):
    """高亮标签必须成对、不嵌套。返回 (问题列表, 各维度高亮字符数)。"""
    problems, counts = [], {d: 0 for d in DIMS}
    open_name, open_at = None, 0
    for m in DIM_TAG.finditer(en):
        closing, name = m.group(1), m.group(2)
        if not closing:
            if open_name:
                problems.append(f"<{name}> 嵌套在 <{open_name}> 里（高亮不能嵌套或交叉）")
            open_name, open_at = name, m.end()
        else:
            if open_name != name:
                problems.append(f"</{name}> 前面没有对应的 <{name}>")
            else:
                counts[name] += len(strip_tags(en[open_at:m.start()]))
            open_name = None
    if open_name:
        problems.append(f"<{open_name}> 没有闭合")
    return problems, counts


def validate(doc):
    errors, warnings = [], []
    meta = doc["meta"]
    if not meta.get("title"):
        errors.append("文件头缺少 title")
    if not meta.get("course"):
        warnings.append("文件头没有 course（课程信息）——顶栏只会显示论文名")

    paras = [it for sec in doc["sections"] for it in sec["items"] if it["type"] == "p"]
    if not paras:
        errors.append("没有任何 @p 段落")
    for sec in doc["sections"]:
        if not any(it["type"] == "p" for it in sec["items"]):
            warnings.append(f"章节「{sec['en']}」下面没有段落")

    total = {d: 0 for d in DIMS}
    for num, p in enumerate(paras, 1):
        p["num"] = num
        f = p["fields"]
        where = f"¶{num}（第 {p['line']} 行）"
        for k in P_REQUIRED:
            if not f.get(k):
                errors.append(f"{where}：缺少 [{k}]")
        en = f.get("en", "")
        problems, counts = check_highlight_tags(en)
        errors += [f"{where}：{x}" for x in problems]
        for m in ANY_TAG.finditer(en):
            if m.group(1) not in DIMS and m.group(1) not in PASS_TAGS:
                warnings.append(f"{where}：[en] 里的 {m.group(0)} 不是可用标签，会按原样显示")
        for k in ("zh", "func", "role", "note"):
            if DIM_TAG.search(f.get(k, "")):
                errors.append(f"{where}：[{k}] 里不能有高亮标签（只有 [en] 可以高亮）")
        tag = f.get("tag", "").lower()
        if tag and tag not in DIMS:
            errors.append(f"{where}：[tag] 只能是 {' / '.join(DIMS)}，现在是「{tag}」")
            tag = ""
        if not tag and any(counts.values()):
            tag = max(counts, key=counts.get)
        p["tag"] = tag
        plain = strip_tags(en)
        p["plain"] = plain
        p["words"] = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", plain))
        marked = sum(counts.values())
        if p["words"] >= 40 and plain and marked / len(plain) > 0.6:
            warnings.append(f"{where}：高亮占了 {marked * 100 // len(plain)}%——高亮太多等于没有高亮，只标关键短语")
        for d in DIMS:
            total[d] += 1 if counts[d] else 0

    nmax = len(paras)
    def check_refs(text, where):
        for m in PREF.finditer(text):
            if not 1 <= int(m.group(1)) <= nmax:
                warnings.append(f"{where}：引用了不存在的 ¶{m.group(1)}（全文共 {nmax} 段）")
    for p in paras:
        for k in ("role", "note"):
            check_refs(p["fields"].get(k, ""), f"¶{p['num']} 的 [{k}]")

    sm = doc["summary"]
    if sm is None:
        errors.append("缺少 @summary（底部论证结构总览）")
    else:
        for k in S_FIELDS:
            if not sm["fields"].get(k):
                errors.append(f"@summary 缺少 [{k}]")
            check_refs(sm["fields"].get(k, ""), f"@summary 的 [{k}]")

    unused = [DIMS[d] for d in DIMS if not total[d]]
    if paras and unused:
        warnings.append("全文没有用到的高亮维度：" + "、".join(unused) + "（论文确实没有这类内容就不用管）")
    return paras, total, errors, warnings


def norm(s):
    s = unicodedata.normalize("NFKD", s).lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def check_source(paras, source_text):
    """[en] 是否逐字照录：把每段切成 6 词小块，看有多少块能在源文本里找到。"""
    src = norm(source_text)
    warnings, matched = [], 0
    for p in paras:
        words = p["plain"].split()
        chunks = [norm(" ".join(words[i:i + 6])) for i in range(0, len(words), 6)]
        chunks = [c for c in chunks if c]
        if not chunks:
            continue
        hit = [c for c in chunks if c in src]
        matched += sum(len(c) for c in hit)
        ratio = len(hit) / len(chunks)
        if ratio < 0.85:
            warnings.append(
                f"¶{p['num']}（第 {p['line']} 行）：只有 {ratio:.0%} 能在源文本里逐字找到——"
                "可能被改写、漏词，或源文本在此处有跨页/分栏断裂，请对照原文"
            )
    coverage = matched / len(src) if src else 0
    return warnings, coverage


# ───────────────────────── 渲染 ─────────────────────────

def esc(s):
    return html.escape(s, quote=True)


def inline(text, highlight=False, refs=False):
    s = html.escape(text, quote=False)
    for t in PASS_TAGS:
        s = s.replace(f"&lt;{t}&gt;", f"<{t}>").replace(f"&lt;/{t}&gt;", f"</{t}>")
    if highlight:
        for d in DIMS:
            s = s.replace(f"&lt;{d}&gt;", f'<mark class="hl {d}">').replace(f"&lt;/{d}&gt;", "</mark>")
    if refs:
        s = PREF.sub(r'<a class="pref" href="#p\1">¶\1</a>', s)
    return s


def render(doc, template):
    meta = doc["meta"]
    title = meta.get("title", "")
    nav, body = [], []

    for si, sec in enumerate(doc["sections"], 1):
        sid = f"s{si}"
        nav.append(f'    <a href="#{sid}">{esc(sec["zh"] or sec["en"])}</a>')
        zh = f'<span class="st-zh">{esc(sec["zh"])}</span>' if sec["zh"] else ""
        body.append(f'  <section class="sec" id="{sid}">')
        body.append(f'    <h2 class="sec-title"><span class="st-en">{esc(sec["en"])}</span>{zh}</h2>')
        for it in sec["items"]:
            if it["type"] == "h":
                zh = f'<span class="st-zh">{esc(it["zh"])}</span>' if it["zh"] else ""
                body.append(f'    <h3 class="sub-title"><span class="st-en">{esc(it["en"])}</span>{zh}</h3>')
                continue
            if it["type"] == "skip":
                body.append(f'    <div class="skiprow"><p class="skip">{esc(it["text"])}</p></div>')
                continue
            f, n = it["fields"], it["num"]
            label = f'<span class="plabel">{esc(f["label"])}</span>' if f.get("label") else ""
            tag = f' tag-{it["tag"]}' if it["tag"] else ""
            body.append(
                f'    <article class="row" id="p{n}">\n'
                f'      <div class="text">\n'
                f'        <div class="pno">¶{n}{label}</div>\n'
                f'        <p class="en" lang="en">{inline(f["en"], highlight=True)}</p>\n'
                f'        <div class="zh"><p>{inline(f["zh"])}</p></div>\n'
                f'      </div>\n'
                f'      <aside class="note{tag}" aria-label="¶{n} 批注">\n'
                f'        <div class="ni ni-func"><span class="nk">段落功能</span><span class="func">{inline(f["func"])}</span></div>\n'
                f'        <div class="ni"><span class="nk">逻辑角色</span><p>{inline(f["role"], refs=True)}</p></div>\n'
                f'        <div class="ni"><span class="nk">技巧 / 漏洞</span><p>{inline(f["note"], refs=True)}</p></div>\n'
                f'      </aside>\n'
                f'    </article>'
            )
        body.append("  </section>")
    nav.append('    <a class="to-overview" href="#overview">论证总览</a>')

    mast = ['  <section class="masthead">', f"    <h1>{esc(title)}</h1>"]
    if meta.get("title_zh"):
        mast.append(f'    <p class="title-zh">{esc(meta["title_zh"])}</p>')
    bits = [(k, lab) for k, lab in (("authors", "作者"), ("source", "出处"), ("course", "课程")) if meta.get(k)]
    if bits:
        mast.append('    <div class="meta">' + "".join(f"<span><b>{lab}</b>{esc(meta[k])}</span>" for k, lab in bits) + "</div>")
    if meta.get("note"):
        mast.append(f'    <p class="mnote">{esc(meta["note"])}</p>')
    mast.append("  </section>")

    sm = doc["summary"]["fields"]
    ov = ['  <section class="overview" id="overview">', "    <h2>论证结构总览</h2>",
          '    <div class="ov-k">全文逻辑骨架</div>', '    <div class="flow">']
    for i, (key, lab, cls) in enumerate(STEPS, 1):
        ov.append(f'      <div class="step {cls}"><div class="step-k"><span>{i:02d}</span>{lab}</div>{inline(sm[key], refs=True)}</div>')
    ov += [
        "    </div>",
        f'    <div class="claim"><div class="ov-k">作者核心主张 · 一句话</div><p>{inline(sm["claim"], refs=True)}</p></div>',
        '    <div class="sw">',
        f'      <div class="sw-card strong"><div class="ov-k">论证最强处</div><p>{inline(sm["strongest"], refs=True)}</p></div>',
        f'      <div class="sw-card weak"><div class="ov-k">论证最弱处</div><p>{inline(sm["weakest"], refs=True)}</p></div>',
        "    </div>", "  </section>",
    ]

    course = f'<span class="course">{esc(meta["course"])}</span>' if meta.get("course") else ""
    parts = {
        "PAGE_TITLE": esc(title) + " · 双栏批注",
        "HEADER_TITLE": esc(title),
        "COURSE": course,
        "NAV": "\n".join(nav),
        "MASTHEAD": "\n".join(mast),
        "BODY": "\n".join(body),
        "OVERVIEW": "\n".join(ov),
    }
    return re.sub(r"@@([A-Z_]+)@@", lambda m: parts[m.group(1)], template)


# ───────────────────────── 入口 ─────────────────────────

def main():
    # Git Bash 按 UTF-8 读输出，PowerShell / cmd 按系统代码页读；两边都别崩。
    for stream in (sys.stdout, sys.stderr):
        if os.environ.get("MSYSTEM"):
            stream.reconfigure(encoding="utf-8")
        stream.reconfigure(errors="replace")

    ap = argparse.ArgumentParser(description="批注稿 (.md) -> 单文件双栏批注 HTML")
    ap.add_argument("notes", type=Path, help="批注稿路径，如 notes/paper.md")
    ap.add_argument("-o", "--output", type=Path, help="输出路径（默认 output/<同名>.html）")
    ap.add_argument("--source", type=Path, help="extract.py 提取的原文文本，用来核对 [en] 是否照录")
    ap.add_argument("--index", action="store_true", help="只列出段落编号与开头，不生成 HTML")
    args = ap.parse_args()

    doc, errors = parse(args.notes.read_text(encoding="utf-8-sig"))
    paras, total, verrors, warnings = validate(doc)
    errors += verrors

    if args.index:
        for sec in doc["sections"]:
            print(f"# {sec['en']}")
            for it in sec["items"]:
                if it["type"] == "p":
                    print(f"  ¶{it['num']:<3} {' '.join(it['plain'].split()[:9])} …")
        return 1 if errors else 0

    coverage = None
    if args.source and paras:
        sw, coverage = check_source(paras, args.source.read_text(encoding="utf-8-sig", errors="replace"))
        warnings += sw

    for w in warnings:
        print(f"[提醒] {w}")
    if errors:
        for e in errors:
            print(f"[错误] {e}")
        print(f"\n共 {len(errors)} 处错误，未生成 HTML。改完批注稿再运行一次。")
        return 1

    out = args.output or ROOT / "output" / (args.notes.stem + ".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(doc, (ROOT / "template.html").read_text(encoding="utf-8")), encoding="utf-8")

    words = sum(p["words"] for p in paras)
    print(f"已生成 {out}")
    print(f"  {len(doc['sections'])} 节 · {len(paras)} 段 · 英文约 {words} 词")
    print("  含高亮的段落数：" + "  ".join(f"{DIMS[d]} {total[d]}" for d in DIMS))
    if coverage is not None:
        print(f"  批注稿覆盖了源文本的约 {coverage:.0%}（参考文献、页眉页脚、图表不收录，所以不会到 100%；明显偏低说明有段落漏了）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
