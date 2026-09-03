"""Assemble notslowapi.com into out/: landing page, generated benchmarks page, MkDocs docs."""

import json
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


def ladder_table(day_one: list[dict], current: list[dict]) -> str:
    first = {r["rung"]: r for r in day_one}
    by_base: dict[str, dict[str, dict]] = {}
    for row in current:
        base, server = split_server(row["rung"])
        by_base.setdefault(base, {})[server] = row
    head = "<tr><th>route</th><th>FastAPI 0.141 day one, uvicorn</th><th>notslowapi, uvicorn</th><th>notslowapi, granian</th></tr>"
    body = []
    for base, servers in by_base.items():
        if base not in RUNG_LABELS:
            continue
        uv = servers.get("uvicorn")
        gr = servers.get("granian")
        d1 = first.get(base)
        cells = [
            escape(RUNG_LABELS[base]),
            f"{d1['us_per_request']:.1f} µs" if d1 else "",
            f"{uv['us_per_request']:.1f} µs, {statistics.median(uv['rps']):,.0f} req/s" if uv else "",
            f"{gr['us_per_request']:.1f} µs, {statistics.median(gr['rps']):,.0f} req/s" if gr else "",
        ]
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<table>{head}{''.join(body)}</table>"


def fixes_table() -> str:
    pairs = sorted(BASELINE.glob("results_fix*_before.json"))
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
            rows.append(f"<tr><td>{escape(label)}</td><td>{escape(rung)}</td><td>{b['us_per_request']:.1f}</td><td>{a['us_per_request']:.1f}</td><td>{change:+.0%}</td></tr>")
    head = "<tr><th>change</th><th>rung</th><th>before µs</th><th>after µs</th><th>delta</th></tr>"
    return f"<table>{head}{''.join(rows)}</table>"


def render_benchmarks(template: str) -> str:
    day_one = load_rows("results_ladder_v1.json")
    current = load_rows("results_ladder_v3.json")
    return template.replace("{{LADDER_TABLE}}", ladder_table(day_one, current)).replace("{{FIXES_TABLE}}", fixes_table())


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
    subprocess.run([sys.executable, "-m", "mkdocs", "build", "-f", str(SITE / "mkdocs.yml"), "-d", str(OUT / "docs")], check=True)
    print("built", OUT)


if __name__ == "__main__":
    main()
