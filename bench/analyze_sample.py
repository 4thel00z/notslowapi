"""Summarize sample(1) output per rung: where main-thread samples land, by library."""

import re
import sys
from collections import Counter
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"

IDLE = {"__psynch_cvwait", "__semwait_signal", "__workq_kernreturn", "__ulock_wait", "start_wqthread"}

CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("kernel", re.compile(r"libsystem_kernel")),
    ("malloc", re.compile(r"libsystem_malloc|_PyObject_(Malloc|Free|Realloc)|_PyObject_GC|PyObject_GC_Del|PyType_GenericAlloc|_PyMem")),
    ("dealloc", re.compile(r"dealloc|_PyFrame_Clear|__bzero|_platform_mem")),
    ("regex", re.compile(r"\bsre_|_sre")),
    ("uvloop", re.compile(r"uvloop|libuv|loop\.cpython")),
    ("httptools", re.compile(r"llhttp|parser\.cpython|httptools")),
    ("pydantic_core", re.compile(r"pydantic_core|_pydantic_core")),
    ("libc/dyld", re.compile(r"libdyld|libsystem_platform|libsystem_c|libc\+\+")),
    ("interpreter", re.compile(r"in python3")),
]


def categorize(frame: str) -> str:
    for name, pattern in CATEGORIES:
        if pattern.search(frame):
            return name
    return "other"


def top_of_stack(text: str) -> Counter[str]:
    start = text.index("Sort by top of stack")
    end = text.index("Binary Images", start)
    counts: Counter[str] = Counter()
    for line in text[start:end].splitlines()[1:]:
        match = re.match(r"\s+(\S.*?)\s+(\d+)\s*$", line)
        if not match:
            continue
        symbol, count = match.group(1), int(match.group(2))
        if symbol.split()[0] in IDLE:
            continue
        counts[categorize(symbol)] += count
    return counts


def top_symbols(text: str, limit: int) -> list[tuple[str, int]]:
    start = text.index("Sort by top of stack")
    end = text.index("Binary Images", start)
    rows: list[tuple[str, int]] = []
    for line in text[start:end].splitlines()[1:]:
        match = re.match(r"\s+(\S.*?)\s+(\d+)\s*$", line)
        if not match:
            continue
        if match.group(1).split()[0] in IDLE:
            continue
        rows.append((match.group(1), int(match.group(2))))
    return rows[:limit]


def main() -> None:
    files = sorted(OUT_DIR.glob("sample_*.txt"))
    names = [f.stem.removeprefix("sample_") for f in files]
    tables = [top_of_stack(f.read_text(errors="replace")) for f in files]
    cats = [c for c, _ in CATEGORIES] + ["other"]
    width = max(len(n) for n in names) + 2
    print(f"{'category':14}" + "".join(f"{n:>{width}}" for n in names))
    for cat in cats:
        print(f"{cat:14}" + "".join(f"{t[cat] / max(sum(t.values()), 1):{width}.1%}" for t in tables))
    print(f"{'samples':14}" + "".join(f"{sum(t.values()):{width}d}" for t in tables))
    if len(sys.argv) < 2:
        return
    for f, name in zip(files, names):
        print(f"\n== {name}: top symbols ==")
        for symbol, count in top_symbols(f.read_text(errors="replace"), int(sys.argv[1])):
            print(f"{count:7d}  {symbol}")


if __name__ == "__main__":
    main()
