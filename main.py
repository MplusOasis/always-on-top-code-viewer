# -*- coding: utf-8 -*-
"""CodePin - 置顶式代码阅览窗

无边框 · 可置顶 · F5 切换点击穿透锁定 · VSCode Dark+ 配色 · 横向滚动阅读
纯标准库实现（仅 tkinter），可用 PyInstaller 打包为单文件 exe。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import sys
import threading
import time

import tkinter as tk
from tkinter import filedialog
from tkinter import font as tkfont

APP_NAME = "CodePin"
APP_VER = "1.0.0"

# ---------------------------------------------------------------- VSCode Dark+ 调色板
C = {
    "bg": "#1E1E1E",
    "titlebar": "#252526",
    "border": "#2B2B2B",
    "fg": "#D4D4D4",
    "dim": "#858585",
    "accent": "#007ACC",
    "hover": "#37373D",
    "sel": "#264F78",
    "comment": "#6A9955",
    "keyword": "#569CD6",
    "control": "#C586C0",
    "string": "#CE9178",
    "number": "#B5CEA8",
    "func": "#DCDCAA",
    "type": "#4EC9B0",
    "var": "#9CDCFE",
    "const": "#4FC1FF",
}

TAG_COLORS = {
    "comment": C["comment"],
    "keyword": C["keyword"],
    "control": C["control"],
    "string": C["string"],
    "number": C["number"],
    "func": C["func"],
    "type": C["type"],
    "var": C["var"],
    "const": C["const"],
}

GUI_FONT = "Microsoft YaHei UI"
MONO_CANDIDATES = ("Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas", "Courier New")

VK_F5, VK_ESCAPE = 0x74, 0x1B
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
SWP_APPLY = SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.GetWindowLongPtrW.argtypes = (wt.HWND, ctypes.c_int)
u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
u32.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_uint)
u32.GetAncestor.restype = wt.HWND
u32.GetAncestor.argtypes = (wt.HWND, ctypes.c_uint)
u32.RegisterHotKey.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint)
u32.RegisterHotKey.restype = wt.BOOL
u32.UnregisterHotKey.argtypes = (wt.HWND, ctypes.c_int)
u32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
u32.PostThreadMessageW.argtypes = (wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
k32.GetCurrentThreadId.restype = wt.DWORD


# ---------------------------------------------------------------- 语言定义
CTRL_KW = frozenset("""
if elif else for while return break continue try except finally with yield await async
raise pass match case switch do default throw catch
""".split())


def _spec(**kw):
    d = {"label": "Text", "exts": (), "mode": "generic", "lc": (), "blk": None,
         "q": "\"'", "tri": (), "keys": False, "kwords": False,
         "kw": frozenset(), "typ": frozenset(), "const": frozenset()}
    for k in ("kw", "typ", "const"):
        if isinstance(kw.get(k), str):
            kw[k] = frozenset(kw[k].split())
    d.update(kw)
    return d


LANGS = {
    "python": _spec(
        label="Python", exts=(".py", ".pyw", ".pyi"), lc=("#",), tri=('"""', "'''"),
        kw="""False None True and as assert class def del from global import in is lambda nonlocal
              not or self cls yield async await""",
        typ="""int float str bool list dict set tuple bytes bytearray object type complex frozenset
               range Exception ValueError TypeError KeyError IndexError RuntimeError""",
        const="""True False None self cls NotImplemented Ellipsis __name__""",
    ),
    "javascript": _spec(
        label="JavaScript", exts=(".js", ".mjs", ".cjs", ".jsx"), lc=("//",), blk=("/*", "*/"),
        q="\"'`", kw="""var let const function class extends return new typeof instanceof in of void
                        delete this super import export from default async await static get set as""",
        typ="""String Number Boolean Object Array Promise Map Set Date RegExp JSON Math console window
               document undefined NaN Infinity""",
        const="""true false null undefined NaN Infinity console""",
    ),
    "typescript": _spec(
        label="TypeScript", exts=(".ts", ".tsx"), lc=("//",), blk=("/*", "*/"), q="\"'`",
        kw="""var let const function class extends implements interface type enum return new typeof
              instanceof in of void delete this super import export from default async await static
              get set as namespace declare abstract public private protected readonly""",
        typ="""string number boolean any unknown never void object Array Promise Map Set Date JSON
               console window document""",
        const="""true false null undefined NaN Infinity console""",
    ),
    "cpp": _spec(
        label="C / C++", exts=(".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"), lc=("//",), blk=("/*", "*/"),
        kw="""auto break case catch class const constexpr continue default delete do else enum explicit
              extern for friend goto if inline namespace new noexcept operator private protected public
              return sizeof static struct switch template this throw try typedef typename union using
              virtual void volatile while nullptr override final""",
        typ="""int float double char bool long short unsigned signed size_t string vector map set
               unordered_map shared_ptr unique_ptr wchar_t""",
        const="""NULL true false nullptr""",
    ),
    "java": _spec(
        label="Java", exts=(".java",), lc=("//",), blk=("/*", "*/"),
        kw="""abstract assert boolean break byte case catch char class const continue default do double
              else enum extends final finally float for goto if implements import instanceof int
              interface long native new package private protected public return short static strictfp
              super switch synchronized this throw throws transient try void volatile while var record""",
        typ="""String Integer Long Double Float Boolean Object List Map Set ArrayList HashMap Optional
               Stream Exception RuntimeException Thread Runnable""",
        const="""true false null""",
    ),
    "csharp": _spec(
        label="C#", exts=(".cs",), lc=("//",), blk=("/*", "*/"),
        kw="""abstract as base bool break byte case catch char checked class const continue decimal
              default delegate do double else enum event explicit extern finally fixed float for
              foreach goto if implicit in int interface internal is lock long namespace new object
              operator out override params private protected public readonly ref return sbyte sealed
              short sizeof stackalloc static string struct switch this throw try typeof uint ulong
              unchecked unsafe ushort using virtual void volatile while var async await yield record""",
        typ="""List Dictionary IEnumerable Task Span Guid DateTime Console""",
        const="""true false null""",
    ),
    "go": _spec(
        label="Go", exts=(".go",), lc=("//",), blk=("/*", "*/"), q="\"`",
        kw="""break case chan const continue default defer else fallthrough for func go goto if import
              interface map package range return select struct switch type var""",
        typ="""bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 rune
               string uint uint8 uint16 uint32 uint64 uintptr""",
        const="""true false nil iota""",
    ),
    "rust": _spec(
        label="Rust", exts=(".rs",), lc=("//",), blk=("/*", "*/"),
        kw="""as async await break const continue crate dyn else enum extern fn for if impl in let loop
              match mod move mut pub ref return self Self static struct super trait type unsafe use
              where while""",
        typ="""bool char str String i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64
               Vec Option Result Box Rc Arc HashMap""",
        const="""true false None Some Ok Err""",
    ),
    "json": _spec(label="JSON", exts=(".json",), keys=True, const="true false null"),
    "html": _spec(label="HTML", exts=(".html", ".htm", ".xml", ".vue", ".svg"), mode="html"),
    "css": _spec(label="CSS", exts=(".css", ".scss", ".less"), mode="css"),
    "sql": _spec(
        label="SQL", exts=(".sql",), lc=("--",), blk=("/*", "*/"),
        kw="""select from where insert into values update set delete create table drop alter add column
              index view join left right inner outer on group by order having limit offset union all
              distinct as and or not null primary key foreign references default""",
        typ="""int varchar char text date datetime timestamp decimal float boolean serial bigint""",
        const="""NULL""",
    ),
    "bash": _spec(
        label="Shell", exts=(".sh", ".bash", ".zsh"), lc=("#",),
        kw="""if then else elif fi for while until do done case esac function return in local export
              readonly source alias unset echo printf read set cd exit""",
        typ="""sudo apt pip python npm git curl wget grep sed awk mkdir rm cp mv ls cat""",
        const="""true false""",
    ),
    "yaml": _spec(label="YAML", exts=(".yml", ".yaml"), lc=("#",), keys=True, kwords=True,
                  const="true false null yes no on off"),
    "text": _spec(label="纯文本"),
}

