<p align="center">
  <a href="https://notslowapi.com"><img src="https://raw.githubusercontent.com/4thel00z/notslowapi/master/site/landing/assets/logo.svg" alt="notslowapi" width="360"></a>
</p>

<p align="center"><strong>FastAPI, minus the slow.</strong></p>

<p align="center">A fork of FastAPI 0.141.1 that does less work per request: the same public API and test suite, with the plain JSON route down from 31.2 to 18.3 µs on uvicorn and 9.1 µs on granian.</p>

<p align="center">
  <a href="https://pypi.org/project/notslowapi"><img src="https://img.shields.io/pypi/v/notslowapi" alt="PyPI version"></a>
  <a href="https://pypi.org/project/notslowapi"><img src="https://img.shields.io/pypi/pyversions/notslowapi" alt="Python versions"></a>
  <a href="https://github.com/4thel00z/notslowapi/actions/workflows/ci.yml"><img src="https://github.com/4thel00z/notslowapi/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

**Site**: [https://notslowapi.com](https://notslowapi.com)

**Docs**: [https://notslowapi.com/docs/](https://notslowapi.com/docs/)

**Source**: [https://github.com/4thel00z/notslowapi](https://github.com/4thel00z/notslowapi)

## Install

```console
uv add notslowapi[granian]
```

```console
pip install "notslowapi[granian]"
```

Python 3.10 to 3.14 and `pydantic>=2.9.0`. Pydantic v1 is not supported. The base install brings no ASGI server; the `granian` extra adds `granian>=2.0`. The `standard` extra is FastAPI's and pulls the same set upstream does. Nothing is installed under the `fastapi` or `starlette` names, and existing installs of those packages are left alone.

## Switch

```python
from notslowapi import FastAPI
```

Replace the package name `fastapi` with `notslowapi` in every import. The modules upstream exposes under `fastapi.*` exist under `notslowapi.*`: `responses`, `requests`, `middleware`, `security`, `openapi`, `encoders`, `exceptions`, `background`, `staticfiles`, `templating`, `testclient`, `websockets`, `sse`, `status`.

## Run

```console
granian --interface asgi --workers 1 --loop uvloop myapp:app
```

`myapp:app` is the module path and attribute of your `FastAPI` instance. granian's I/O runs on Rust threads alongside the Python thread, so the framework's Python is the only thing left on the critical path. On a bare ASGI callable the server alone costs 7.8 µs per request under granian against 13.5 µs under uvicorn, and the notslowapi route adds 1.3 µs on top of that under granian against 4.8 µs under uvicorn.

On uvicorn, install `uvicorn[standard]` for uvloop and httptools (18.3 µs on the plain route against 64.0 µs on asyncio and h11) and run:

```console
uvicorn myapp:app --loop uvloop --http httptools --no-proxy-headers --no-server-header --no-date-header
```

Leave `--proxy-headers` on if a proxy in front of you sets `X-Forwarded-*` headers and your app reads them.

## Numbers

One core (Apple M3 Pro, Python 3.13), 64 keep-alive connections, median of 3 x 5 s oha runs, one worker. The first column is upstream FastAPI 0.141.1 on uvicorn at the start of the work; the other two are notslowapi 0.1.0. Raw files: `bench/baseline/results_ladder_v1.json` and `results_ladder_v3.json` in the repository.

| route | day one, uvicorn (FastAPI 0.141.1) | notslowapi, uvicorn | notslowapi, granian |
|---|---|---|---|
| raw ASGI app, fixed bytes (server floor) | 13.7 µs, 73,040 req/s | 13.5 µs, 74,172 req/s | 7.8 µs, 128,801 req/s |
| plain JSON route | 31.2 µs, 32,033 req/s | 18.3 µs, 54,793 req/s | 9.1 µs, 110,154 req/s |
| int path + str query param | 57.0 µs, 17,531 req/s | 24.2 µs, 41,405 req/s | 14.3 µs, 69,742 req/s |
| pydantic body + response_model | 52.1 µs, 19,212 req/s | 26.1 µs, 38,295 req/s | 20.1 µs, 49,777 req/s |
| 50 routes via include_router | 92.2 µs, 10,800 req/s * | 26.3 µs, 37,968 req/s | 17.3 µs, 57,864 req/s |

\* This rung did not exist on day one; the figure is the before-run recorded in the include_router commit message.

The changes are inside the framework: parameter extraction, the dependency solver, routing, exception handling and response encoding. Each is one commit with a before and after measurement, listed at [What changed](https://notslowapi.com/docs/what-changed/). The method, the tools and the raw files are at [Benchmark method](https://notslowapi.com/docs/benchmarks-method/); the full tables are at [notslowapi.com/benchmarks/](https://notslowapi.com/benchmarks/).

## Compatibility

notslowapi 0.1.0 has the public API of FastAPI 0.141.1: classes, functions, parameters and behaviors are upstream's, and the changes are internal. The check is the upstream test suite with its imports rewritten: 3,335 FastAPI tests plus 1,154 Starlette tests, 4,489 pass, with the same 8 environmental failures before and after every change. The modified Starlette 1.6.0 ships inside the package as `notslowapi.starlette` and nothing is installed under the `starlette` name, so code that imports `starlette.*` directly needs upstream Starlette installed and gets upstream behavior for those objects.

```python
from notslowapi.starlette.middleware.base import BaseHTTPMiddleware
from notslowapi.starlette.responses import Response
```

Two observable differences: `AsyncExitStackMiddleware` is importable but no longer installed, so the scope no longer carries `fastapi_middleware_astack`, and `solve_dependencies` raises `RuntimeError` instead of failing an `assert` when a `yield` dependency runs without an exit stack. Details at [Compatibility](https://notslowapi.com/docs/compatibility/).

## Reporting a regression

Open an issue at [github.com/4thel00z/notslowapi/issues](https://github.com/4thel00z/notslowapi/issues) with the notslowapi version, a minimal app, and what FastAPI 0.141.1 does with the same code. For a performance regression, name the machine, Python version and server, and attach `bench/out/results.json` from a before and an after run of the ladder.

## Credits

notslowapi is built from [FastAPI](https://fastapi.tiangolo.com) by Sebastián Ramírez and [Starlette](https://starlette.dev) by Encode. The code is theirs; this fork changes how much of it runs per request. FastAPI's documentation applies to notslowapi with the package name swapped.

## License

The FastAPI code is MIT licensed, copyright 2018 Sebastián Ramírez (`LICENSE`). The vendored Starlette is BSD-3-Clause, copyright 2018 Encode OSS Ltd (`notslowapi/starlette/LICENSE.md`). Both files ship in the wheel; the package metadata declares `MIT`.
