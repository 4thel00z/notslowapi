"""Compare two results.json files from bench.run rung by rung."""

import json
import statistics
import sys
from pathlib import Path


def load(path: str) -> dict[str, dict]:
    return {row["rung"]: row for row in json.loads(Path(path).read_text())}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: compare.py before.json after.json")
    before, after = load(sys.argv[1]), load(sys.argv[2])
    print(f"{'rung':26} {'before us':>10} {'after us':>10} {'delta us':>10} {'change':>8} {'rps before':>11} {'rps after':>10}")
    for rung in before:
        if rung not in after:
            continue
        b, a = before[rung], after[rung]
        bu, au = b["us_per_request"], a["us_per_request"]
        print(
            f"{rung:26} {bu:10.1f} {au:10.1f} {au - bu:+10.1f} {(au - bu) / bu:+8.1%} "
            f"{statistics.median(b['rps']):11.0f} {statistics.median(a['rps']):10.0f}"
        )


if __name__ == "__main__":
    main()