EXT_MAP = {e: k for k, v in LANGS.items() for e in v["exts"]}

SHORT = {"python": "Python", "javascript": "JS", "typescript": "TS", "cpp": "C/C++",
         "java": "Java", "csharp": "C#", "go": "Go", "rust": "Rust", "json": "JSON",
         "html": "HTML", "css": "CSS", "sql": "SQL", "bash": "Shell", "yaml": "YAML",
         "text": "Text"}

NUM_RE = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|"
                    r"\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?[a-zA-Z]{0,2}")
WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
STR_PREFIX = {"f", "r", "b", "u", "rb", "br", "fr", "rf", "ur"}
ATTR_RE = re.compile(r"[A-Za-z_:@#\[\(\)\-][\w:.\-]*")


def _find_unescaped(line, needle, start):
    k = line.find(needle, start)
    while k > 0 and line[k - 1] == "\\":
        k = line.find(needle, k + len(needle))
    return k


def _scan_string(line, i, q):
    k, n = i + 1, len(line)
    while k < n:
        ch = line[k]
        if ch == "\\":
            k += 2
            continue
        if ch == q:
            return k + 1
        k += 1
    return -1


def _classify(w, line, end, spec):
    if w.startswith("@"):
        return "func"
    if w in spec["const"]:
        return "const"
    if w in spec["kw"]:
        return "control" if w in CTRL_KW else "keyword"
    if w in spec["typ"]:
        return "type"
    if end < len(line) and line[end] == "(":
        return "func"
    if w[:1].isupper() and len(w) > 1:
        return "type"
    return ""


def _scan_generic(line, spec, state):
    toks = []
    i, n = 0, len(line)
    lcs, blk, tri, keys, kwords = spec["lc"], spec["blk"], spec["tri"], spec["keys"], spec["kwords"]
    quotes = spec["q"]
    while i < n:
        if state == "blk":
            end = line.find(blk[1], i)
            if end < 0:
                toks.append((i, n, "comment"))
                return toks, "blk"
            toks.append((i, end + len(blk[1]), "comment"))
            i, state = end + len(blk[1]), ""
            continue
        if state.startswith("tri|"):
            q = state[4:]
            end = _find_unescaped(line, q, i)
            if end < 0:
                toks.append((i, n, "string"))
                return toks, state
            toks.append((i, end + len(q), "string"))
            i, state = end + len(q), ""
            continue

        ch = line[i]
        if ch in " \t\r":
            i += 1
            continue

        if any(line.startswith(lc, i) for lc in lcs):
            toks.append((i, n, "comment"))
            return toks, state

        if blk and line.startswith(blk[0], i):
            end = line.find(blk[1], i + len(blk[0]))
            if end < 0:
                toks.append((i, n, "comment"))
                return toks, "blk"
            toks.append((i, end + len(blk[1]), "comment"))
            i = end + len(blk[1])
            continue

        hit = next((q for q in tri if line.startswith(q, i)), None)
        if hit:
            end = _find_unescaped(line, hit, i + len(hit))
            if end < 0:
                toks.append((i, n, "string"))
                return toks, "tri|" + hit
            toks.append((i, end + len(hit), "string"))
            i = end + len(hit)
            continue

        if ch in quotes:
            end = _scan_string(line, i, ch)
            if end < 0:
                toks.append((i, n, "string"))
                return toks, ""
            tag = "string"
            if keys:
                k = end
                while k < n and line[k] == " ":
                    k += 1
                if k < n and line[k] == ":" and not line.startswith("::", k):
                    tag = "var"
            toks.append((i, end, tag))
            i = end
            continue

        if ch == "$" and i + 1 < n and (line[i + 1].isalnum() or line[i + 1] in "_{"):
            m = re.match(r"[\w{}]+", line[i + 1:])
            if m:
                toks.append((i, i + 1 + m.end(), "var"))
                i = i + 1 + m.end()
                continue

        if ch.isdigit() or (ch == "." and i + 1 < n and line[i + 1].isdigit()):
            m = NUM_RE.match(line, i)
            if m and m.end() > i:
                toks.append((i, m.end(), "number"))
                i = m.end()
                continue

        m = WORD_RE.match(line, i)
        if m:
            w = m.group(0)
            if m.end() < n and line[m.end()] in quotes and w.lower() in STR_PREFIX:
                end = _scan_string(line, m.end(), line[m.end()])
                if end > 0:
                    toks.append((i, end, "string"))
                    i = end
                    continue
            prev = line[i - 1] if i else ""
            tag = "var" if prev == "." else _classify(w, line, m.end(), spec)
            if not tag and kwords:
                k = m.end()
                while k < n and line[k] == " ":
                    k += 1
                if k < n and line[k] == ":":
                    tag = "var"
            if tag:
                toks.append((i, m.end(), tag))
            i = m.end()
            continue

        i += 1
    return toks, state


