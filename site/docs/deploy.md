# Deploy

## granian

```console
granian --interface asgi --workers 1 --loop uvloop myapp:app
```

`myapp:app` is the module path and attribute of your `FastAPI` instance. The `granian` extra installs the server:

```console
uv add notslowapi[granian]
```

Why granian: its I/O runs on Rust threads alongside the Python thread instead of sharing it, so the framework's Python is the only thing left on the critical path. On the ladder's bare ASGI callable the server alone costs 7.8 µs per request under granian against 13.5 µs under uvicorn, and the notslowapi route adds 1.3 µs on top of that under granian against 4.8 µs under uvicorn.

granian's `--task-impl rust` option made no measurable difference on the plain route: 11.7 µs against 12.0 µs in `bench/baseline/results_servers_v1.json`.

## uvicorn

```console
uvicorn myapp:app --loop uvloop --http httptools --no-proxy-headers --no-server-header --no-date-header
```

`uvicorn[standard]`, part of the `standard` extra, installs uvloop and httptools, and uvicorn picks them when present. Without them, on asyncio and h11, the plain notslowapi route measured 64.0 µs per request against 18.3 µs with uvloop and httptools.

The three `--no-*` flags are worth about 5 percent: 22.0 to 20.8 µs on the plain route in `results_servers_v1.json`. Leave `--proxy-headers` on if you run behind a proxy that sets `X-Forwarded-*` headers and your app reads the client address from them.

## One core, per server

Measured on one core (Apple M3 Pro, Python 3.13), 64 keep-alive connections, one route returning a small JSON body, from `bench/baseline/results_ladder_v3.json`:

| server | raw ASGI µs/request | Starlette route | notslowapi route | notslowapi requests/s |
|---|---|---|---|---|
| uvicorn defaults (uvloop, httptools) | 13.5 | 17.4 | 18.3 | 54,800 |
| granian `--interface asgi --workers 1 --loop uvloop` | 7.8 | 8.5 | 9.1 | 110,200 |

The raw ASGI column is a bare callable that sends fixed bytes; the difference between it and the notslowapi column is the framework's own cost. For comparison, upstream FastAPI 0.141.1 on the same uvicorn configuration measured 31.2 µs per request (32,000 requests/s) at the start of this work.

## Workers

The numbers above use one worker. Multi-worker throughput was not measured cleanly: with the load generator on the same machine, six workers of either server reached 140,000 to 175,000 requests per second, which is the machine's ceiling rather than the framework's. Measuring scaling across cores needs a separate client machine. Details in [Benchmark method](benchmarks-method.md).
