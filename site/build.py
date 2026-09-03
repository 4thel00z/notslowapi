"""Assemble notslowapi.com into out/: landing page, generated benchmarks page, MkDocs docs."""

import json
import re
import shutil
import statistics
import subprocess
import sys
from html import escape
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
OUT = ROOT / "out"
BASELINE = ROOT / "bench" / "baseline"

RUNG_LABELS = {
    "l0_raw": "raw ASGI app",
    "l1_starlette": "Starlette route",
    "l1b_starlette_params": "Starlette, int path + str query",
    "l1c_starlette_50routes": "Starlette, 50 routes",
    "l2_fastapi_dict": "notslowapi, typed dict return",
    "l2b_fastapi_untyped": "notslowapi, untyped dict return",
    "l2c_fastapi_included": "notslowapi, route via include_router",
    "l3_fastapi_params": "notslowapi, int path + str query",
    "l4_fastapi_model": "notslowapi, pydantic body + response_model",
    "l5_fastapi_50routes": "notslowapi, 50 routes",
    "l5b_fastapi_50routes_included": "notslowapi, 50 routes via include_router",
}


def load_rows(name: str) -> list[dict]:
    return json.loads((BASELINE / name).read_text())


def split_server(rung: str) -> tuple[str, str]:
    base, _, tag = rung.partition("[")
    if "granian" in tag:
        return base, "granian"
    if "asyncio" in tag:
        return base, "uvicorn asyncio+h11"
    return base, "uvicorn"


LADDER_COLUMNS = ("FastAPI 0.141 day one, uvicorn", "notslowapi, uvicorn", "notslowapi, granian")


def highlight_class(column: str) -> str:
    if column != LADDER_COLUMNS[-1]:
        return ""
    return ' class="is-hi"'


def ladder_cell(row: dict | None, column: str) -> str:
    attrs = f' data-col="{escape(column)}"{highlight_class(column)}'
    if not row:
        return f'<td{attrs}><span class="cell"><span class="is-na">not measured</span></span></td>'
    val = f"{row['us_per_request']:.1f} µs"
    sub = f"{statistics.median(row['rps']):,.0f} req/s"
    return f'<td{attrs}><span class="cell"><span class="val">{val}</span><span class="sub">{sub}</span></span></td>'


def ladder_table(day_one: list[dict], current: list[dict]) -> str:
    first = {r["rung"]: r for r in day_one}
    by_base: dict[str, dict[str, dict]] = {}
    for row in current:
        base, server = split_server(row["rung"])
        by_base.setdefault(base, {})[server] = row
    head_cells = "".join(
        f'<th scope="col"{highlight_class(c)}>{escape(c)}</th>' for c in LADDER_COLUMNS
    )
    head = f'<tr><th scope="col">Route</th>{head_cells}</tr>'
    body = []
    for base, servers in by_base.items():
        if base not in RUNG_LABELS:
            continue
        rows = (first.get(base), servers.get("uvicorn"), servers.get("granian"))
        cells = "".join(ladder_cell(r, c) for r, c in zip(rows, LADDER_COLUMNS))
        body.append(f'<tr><th scope="row">{escape(RUNG_LABELS[base])}</th>{cells}</tr>')
    return f'<table class="bench"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def delta_class(change: float) -> str:
    if change < -0.005:
        return " is-down"
    if change > 0.005:
        return " is-up"
    return ""


def fix_number(path: Path) -> tuple[int, str]:
    digits = re.search(r"fix(\d+)", path.name)
    return (int(digits.group(1)) if digits else 0, path.name)


def fixes_table() -> str:
    pairs = sorted(BASELINE.glob("results_fix*_before.json"), key=fix_number)
    rows = []
    for before_path in pairs:
        after_path = before_path.with_name(before_path.name.replace("_before", "_after"))
        if not after_path.exists():
            continue
        before = {r["rung"]: r for r in json.loads(before_path.read_text())}
        after = {r["rung"]: r for r in json.loads(after_path.read_text())}
        label = before_path.stem.replace("results_", "").replace("_before", "")
        for rung, b in before.items():
            a = after.get(rung)
            if not a:
                continue
            change = (a["us_per_request"] - b["us_per_request"]) / b["us_per_request"]
            rows.append(
                f'<tr><td class="change">{escape(label)}</td><td class="rung">{escape(rung)}</td>'
                f'<td class="is-num" data-col="before µs">{b["us_per_request"]:.1f}</td>'
                f'<td class="is-num" data-col="after µs">{a["us_per_request"]:.1f}</td>'
                f'<td class="is-num{delta_class(change)}" data-col="delta">{change:+.0%}</td></tr>'
            )
    head = '<tr><th scope="col">change</th><th scope="col">rung</th><th scope="col" class="is-num">before µs</th><th scope="col" class="is-num">after µs</th><th scope="col" class="is-num">delta</th></tr>'
    return f'<table class="fixes"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def render_benchmarks(template: str) -> str:
    day_one = load_rows("results_ladder_v1.json")
    current = load_rows("results_ladder_v3.json")
    return template.replace("{{LADDER_TABLE}}", ladder_table(day_one, current)).replace(
        "{{FIXES_TABLE}}", fixes_table()
    )


def main() -> None:
    landing = SITE / "landing" / "index.html"
    if not landing.exists():
        raise SystemExit("site/landing/index.html is missing: copy the chosen mockup there")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copy(landing, OUT / "index.html")
    assets = SITE / "landing" / "assets"
    if assets.exists():
        shutil.copytree(assets, OUT / "assets")
    (OUT / "benchmarks").mkdir()
    template = (SITE / "benchmarks.html").read_text()
    (OUT / "benchmarks" / "index.html").write_text(render_benchmarks(template))
    (OUT / "404.html").write_text((SITE / "404.html").read_text())
    subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "-f",
            str(SITE / "mkdocs.yml"),
            "-d",
            str(OUT / "docs"),
        ],
        check=True,
    )
    print("built", OUT)


if __name__ == "__main__":
    main()