def _scan_html(line, spec, state):
    toks = []
    i, n = 0, len(line)
    while i < n:
        if state == "cmt":
            end = line.find("-->", i)
            if end < 0:
                toks.append((i, n, "comment"))
                return toks, "cmt"
            toks.append((i, end + 3, "comment"))
            i, state = end + 3, ""
            continue
        if line.startswith("<!--", i):
            end = line.find("-->", i + 4)
            if end < 0:
                toks.append((i, n, "comment"))
                return toks, "cmt"
            toks.append((i, end + 3, "comment"))
            i = end + 3
            continue
        if line[i] != "<":
            i += 1
            continue

        j = i + 1
        if j < n and line[j] == "/":
            j += 1
        m = re.match(r"[A-Za-z][\w:.\-]*", line[j:])
        if not m:
            i += 1
            continue
        toks.append((j, j + m.end(), "tag"))
        k = j + m.end()
        while k < n and line[k] != ">":
            if line[k] in " \t/=":
                k += 1
                continue
            am = ATTR_RE.match(line, k)
            if not am:
                k += 1
                continue
            toks.append((k, am.end(), "var"))
            k = am.end()
            e = k
            while e < n and line[e] in " \t":
                e += 1
            if e < n and line[e] == "=":
                e += 1
                while e < n and line[e] in " \t":
                    e += 1
                if e < n and line[e] in "\"'":
                    end = _scan_string(line, e, line[e])
                    end = n if end < 0 else end
                    toks.append((e, end, "string"))
                    k = end
                    continue
                vm = re.match(r"[^ >]+", line[e:])
                if vm:
                    toks.append((e, e + vm.end(), "string"))
                    k = e + vm.end()
                    continue
            k += 1
        i = k + 1 if k < n else n
    return toks, state


def _scan_css(line, spec, state):
    toks = []
    i, n = 0, len(line)
    while i < n:
        if state == "blk":
            end = line.find("*/", i)
            if end < 0:
                toks.append((i, n, "comment"))
                return toks, "blk"
            toks.append((i, end + 2, "comment"))
            i, state = end + 2, ""
            continue
        if line.startswith("/*", i):
            end = line.find("*/", i + 2)
            if end < 0:
                toks.append((i, n, "comment"))
                return toks, "blk"
            toks.append((i, end + 2, "comment"))
            i = end + 2
            continue
        ch = line[i]
        if ch in "\"'":
            end = _scan_string(line, i, ch)
            if end < 0:
                toks.append((i, n, "string"))
                return toks, ""
            toks.append((i, end, "string"))
            i = end
            continue
        if ch == "#":
            m = re.match(r"#[0-9a-fA-F]{3,8}\b", line[i:])
            if m:
                toks.append((i, i + m.end(), "number"))
                i += m.end()
                continue
        if ch.isdigit():
            m = re.match(r"\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg)?", line[i:])
            if m:
                toks.append((i, i + m.end(), "number"))
                i += m.end()
                continue
        m = re.match(r"[.#&@]?[A-Za-z_\-][\w\-]*", line[i:])
        if m:
            end = i + m.end()
            k = end
            while k < n and line[k] == " ":
                k += 1
            if k < n and line[k] == ":":
                tag = "var"
            elif k < n and line[k] in "{>,":
                tag = "tag"
            elif line[end:end + 1] == "(":
                tag = "func"
            else:
                tag = ""
            if tag:
                toks.append((i, end, tag))
            i = end
            continue
        i += 1
    return toks, state


def scan_line(line, spec, state):
    mode = spec["mode"]
    if mode == "html":
        return _scan_html(line, spec, state)
    if mode == "css":
        return _scan_css(line, spec, state)
    return _scan_generic(line, spec, state)


