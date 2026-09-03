"""Render the µs-per-request chart from bench/baseline into site/landing/assets."""

import json
import statistics
from dataclasses import dataclass
from html import escape
from pathlib import Path

SITE = Path(__file__).resolve().parent
BASELINE = SITE.parent / "bench" / "baseline"
ASSETS = SITE / "landing" / "assets"

ROUTES = [
    ("l0_raw", "raw ASGI app"),
    ("l2_fastapi_dict", "plain JSON route"),
    ("l3_fastapi_params", "int path + str query"),
    ("l4_fastapi_model", "pydantic body + response_model"),
    ("l5b_fastapi_50routes_included", "50 routes via include_router *"),
]
SERIES = ["FastAPI 0.141.1, uvicorn", "notslowapi, uvicorn", "notslowapi, granian"]

WIDTH = 760
LABEL_WIDTH = 236
RIGHT_PAD = 132
BAR = 12
GAP = 3
GROUP_GAP = 18
TOP = 58
FONT = "Instrument Sans, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"
MONO = "SF Mono, Menlo, Consolas, monospace"


@dataclass(frozen=True)
class Palette:
    ink: str
    muted: str
    line: str
    background: str
    day_one: str
    uvicorn: str
    granian: str


LIGHT = Palette(
    ink="#0e0e0d",
    muted="#5c5c57",
    line="#e4e4df",
    background="#fbfbf9",
    day_one="#a3a39c",
    uvicorn="#0e0e0d",
    granian="#18bed4",
)
DARK = Palette(
    ink="#ffffff",
    muted="#a6a6a0",
    line="rgba(255,255,255,.14)",
    background="#0d0d0d",
    day_one="#5c5c57",
    uvicorn="#ffffff",
    granian="#18bed4",
)


def rows(name: str) -> dict[str, dict]:
    return {r["rung"]: r for r in json.loads((BASELINE / name).read_text())}


def microseconds(row: dict | None) -> float | None:
    if not row:
        return None
    return row["us_per_request"]


def requests_per_second(row: dict | None) -> str:
    if not row:
        return ""
    return f"{statistics.median(row['rps']):,.0f} req/s"


def load_values() -> list[tuple[str, list[float | None], list[str]]]:
    day_one = rows("results_ladder_v1.json")
    now = rows("results_ladder_v4.json")
    fix11 = rows("results_fix11_before.json")
    result = []
    for rung, label in ROUTES:
        first = day_one.get(rung) or fix11.get(rung)
        uvicorn = now.get(rung)
        granian = now.get(f"{rung}[granian]")
        values = [microseconds(first), microseconds(uvicorn), microseconds(granian)]
        notes = [
            requests_per_second(first),
            requests_per_second(uvicorn),
            requests_per_second(granian),
        ]
        result.append((label, values, notes))
    return result


def render(palette: Palette) -> str:
    data = load_values()
    colors = [palette.day_one, palette.uvicorn, palette.granian]
    plot_width = WIDTH - LABEL_WIDTH - RIGHT_PAD
    scale = plot_width / 100.0
    group_height = 3 * BAR + 2 * GAP
    height = TOP + len(data) * (group_height + GROUP_GAP) + 40
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" '
        f'font-family="{FONT}" font-size="13" role="img" aria-label="Microseconds per request by route">',
        f'<rect width="{WIDTH}" height="{height}" fill="{palette.background}" rx="16"/>',
        f'<text x="24" y="30" font-size="15" font-weight="600" fill="{palette.ink}">µs per request, one core, lower is better</text>',
    ]
    legend_x = 24
    for name, color in zip(SERIES, colors):
        parts.append(f'<rect x="{legend_x}" y="41" width="10" height="10" rx="2" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 15}" y="50" fill="{palette.muted}" font-size="12">{escape(name)}</text>'
        )
        legend_x += 15 + 7 * len(name) + 22
    for tick in (0, 25, 50, 75, 100):
        x = LABEL_WIDTH + tick * scale
        parts.append(
            f'<line x1="{x:.1f}" y1="{TOP}" x2="{x:.1f}" y2="{height - 34}" stroke="{palette.line}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{height - 18}" text-anchor="middle" fill="{palette.muted}" font-size="11" font-family="{MONO}">{tick}</text>'
        )
    y = TOP + 8
    for label, values, notes in data:
        parts.append(
            f'<text x="{LABEL_WIDTH - 12}" y="{y + group_height / 2 + 4:.1f}" text-anchor="end" fill="{palette.ink}">{escape(label)}</text>'
        )
        for value, note, color in zip(values, notes, colors):
            if value is None:
                parts.append(
                    f'<text x="{LABEL_WIDTH + 6}" y="{y + BAR - 2}" fill="{palette.muted}" font-size="11">not measured</text>'
                )
                y += BAR + GAP
                continue
            bar_width = value * scale
            parts.append(
                f'<rect x="{LABEL_WIDTH}" y="{y}" width="{bar_width:.1f}" height="{BAR}" rx="2" fill="{color}"/>'
            )
            parts.append(
                f'<text x="{LABEL_WIDTH + bar_width + 6:.1f}" y="{y + BAR - 2}" fill="{palette.ink}" font-size="11" font-family="{MONO}">'
                f'{value:.1f}<tspan fill="{palette.muted}"> {escape(note)}</tspan></text>'
            )
            y += BAR + GAP
        y += GROUP_GAP
    parts.append("</svg>\n")
    return "\n".join(parts)


def write_charts() -> list[Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    light = ASSETS / "numbers.svg"
    dark = ASSETS / "numbers-dark.svg"
    light.write_text(render(LIGHT))
    dark.write_text(render(DARK))
    return [light, dark]


if __name__ == "__main__":
    for path in write_charts():
        print("wrote", path)
