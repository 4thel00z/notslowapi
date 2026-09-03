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
    gc_freeze: bool = False
    server: str = "uvicorn"
    server_args: tuple[str, ...] = ()
    tag: str = ""
    workers: int = 1

    @property
    def label(self) -> str:
        tags = []
        if self.server != "uvicorn":
            tags.append(self.server)
        if self.loop != "uvloop" or self.http != "httptools":
            tags.append(f"{self.loop}+{self.http}")
        if self.tag:
            tags.append(self.tag)
        if self.workers != 1:
            tags.append(f"w{self.workers}")
        if self.gc_freeze:
            tags.append("gc_freeze")
        if not tags:
            return self.name
        return f"{self.name}[{'+'.join(tags)}]"


@dataclass
class Result:
    rung: Rung
    rps: list[float] = field(default_factory=list)
    p50_us: list[float] = field(default_factory=list)
    p99_us: list[float] = field(default_factory=list)
    cpu_s: list[float] = field(default_factory=list)
    requests: list[int] = field(default_factory=list)

    @property
    def rps_median(self) -> float:
        return statistics.median(self.rps)

    @property
    def us_per_request(self) -> float:
        return 1_000_000 / self.rps_median

    @property
    def cpu_us_per_request(self) -> float:
        """Server CPU time per request; wall-clock load on the machine barely moves it."""
        return statistics.median(1_000_000 * cpu / n for cpu, n in zip(self.cpu_s, self.requests))


UVICORN_TUNED = ("--no-proxy-headers", "--no-server-header", "--no-date-header")

LADDER: list[Rung] = [
    Rung("l0_raw", f"{BASE}/"),
    Rung("l1_starlette", f"{BASE}/"),
    Rung("l1b_starlette_params", f"{BASE}/items/42?q=hello"),
    Rung("l2_fastapi_dict", f"{BASE}/"),
    Rung("l2b_fastapi_untyped", f"{BASE}/"),
    Rung("l2c_fastapi_included", f"{BASE}/"),
    Rung("l1c_starlette_50routes", f"{BASE}/r39"),
    Rung("l5_fastapi_50routes", f"{BASE}/r39"),
    Rung("l5b_fastapi_50routes_included", f"{BASE}/r39"),
    Rung("l3_fastapi_params", f"{BASE}/items/42?q=hello"),
    Rung(
        "l4_fastapi_model",
        f"{BASE}/items",
        method="POST",
        body='{"name": "widget", "price": 1.5, "tags": ["a", "b"]}',
    ),
    Rung("l2_fastapi_dict", f"{BASE}/", loop="asyncio", http="h11"),
    Rung("l3_fastapi_params", f"{BASE}/items/42?q=hello", gc_freeze=True),
    Rung("l0_raw", f"{BASE}/", server_args=UVICORN_TUNED, tag="tuned"),
    Rung("l2_fastapi_dict", f"{BASE}/", server_args=UVICORN_TUNED, tag="tuned"),
    Rung("l0_raw", f"{BASE}/", server="granian"),
    Rung("l1_starlette", f"{BASE}/", server="granian"),
    Rung("l2_fastapi_dict", f"{BASE}/", server="granian"),
    Rung("l3_fastapi_params", f"{BASE}/items/42?q=hello", server="granian"),
    Rung(
        "l4_fastapi_model",
        f"{BASE}/items",
        method="POST",
        body='{"name": "widget", "price": 1.5, "tags": ["a", "b"]}',
        server="granian",
    ),
    Rung("l5b_fastapi_50routes_included", f"{BASE}/r39", server="granian"),
    Rung("l0_raw", f"{BASE}/", server="granian", workers=6),
    Rung("l2_fastapi_dict", f"{BASE}/", server="granian", workers=4),
    Rung("l2_fastapi_dict", f"{BASE}/", server="granian", workers=6),
    Rung("l2_fastapi_dict", f"{BASE}/", server="granian", workers=12),
    Rung("l2_fastapi_dict", f"{BASE}/", workers=6),
    Rung(
        "l0_raw",
        f"{BASE}/",
        server="granian",
        server_args=("--task-impl", "rust"),
        tag="rust-tasks",
    ),
    Rung(
        "l2_fastapi_dict",
        f"{BASE}/",
        server="granian",
        server_args=("--task-impl", "rust"),
        tag="rust-tasks",
    ),
    Rung(
        "l4_fastapi_model",
        f"{BASE}/items",
        method="POST",
        body='{"name": "widget", "price": 1.5, "tags": ["a", "b"]}',
        gc_freeze=True,
    ),
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
    if rung.gc_freeze:
        env["BENCH_GC_FREEZE"] = "1"
    if profile:
        env["BENCH_PROFILE"] = profile
    cmd = server_command(rung)
    proc = subprocess.Popen(cmd, env=env)
    wait_for_port()
    return proc


def server_command(rung: Rung) -> list[str]:
    if rung.server == "granian":
        return [
            sys.executable,
            "-m",
            "granian",
            "--interface",
            "asgi",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--workers",
            str(rung.workers),
            "--loop",
            rung.loop,
            "--no-log",
            *rung.server_args,
            "bench.apps:app",
        ]
    return [
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
        "--workers",
        str(rung.workers),
        *rung.server_args,
    ]


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


def record(result: Result, report: dict, cpu_s: float) -> None:
    summary = report["summary"]
    if summary["successRate"] < 1.0:
        raise RuntimeError(f"{result.rung.label}: success rate {summary['successRate']}")
    result.rps.append(summary["requestsPerSec"])
    result.p50_us.append(report["latencyPercentiles"]["p50"] * 1_000_000)
    result.p99_us.append(report["latencyPercentiles"]["p99"] * 1_000_000)
    result.cpu_s.append(cpu_s)
    result.requests.append(sum(report["statusCodeDistribution"].values()))


def parse_cputime(text: str) -> float:
    """ps cputime: [[DD-]HH:]MM:SS.hh"""
    days = 0.0
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = float(day_text)
    parts = [float(part) for part in text.split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return days * 86400 + seconds


def process_tree(pid: int) -> list[int]:
    children = subprocess.run(
        ["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
    ).stdout.split()
    pids = [pid]
    for child in children:
        pids.extend(process_tree(int(child)))
    return pids


def cpu_seconds(pid: int) -> float:
    """User plus system CPU time of the server process and its workers."""
    pids = ",".join(str(p) for p in process_tree(pid))
    out = subprocess.run(
        ["ps", "-o", "cputime=", "-p", pids], capture_output=True, text=True, check=True
    ).stdout
    return sum(parse_cputime(line.strip()) for line in out.splitlines() if line.strip())


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
            cpu_before = cpu_seconds(proc.pid)
            report = oha(rung, duration, concurrency)
            record(result, report, cpu_seconds(proc.pid) - cpu_before)
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
    print(
        f"{'rung':34} {'rps':>10} {'us/req':>9} {'vs l0':>9} {'cpu us':>9} "
        f"{'p50 us':>9} {'p99 us':>9}"
    )
    for r in results:
        print(
            f"{r.rung.label:34} {r.rps_median:10.0f} {r.us_per_request:9.1f} "
            f"{r.us_per_request - base:+9.1f} {r.cpu_us_per_request:9.1f} "
            f"{statistics.median(r.p50_us):9.0f} {statistics.median(r.p99_us):9.0f}"
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
                    "cpu_s": r.cpu_s,
                    "requests": r.requests,
                    "cpu_us_per_request": r.cpu_us_per_request,
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
