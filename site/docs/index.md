# notslowapi

notslowapi is a fork of FastAPI 0.141.1 that does less work per request. The public API is the one you already use, and the upstream test suite passes unchanged: 4,493 tests across FastAPI and Starlette. The changes are inside the framework: parameter extraction, the dependency solver, routing, exception handling and response encoding. Every change is one commit with a before and after measurement, and the numbers and profiles are committed to the repository.

The Starlette it depends on (1.6.0) is modified as well and ships inside the package as `notslowapi.starlette`. Nothing is installed under the `starlette` name, so notslowapi can sit next to an upstream Starlette install without either overwriting the other. The current release is 0.2.0. FastAPI code is MIT licensed; the vendored Starlette keeps its BSD-3 license.

## The switch

Install with the granian extra:

```console
uv add notslowapi[granian]
```

Change the import:

```python
from notslowapi import FastAPI
```

Run under granian:

```console
granian --interface asgi --workers 1 --loop uvloop myapp:app
```

## Numbers

One core, Apple M3 Pro, Python 3.13, 64 keep-alive connections, median of 3 x 5 s runs. The first column is upstream FastAPI 0.141.1 on uvicorn at the start of the work; the other two are the current master (all changes through 0.2.0).

| route | FastAPI 0.141 on uvicorn | notslowapi on uvicorn | notslowapi on granian |
|---|---|---|---|
| raw ASGI app (server floor) | 13.7 µs/req, 73,040 req/s | 13.4 µs/req, 74,846 req/s | 7.9 µs/req, 126,443 req/s |
| plain JSON route | 31.2 µs/req, 32,033 req/s | 15.8 µs/req, 63,374 req/s | 8.5 µs/req, 117,318 req/s |
| int path + str query param | 57.0 µs/req, 17,531 req/s | 18.3 µs/req, 54,769 req/s | 9.0 µs/req, 111,149 req/s |
| pydantic body + response_model | 52.1 µs/req, 19,212 req/s | 21.1 µs/req, 47,445 req/s | 14.1 µs/req, 71,011 req/s |
| 50 routes via include_router | 92.2 µs/req * | 16.7 µs/req, 59,862 req/s | 8.5 µs/req, 117,379 req/s |
| three dependencies (path, header, query via Depends) | not measured | 25.0 µs/req, 39,953 req/s | 14.9 µs/req, 67,232 req/s |

Staying on uvicorn: 2.0x the requests per core on the plain route, 3.1x on typed parameters, 2.5x on a pydantic body. Moving the plain route to granian: 3.7x. The before column is `bench/baseline/results_ladder_v1.json`; both after columns are `results_ladder_v4.json`, the same files the landing page and the README quote.

\* This rung did not exist on day one. The 92.2 µs is the before-run of the include_router change (`results_fix11_before.json`), taken on a tree that already had the first ten changes, so it understates the day-one gap. How the runs were taken is in [Benchmark method](benchmarks-method.md).

## Pages

- [Install](install.md): uv, pip, extras, Python versions
- [Deploy](deploy.md): granian, uvicorn flags, per-server numbers
- [What changed](what-changed.md): each change with its measured effect
- [Compatibility](compatibility.md): imports, Starlette, the test suite
- [Benchmark method](benchmarks-method.md): the ladder, the tools, the raw files
- [FAQ](faq.md)

Benchmark tables are at [notslowapi.com/benchmarks](https://notslowapi.com/benchmarks/). Source and issues: [github.com/4thel00z/notslowapi](https://github.com/4thel00z/notslowapi).
