"""Drive uvicorn + oha across the ladder and report rps, latency and per-layer delta."""

import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"
HOST = "127.0.0.1"
PORT = 8123
BASE = f"http://{HOST}:{PORT}"


@dataclass(frozen=True)
class Rung:
    name: str
    url: str
    method: str = "GET"
    body: str | None = None
    loop: str = "uvloop"
    http: str = "httptools"

    @property
    def label(self) -> str:
        if self.loop == "uvloop" and self.http == "httptools":
            return self.name
        return f"{self.name}[{self.loop}+{self.http}]"


@dataclass
class Result:
    rung: Rung
    rps: list[float] = field(default_factory=list)
    p50_us: list[float] = field(default_factory=list)
    p99_us: list[float] = field(default_factory=list)

    @property
    def rps_median(self) -> float:
        return statistics.median(self.rps)

    @property
    def us_per_request(self) -> float:
        return 1_000_000 / self.rps_median


LADDER: list[Rung] = [
    Rung("l0_raw", f"{BASE}/"),
    Rung("l1_starlette", f"{BASE}/"),
    Rung("l1b_starlette_params", f"{BASE}/items/42?q=hello"),
    Rung("l2_fastapi_dict", f"{BASE}/"),
    Rung("l2b_fastapi_untyped", f"{BASE}/"),
    Rung("l3_fastapi_params", f"{BASE}/items/42?q=hello"),
    Rung(
        "l4_fastapi_model",
        f"{BASE}/items",
        method="POST",
        body='{"name": "widget", "price": 1.5, "tags": ["a", "b"]}',
    ),
    Rung("l2_fastapi_dict", f"{BASE}/", loop="asyncio", http="h11"),
]


def wait_for_port(timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"server on {HOST}:{PORT} did not come up in {timeout_s}s")


def start_server(rung: Rung, profile: str | None) -> subprocess.Popen[bytes]:
    env = dict(os.environ, BENCH_RUNG=rung.name, BENCH_LABEL=rung.label)
    if profile:
        env["BENCH_PROFILE"] = profile
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "bench.apps:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
        "--loop",
        rung.loop,
        "--http",
        rung.http,
        "--no-access-log",
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, env=env)
    wait_for_port()
    return proc


def stop_server(proc: subprocess.Popen[bytes]) -> None:
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def oha(rung: Rung, duration: str, concurrency: int) -> dict:
    cmd = [
        "oha",
        "-z",
        duration,
        "-c",
        str(concurrency),
        "--no-tui",
        "--output-format",
        "json",
        "-m",
        rung.method,
    ]
    if rung.body:
        cmd += ["-d", rung.body, "-H", "content-type: application/json"]
    cmd.append(rung.url)
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def record(result: Result, report: dict) -> None:
    summary = report["summary"]
    if summary["successRate"] < 1.0:
        raise RuntimeError(f"{result.rung.label}: success rate {summary['successRate']}")
    result.rps.append(summary["requestsPerSec"])
    result.p50_us.append(report["latencyPercentiles"]["p50"] * 1_000_000)
    result.p99_us.append(report["latencyPercentiles"]["p99"] * 1_000_000)


def sample_native(pid: int, name: str, seconds: int) -> subprocess.Popen[bytes]:
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"sample_{name}.txt"
    return subprocess.Popen(
        ["sample", str(pid), str(seconds), "-f", str(out)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def measure(rung: Rung, repeats: int, duration: str, concurrency: int, native: bool) -> Result:
    result = Result(rung)
    proc = start_server(rung, profile=None)
    try:
        oha(rung, "2s", concurrency)
        for _ in range(repeats):
            record(result, oha(rung, duration, concurrency))
        if not native:
            return result
        sampler = sample_native(proc.pid, rung.label, 8)
        oha(rung, "9s", concurrency)
        sampler.wait()
    finally:
        stop_server(proc)
    return result


def profile(rung: Rung, duration: str, concurrency: int) -> None:
    proc = start_server(rung, profile="pyinstrument")
    try:
        oha(rung, duration, concurrency)
    finally:
        stop_server(proc)


def print_table(results: list[Result]) -> None:
    base = results[0].us_per_request
    print()
    print(f"{'rung':34} {'rps':>10} {'us/req':>9} {'vs l0':>9} {'p50 us':>9} {'p99 us':>9}")
    for r in results:
        print(
            f"{r.rung.label:34} {r.rps_median:10.0f} {r.us_per_request:9.1f} "
            f"{r.us_per_request - base:+9.1f} {statistics.median(r.p50_us):9.0f} "
            f"{statistics.median(r.p99_us):9.0f}"
        )
    print()


def main() -> None:
    repeats = int(os.environ.get("BENCH_REPEATS", "3"))
    duration = os.environ.get("BENCH_DURATION", "5s")
    concurrency = int(os.environ.get("BENCH_CONCURRENCY", "64"))
    native = os.environ.get("BENCH_SAMPLE") == "1"
    do_profile = os.environ.get("BENCH_PYINSTRUMENT") == "1"
    only = set(filter(None, os.environ.get("BENCH_ONLY", "").split(",")))
    rungs = [r for r in LADDER if not only or r.label in only]

    results = [measure(r, repeats, duration, concurrency, native) for r in rungs]
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "results.json").write_text(
        json.dumps(
            [
                {
                    "rung": r.rung.label,
                    "rps": r.rps,
                    "p50_us": r.p50_us,
                    "p99_us": r.p99_us,
                    "us_per_request": r.us_per_request,
                }
                for r in results
            ],
            indent=2,
        )
    )
    print_table(results)
    if not do_profile:
        return
    for r in rungs:
        profile(r, duration, concurrency)


if __name__ == "__main__":
    main()
