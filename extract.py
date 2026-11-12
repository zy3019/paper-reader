#!/usr/bin/env python3
"""PDF -> 纯文本：批注时从这里逐字取英文原文，构建时用它核对原文有没有被改写。

用法:
    python extract.py papers/paper.pdf              # 输出 notes/paper.source.txt
    python extract.py papers/paper.pdf -o x.txt

优先用 pdftotext（Git for Windows 自带），没有就用 pypdf（pip install pypdf）。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_pdftotext():
    exe = shutil.which("pdftotext")
    if exe:
        return exe
    candidates = []
    git = shutil.which("git")
    if git:
        g = Path(git).resolve().parent
        candidates += [g / "pdftotext.exe", g.parent / "mingw64" / "bin" / "pdftotext.exe"]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(env)
        if base:
            candidates += [
                Path(base) / "Git" / "mingw64" / "bin" / "pdftotext.exe",
                Path(base) / "Programs" / "Git" / "mingw64" / "bin" / "pdftotext.exe",
            ]
    return next((str(c) for c in candidates if c.is_file()), None)


def main():
    for stream in (sys.stdout, sys.stderr):
        if os.environ.get("MSYSTEM"):
            stream.reconfigure(encoding="utf-8")
        stream.reconfigure(errors="replace")

    ap = argparse.ArgumentParser(description="PDF -> 纯文本")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="输出路径（默认 notes/<同名>.source.txt）")
    args = ap.parse_args()
    if not args.pdf.is_file():
        print(f"[错误] 找不到文件：{args.pdf}")
        return 1

    out = args.output or ROOT / "notes" / (args.pdf.stem + ".source.txt")
    out.parent.mkdir(parents=True, exist_ok=True)

    exe = find_pdftotext()
    if exe:
        subprocess.run([exe, "-enc", "UTF-8", str(args.pdf), str(out)], check=True)
        tool = "pdftotext"
    else:
        try:
            from pypdf import PdfReader
        except ImportError:
            print("[错误] 既没有 pdftotext 也没有 pypdf。装一个即可：pip install pypdf")
            return 1
        pages = PdfReader(str(args.pdf)).pages
        out.write_text("\f".join((p.extract_text() or "") for p in pages), encoding="utf-8")
        tool = "pypdf"

    text = out.read_text(encoding="utf-8", errors="replace")
    pages = max(1, text.count("\f") + (0 if text.endswith("\f") else 1))
    chars = len(text.strip())
    print(f"已提取 {out}（{tool}，{pages} 页，{chars} 字符）")
    if chars / pages < 300:
        print("[提醒] 每页文字很少——这份 PDF 多半是扫描件，提取不到文字。请直接读 PDF 页面图像，"
              "构建时不要加 --source。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