DETECT = [
    ("python", re.compile(r"^\s*(def |class |import |from \w+ import |@\w+\s*$)", re.M)),
    ("html", re.compile(r"<(!DOCTYPE|html|div|body|head|span|p|script)\b", re.I)),
    ("json", re.compile(r'^\s*\{\s*$|^\s*"[^"]+"\s*:\s*', re.M)),
    ("sql", re.compile(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE)\b", re.I)),
    ("bash", re.compile(r"^#!.*(bash|sh)|^\s*(sudo|apt-get|npm |pip )", re.M)),
    ("cpp", re.compile(r"#include|std::|template\s*<")),
    ("go", re.compile(r"^\s*package \w+|^func \w+\(", re.M)),
    ("rust", re.compile(r"^\s*fn \w+|let mut |impl |use std::", re.M)),
    ("java", re.compile(r"public\s+(static\s+)?(class|void)\s+\w+")),
    ("typescript", re.compile(r"\binterface\s+\w+\s*\{|:\s*(string|number|boolean)\b")),
    ("javascript", re.compile(r"\b(function|const|let|document\.|console\.|=>)\b")),
    ("css", re.compile(r"^\s*[.#@][\w-]+.*\{|^\s*[\w-]+\s*:\s*[^;]+;", re.M)),
    ("yaml", re.compile(r"^[\w-]+:\s|^\s*-\s+\w+", re.M)),
]


def detect_lang(text):
    for name, rx in DETECT:
        if rx.search(text):
            return name
    return "text"


DEMO = '''# CodePin · 置顶代码阅览窗
# Ctrl+V 粘贴 / Ctrl+O 导入文件 / F5 锁定穿透

import asyncio
from dataclasses import dataclass


@dataclass
class Window:
    """一个无边框、可置顶的代码窗口。"""
    title: str = "CodePin"
    alpha: float = 0.96

    async def pin(self, on: bool = True) -> bool:
        await asyncio.sleep(0.01)
        return on

    def describe(self) -> str:
        state = "pinned" if self.alpha > 0.5 else "floating"
        return f"{self.title} -> {state} ({self.alpha:.2f})"


def main() -> None:
    w = Window(alpha=0.9)
    print(w.describe())          # 0x2A -> 42, 3.14, "string"
    for i in range(3):
        print(i, {"key": True, "n": None})

    # 下面这一行刻意超宽，用来验证「内容超出窗口宽度」时的横向滚动
    labels = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota"]

if __name__ == "__main__":
    asyncio.run(main())
'''


class HotkeyThread(threading.Thread):
    """锁定态专用：窗口不可获得焦点时，全局 F5 / Esc 是唯一解锁通道。"""

    def __init__(self, out: "queue.Queue[int]"):
        super().__init__(daemon=True, name="hotkey")
        self.out = out
        self.tid = None
        self.ready = threading.Event()
        self.ok = False

    def run(self):
        self.tid = k32.GetCurrentThreadId()
        ok_f5 = bool(u32.RegisterHotKey(None, 1, MOD_NOREPEAT, VK_F5))
        ok_esc = bool(u32.RegisterHotKey(None, 2, MOD_NOREPEAT, VK_ESCAPE))
        self.ok = ok_f5 or ok_esc
        self.ready.set()
        msg = wt.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.out.put(int(msg.wParam))
        u32.UnregisterHotKey(None, 1)
        u32.UnregisterHotKey(None, 2)

    def stop(self):
        if self.tid:
            u32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


def resource(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(base, rel),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)):
        if os.path.exists(cand):
            return cand
    return ""


class SlimBar(tk.Canvas):
    """极简滚动条：无箭头、无边框，只有一条滑块（可点、可拖）。"""

    def __init__(self, master, orient, command, thickness=10, **kw):
        self.orient = orient
        self.command = command
        self._first, self._last = 0.0, 1.0
        self._drag = None
        if orient == "vertical":
            kw.setdefault("width", thickness)
            kw.setdefault("height", 10)
        else:
            kw.setdefault("width", 10)
            kw.setdefault("height", thickness)
        super().__init__(master, bg=C["bg"], highlightthickness=0, bd=0, **kw)
        self._thumb = self.create_rectangle(0, 0, 0, 0, fill="#3E3E42", width=0)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.bind("<Enter>", lambda e: self.itemconfig(self._thumb, fill="#5A5A5F"))
        self.bind("<Leave>", lambda e: self.itemconfig(self._thumb, fill="#3E3E42"))

    def _total(self):
        return self.winfo_height() if self.orient == "vertical" else self.winfo_width()

    def set(self, first, last):
        f, l = float(first), float(last)
        if (f, l) != (self._first, self._last):
            self._first, self._last = f, l
            self._draw()

    def _draw(self):
        total = self._total()
        if total <= 2:
            return
        a, b = self._first * total, self._last * total
        if b - a < 22:
            a = max(0, min((a + b) / 2 - 11, total - 22))
            b = a + 22
        if self.orient == "vertical":
            self.coords(self._thumb, 1, a, max(2, self.winfo_width() - 2), b)
        else:
            self.coords(self._thumb, a, 1, b, max(2, self.winfo_height() - 2))

    def _press(self, e):
        total = max(1, self._total())
        pos = e.y if self.orient == "vertical" else e.x
        a, b = self._first * total, self._last * total
        if a <= pos <= b:
            self._drag = pos - a
        else:
            self._drag = (b - a) / 2
            self._motion(e)

    def _motion(self, e):
        total = max(1, self._total())
        pos = e.y if self.orient == "vertical" else e.x
        frac = (pos - (self._drag or 0)) / total
        self.command("moveto", str(max(0.0, min(1.0, frac))))


class App:
    def __init__(self):
        self.state = self._load_state()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self._dpi_scaling()

        self.locked = False
        self.topmost = bool(self.state.get("topmost", True))
        self.alpha = float(self.state.get("alpha", 0.96))
        self.lang = self.state.get("lang", "auto")
        self.detected = "python"
        self._hotkeys = None
        self._hk_queue = queue.Queue()
        self._hl_job = None
        self._busy_hl = False
        self._hl_guard = 0.0
        self._last_toggle = 0.0
        self._grips = []
        self._toast_lbl = None
        self._info_full = ""

        icon = resource("assets/icon.ico")
        if icon:
            try:
                self.root.iconbitmap(icon)
            except tk.TclError:
                pass

        self._build_fonts()
        self._build_ui()
        self._apply_geometry()
        self._bind_events()

        self.root.overrideredirect(True)
        self.root.deiconify()
        self.root.update_idletasks()
        self._apply_win32()

        self.set_text(DEMO, name="demo.py")
        self.root.after(120, self._focus_code)
        self.root.after(60, self._poll_hotkeys)

    # ------------------------------------------------------------ 基础
    def _dpi_scaling(self):
        try:
            dpi = u32.GetDpiForSystem()
        except Exception:
            dpi = 96
        self.dpi = max(96, dpi)
        self.scale = self.dpi / 96.0
        self.root.tk.call("tk", "scaling", self.dpi / 72.0)

    def _build_fonts(self):
        fams = set(tkfont.families(self.root))
        self.mono_family = next((f for f in MONO_CANDIDATES if f in fams), "Courier New")
        self.f_mono = tkfont.Font(family=self.mono_family, size=11)
        self.f_ui = tkfont.Font(family=GUI_FONT, size=9)
        self.f_title = tkfont.Font(family=GUI_FONT, size=9, weight="bold")
        self.line_pad = max(1, int(self.f_mono.metrics("linespace") * 0.08))

    def _load_state(self):
        p = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME, "state.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        try:
            d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
            os.makedirs(d, exist_ok=True)
            geo = self.root.geometry()
            size, *pos = geo.split("+")
            w, h = (int(v) for v in size.split("x"))
            x, y = (int(v) for v in pos[:2])
            data = {"w": w, "h": h, "x": x, "y": y, "alpha": round(self.alpha, 3),
                    "lang": self.lang, "topmost": self.topmost}
            with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _apply_geometry(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = int(self.state.get("w", 760 * self.scale))
        h = int(self.state.get("h", 620 * self.scale))
        x = int(self.state.get("x", sw - w - 60))
        y = int(self.state.get("y", 110))
        x = max(0, min(x, sw - 160))
        y = max(0, min(y, sh - 120))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ------------------------------------------------------------ 界面
    def _build_ui(self):
        self.root.configure(bg=C["border"])
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.shell = tk.Frame(self.root, bg=C["border"])
        self.shell.grid(row=0, column=0, sticky="nsew")
        self.inner = tk.Frame(self.shell, bg=C["bg"])
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.inner.grid_rowconfigure(1, weight=1)
        self.inner.grid_columnconfigure(0, weight=1)

        self._build_titlebar()
        self._build_body()
        self._build_status()
        self._create_grips()

    def _build_titlebar(self):
        self.titlebar = tk.Frame(self.inner, bg=C["titlebar"], height=int(34 * self.scale))
        self.titlebar.grid(row=0, column=0, sticky="ew")
        self.titlebar.grid_propagate(False)

        right = tk.Frame(self.titlebar, bg=C["titlebar"])
        right.pack(side="right", fill="y", padx=(0, 6))

        self.btn_close = self._title_btn(right, "✕", self.close, hover="#C42B1C", width=3)
        self.btn_close.pack(side="right", fill="y")
        self.btn_lang = self._title_btn(right, "自动", self._open_lang_menu)
        self.btn_lang.pack(side="right", fill="y")
        self.btn_import = self._title_btn(right, "导入", self.import_file)
        self.btn_import.pack(side="right", fill="y")
        self.btn_lock = self._title_btn(right, "锁定", self.toggle_lock)
        self.btn_lock.pack(side="right", fill="y")
        self.btn_pin = self._title_btn(right, "置顶", self.toggle_topmost)
        self.btn_pin.pack(side="right", fill="y")

        self.dragarea = tk.Frame(self.titlebar, bg=C["titlebar"])
        self.dragarea.pack(side="left", fill="both", expand=True)

        self.icon_img = None
        p32 = resource("assets/icon32.png")
        if p32:
            try:
                self.icon_img = tk.PhotoImage(file=p32)
            except tk.TclError:
                self.icon_img = None
        if self.icon_img:
            ico = tk.Label(self.dragarea, image=self.icon_img, bg=C["titlebar"], bd=0)
        else:
            ico = tk.Label(self.dragarea, text="◆", bg=C["titlebar"], fg=C["accent"],
                           font=self.f_ui, bd=0)
        ico.pack(side="left", padx=(10, 7))

        self.lbl_title = tk.Label(self.dragarea, text="未命名", bg=C["titlebar"],
                                  fg="#CCCCCC", font=self.f_title, bd=0)
        self.lbl_title.pack(side="left")
        self.lbl_meta = tk.Label(self.dragarea, text="", bg=C["titlebar"], fg=C["dim"],
                                 font=self.f_ui, bd=0)
        self.lbl_meta.pack(side="left", padx=(8, 0))

        for wdg in (self.dragarea, ico, self.lbl_title, self.lbl_meta):
            wdg.bind("<Button-1>", self._drag_start)
            wdg.bind("<B1-Motion>", self._drag_move)

    def _title_btn(self, parent, text, cmd, hover=None, width=5):
        b = tk.Label(parent, text=text, bg=C["titlebar"], fg="#BBBBBB", font=self.f_ui,
                     width=width, cursor="hand2", bd=0)
        b._fg = "#BBBBBB"
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=hover or C["hover"], fg="#FFFFFF"))
        b.bind("<Leave>", lambda e: b.config(bg=C["titlebar"], fg=b._fg))
        return b

    def _build_body(self):
        self.body = tk.Frame(self.inner, bg=C["bg"])
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(1, weight=1)
        self.body.grid_columnconfigure(0, minsize=44)

        common = dict(bd=0, highlightthickness=0, wrap="none", font=self.f_mono,
                      spacing1=self.line_pad, spacing3=self.line_pad, height=1)
        self.gutter = tk.Text(self.body, width=3, padx=int(8 * self.scale), pady=int(10 * self.scale),
                              bg=C["bg"], fg=C["dim"],
                              takefocus=0, cursor="arrow", state="disabled", **common)
        self.gutter.grid(row=0, column=0, sticky="ns")

        self.code = tk.Text(self.body, padx=int(10 * self.scale), pady=int(10 * self.scale),
                            bg=C["bg"], fg=C["fg"],
                            insertbackground="#AEAFAD", insertwidth=2, width=1,
                            selectbackground=C["sel"], selectforeground="#FFFFFF",
                            undo=True, maxundo=300, spacing1=self.line_pad,
                            spacing3=self.line_pad, wrap="none", bd=0, highlightthickness=0,
                            font=self.f_mono, tabs=(self.f_mono.measure(" ") * 4,), height=1)
        self.code.grid(row=0, column=1, sticky="nsew")

        self.vbar = SlimBar(self.body, "vertical", self._yview)
        self.vbar.grid(row=0, column=2, sticky="ns")
        self.hbar = SlimBar(self.body, "horizontal", self.code.xview)
        self.hbar.grid(row=1, column=0, columnspan=3, sticky="ew")

        self.code.configure(yscrollcommand=self._on_yscroll, xscrollcommand=self._on_xscroll)
        for tag, color in TAG_COLORS.items():
            self.code.tag_configure(tag, foreground=color)

        self.hint = tk.Label(self.body, bg=C["bg"], fg="#5A5A5A", font=self.f_ui, justify="center",
                             text="粘贴代码（Ctrl+V）或点击「导入」\n"
                                  "Ctrl+A 全选后粘贴可整体替换 · Shift+滚轮 横向滚动")
        self.hint.place(relx=0.5, rely=0.45, anchor="center")

    def _build_status(self):
        self.status = tk.Frame(self.inner, bg=C["titlebar"], height=int(25 * self.scale))
        self.status.grid(row=2, column=0, sticky="ew")
        self.status.pack_propagate(False)
        self.lbl_tip = tk.Label(self.status, text="F5 锁定穿透 · Ctrl+滚轮 透明度",
                                bg=C["titlebar"], fg="#5F5F5F", font=self.f_ui)
        self.lbl_tip.pack(side="right", padx=10)
        self.lbl_pos = tk.Label(self.status, text="行 1，列 1", bg=C["titlebar"],
                                fg=C["dim"], font=self.f_ui)
        self.lbl_pos.pack(side="left", padx=(10, 0))
        self.lbl_info = tk.Label(self.status, text="", bg=C["titlebar"], fg=C["dim"], font=self.f_ui)
        self.lbl_info.pack(side="left", padx=(12, 0))
        self.status.bind("<Configure>", self._layout_status)

    def _layout_status(self, e=None):
        w = self.status.winfo_width()
        if w <= 1:
            return
        tip = ("F5 锁定穿透 · Ctrl+滚轮 透明度" if w > 560
               else "F5 锁定" if w > 420 else "")
        if self.lbl_tip.cget("text") != tip:
            self.lbl_tip.config(text=tip)
            if tip:
                self.lbl_tip.pack(side="right", padx=10)
        info = self._info_full if w > 330 else ""
        if self.lbl_info.cget("text") != info:
            self.lbl_info.config(text=info)

    def _create_grips(self):
        curs = {"w": "sb_h_double_arrow", "e": "sb_h_double_arrow",
                "s": "sb_v_double_arrow", "se": "size_nw_se"}
        layout = {"w": dict(x=0, y=6, relheight=1, height=-12, width=5),
                  "e": dict(relx=1, x=-5, y=6, relheight=1, height=-12, width=5),
                  "s": dict(rely=1, y=-5, relwidth=1, height=5),
                  "se": dict(relx=1, rely=1, x=-13, y=-13, width=13, height=13)}
        for edge, kw in layout.items():
            g = tk.Frame(self.root, bg=C["border"], cursor=curs[edge])
            g.place(**kw)
            g.bind("<Button-1>", lambda e, ed=edge: self._resize_start(e, ed))
            g.bind("<B1-Motion>", self._resize_move)
            self._grips.append((g, kw))

    def _show_grips(self, on):
        for g, kw in self._grips:
            if on:
                g.place(**kw)
            else:
                g.place_forget()

    # ------------------------------------------------------------ Win32
    def _hwnd(self):
        return u32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()

    def _apply_win32(self):
        hwnd = self._hwnd()
        style = u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        u32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_APPLY)
        self.root.attributes("-topmost", self.topmost)
        self.root.attributes("-alpha", self.alpha)
        self._sync_chrome()

    def _set_click_through(self, on: bool):
        hwnd = self._hwnd()
        style = u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if on:
            style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
        else:
            style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        u32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        u32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_APPLY)

    # ------------------------------------------------------------ 事件
    def _bind_events(self):
        r = self.root
        r.bind("<F5>", lambda e: self.toggle_lock())
        r.bind("<Control-o>", lambda e: self.import_file())
        r.bind("<Control-q>", lambda e: self.close())
        r.protocol("WM_DELETE_WINDOW", self.close)

        for w in (self.code, self.gutter):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Shift-MouseWheel>", self._on_wheel)
            w.bind("<Control-MouseWheel>", self._on_wheel)
            w.bind("<Button-4>", self._on_wheel)
            w.bind("<Button-5>", self._on_wheel)

        self.code.bind("<Left>", lambda e: self._hscroll(-3))
        self.code.bind("<Right>", lambda e: self._hscroll(3))
        self.code.bind("<Control-Left>", lambda e: self._hscroll(-12))
        self.code.bind("<Control-Right>", lambda e: self._hscroll(12))
        self.code.bind("<Control-a>", self._select_all)
        self.code.bind("<Control-Shift-C>", self._copy_all)
        self.code.bind("<<Modified>>", self._on_modified)
        self.code.bind("<KeyRelease>", self._on_caret)
        self.code.bind("<ButtonRelease-1>", self._on_caret)
        self.gutter.bind("<Button-1>", lambda e: self.code.focus_set())

    def _focus_code(self):
        try:
            self.root.focus_force()
            self.code.focus_set()
        except tk.TclError:
            pass

    def _select_all(self, e=None):
        self.code.tag_add("sel", "1.0", "end-1c")
        self.code.mark_set("insert", "1.0")
        return "break"

    def _copy_all(self, e=None):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.code.get("1.0", "end-1c"))
        self._toast("已复制全文", 900)
        return "break"

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        dx, dy = getattr(self, "_drag", (0, 0))
        self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _resize_start(self, e, edge):
        self._rs = (edge, e.x_root, e.y_root, self.root.winfo_width(),
                    self.root.winfo_height(), self.root.winfo_x(), self.root.winfo_y())

    def _resize_move(self, e):
        if not hasattr(self, "_rs"):
            return
        edge, sx, sy, w, h, x, y = self._rs
        dx, dy = e.x_root - sx, e.y_root - sy
        nw = max(int(340 * self.scale), w + dx) if "e" in edge else w
        nh = max(int(200 * self.scale), h + dy) if "s" in edge else h
        self.root.geometry(f"{nw}x{nh}+{x}+{y}")

    def _on_wheel(self, e):
        delta = getattr(e, "delta", 0) or 0
        num = getattr(e, "num", 0)
        if num == 4:
            delta = 120
        elif num == 5:
            delta = -120
        if not delta:
            return "break"
        step = -1 if delta > 0 else 1
        if e.state & 0x0004:
            self._change_alpha(0.04 * -step)
        elif e.state & 0x0001:
            self.code.xview_scroll(step * 4, "units")
        else:
            self.code.yview_scroll(step * 3, "units")
            self._sync_gutter()
        return "break"

    def _hscroll(self, n):
        self.code.xview_scroll(n, "units")
        return "break"

    def _yview(self, *args):
        self.code.yview(*args)
        self._sync_gutter()

    def _on_yscroll(self, first, last):
        self.vbar.set(first, last)
        self.gutter.yview_moveto(first)

    def _on_xscroll(self, first, last):
        self.hbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.hbar.grid_remove()
        else:
            self.hbar.grid()

    def _sync_gutter(self):
        self.gutter.yview_moveto(self.code.yview()[0])

    def _on_caret(self, e=None):
        try:
            ln, col = self.code.index("insert").split(".")
        except (tk.TclError, ValueError):
            return
        self.lbl_pos.config(text=f"行 {ln}，列 {int(col) + 1}")

    def _change_alpha(self, d):
        self.alpha = round(min(1.0, max(0.25, self.alpha + d)), 2)
        self.root.attributes("-alpha", self.alpha)
        self._toast(f"不透明度 {int(self.alpha * 100)}%", 700)

    # ------------------------------------------------------------ 功能
    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self._sync_chrome()
        self._toast("已置顶" if self.topmost else "取消置顶", 800)

    def _sync_chrome(self):
        self.btn_pin.config(fg=C["accent"] if self.topmost else "#BBBBBB")
        self.btn_pin._fg = C["accent"] if self.topmost else "#BBBBBB"
        self.btn_lang.config(text="自动" if self.lang == "auto" else SHORT.get(self.lang, "Text"))
        self.lbl_meta.config(text=f"· {LANGS[self.detected]['label']}")

    def toggle_lock(self):
        now = time.time()
        if now - self._last_toggle < 0.35:
            return
        self._last_toggle = now
        self.set_locked(not self.locked)

    def set_locked(self, on: bool):
        if on == self.locked:
            return
        if on:
            hk = HotkeyThread(self._hk_queue)
            hk.start()
            hk.ready.wait(0.6)
            if not hk.ok:
                hk.stop()
                self._toast("全局热键被占用（F5/Esc），已取消锁定", 2000)
                return
            self.locked = True
            self._hotkeys = hk
            self.titlebar.grid_remove()
            self.status.grid_remove()
            self.vbar.grid_remove()
            self.hbar.grid_remove()
            self._show_grips(False)
            self.shell.config(bg=C["accent"])
            self.code.config(insertbackground=C["bg"])
            self._set_click_through(True)
            self._toast("已锁定 · 点击穿透 · 按 F5 解锁", 2200)
        else:
            self.locked = False
            self._stop_hotkeys()
            self._set_click_through(False)
            self.shell.config(bg=C["border"])
            self.code.config(insertbackground="#AEAFAD")
            self.titlebar.grid()
            self.status.grid()
            self.vbar.grid()
            self._show_grips(True)
            self._on_xscroll(*self.code.xview())
            self.root.attributes("-topmost", self.topmost)
            self.root.attributes("-alpha", self.alpha)
            self._focus_code()
            self._last_toggle = time.time()

    def _stop_hotkeys(self):
        if self._hotkeys:
            self._hotkeys.stop()
            self._hotkeys = None
        while not self._hk_queue.empty():
            self._hk_queue.get_nowait()

    def _poll_hotkeys(self):
        try:
            while True:
                self._hk_queue.get_nowait()
                if self.locked:
                    self.set_locked(False)
        except queue.Empty:
            pass
        self.root.after(60, self._poll_hotkeys)

    def _open_lang_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=C["titlebar"], fg="#CCCCCC",
                    activebackground=C["accent"], activeforeground="#FFFFFF", bd=0, font=self.f_ui)
        m.add_command(label="自动识别", command=lambda: self.set_lang("auto"))
        m.add_separator()
        for key in ("python", "javascript", "typescript", "cpp", "java", "csharp", "go",
                    "rust", "json", "html", "css", "sql", "bash", "yaml", "text"):
            m.add_command(label=LANGS[key]["label"], command=lambda k=key: self.set_lang(k))
        x = self.btn_lang.winfo_rootx() - 60
        y = self.btn_lang.winfo_rooty() + self.btn_lang.winfo_height()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def set_lang(self, key):
        self.lang = key
        self._sync_chrome()
        self.highlight()

    def import_file(self):
        # 置顶窗口会盖住模态对话框：先取消置顶，并把本窗口提到前台
        self.root.attributes("-topmost", False)
        try:
            u32.SetForegroundWindow(self._hwnd())
        except Exception:
            pass
        path = ""
        try:
            path = filedialog.askopenfilename(
                parent=self.root,
                title="导入代码文件",
                filetypes=[("代码文件", "*.py *.js *.ts *.tsx *.jsx *.java *.c *.h *.cpp *.hpp *.cs "
                                      "*.go *.rs *.json *.html *.css *.sql *.sh *.yml *.yaml *.txt"),
                           ("所有文件", "*.*")])
        finally:
            self.root.attributes("-topmost", self.topmost)
        if not path:
            return
        data = None
        for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    data = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if data is None:
            self._toast("无法读取该文件", 1500)
            return
        ext = os.path.splitext(path)[1].lower()
        self.set_text(data, name=os.path.basename(path), ext=ext)
        self._toast(f"已导入 {os.path.basename(path)}", 1200)

    def set_text(self, text, name="未命名", ext=None):
        self.code.delete("1.0", "end")
        self.code.insert("1.0", text)
        self.code.edit_reset()
        self.code.edit_modified(False)
        self.code.mark_set("insert", "1.0")
        self.code.yview_moveto(0)
        self.code.xview_moveto(0)
        self.lbl_title.config(text=name)
        if ext and ext in EXT_MAP:
            self.detected = EXT_MAP[ext]
        elif self.lang == "auto":
            self.detected = detect_lang(text)
        self._sync_chrome()
        self.highlight()
        self.root.after(0, lambda: self._on_xscroll(*self.code.xview()))

    # ------------------------------------------------------------ 高亮
    def _on_modified(self, _=None):
        changed = self.code.edit_modified()
        self.code.edit_modified(False)
        if not changed:
            return
        if self._busy_hl or time.time() < self._hl_guard:
            return
        if self.lang == "auto":
            self.detected = detect_lang(self.code.get("1.0", "end-1c"))
            self._sync_chrome()
        self.schedule_highlight(180)

    def schedule_highlight(self, delay=180):
        if self._hl_job:
            try:
                self.root.after_cancel(self._hl_job)
            except tk.TclError:
                pass
        self._hl_job = self.root.after(delay, self.highlight)

    def highlight(self):
        self._hl_job = None
        self._busy_hl = True
        try:
            text = self.code.get("1.0", "end-1c")
            if text:
                self.hint.place_forget()
            else:
                self.hint.place(relx=0.5, rely=0.45, anchor="center")
            lines = text.split("\n") if text else []
            self._update_gutter(len(lines))
            self._info_full = f"{len(lines)} 行 · {len(text)} 字符"
            self._layout_status()

            for tag in TAG_COLORS:
                self.code.tag_remove(tag, "1.0", "end")
            if len(text) > 300_000:
                self._info_full = f"{len(lines)} 行 · 内容过大，已关闭高亮"
                self._layout_status()
                return
            key = self.detected if self.lang == "auto" else self.lang
            spec = LANGS.get(key, LANGS["text"])
            state = ""
            for ln, line in enumerate(lines, 1):
                if not line:
                    continue
                toks, state = scan_line(line, spec, state)
                for s, e, tag in toks:
                    if e > s:
                        self.code.tag_add(tag, f"{ln}.{s}", f"{ln}.{e}")
            self._sync_gutter()
        finally:
            self._busy_hl = False
            self._hl_guard = time.time() + 0.15
            self.code.edit_modified(False)

    def _update_gutter(self, n):
        digits = max(3, len(str(max(n, 1))) + 1)
        if int(self.gutter.cget("width")) != digits:
            self.gutter.config(width=digits)
        self.gutter.config(state="normal")
        self.gutter.delete("1.0", "end")
        if n:
            self.gutter.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        self.gutter.config(state="disabled")
        self.gutter.yview_moveto(self.code.yview()[0])

    # ------------------------------------------------------------ 其他
    def _toast(self, msg, ms=1400):
        if self._toast_lbl is not None:
            try:
                self._toast_lbl.destroy()
            except tk.TclError:
                pass
        lbl = tk.Label(self.root, text=msg, bg=C["accent"], fg="#FFFFFF", font=self.f_ui,
                       padx=14, pady=6, bd=0)
        lbl.place(relx=0.5, rely=0.94, anchor="s")
        lbl.lift()
        self._toast_lbl = lbl

        def kill():
            try:
                lbl.destroy()
            except tk.TclError:
                pass
            if self._toast_lbl is lbl:
                self._toast_lbl = None

        self.root.after(ms, kill)

    def close(self):
        self._save_state()
        self._stop_hotkeys()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 必须在 Tk 建窗之前
    except Exception:
        pass
    App().run()


if __name__ == "__main__":
    main()
