# notslowapi

notslowapi is a fork of FastAPI 0.141.1 that does less work per request. The public API is the one you already use, and the upstream test suite passes unchanged: 4,489 tests across FastAPI and Starlette. The changes are inside the framework: parameter extraction, the dependency solver, routing, exception handling and response encoding. Every change is one commit with a before and after measurement, and the numbers and profiles are committed to the repository.

The Starlette it depends on (1.6.0) is modified as well and ships inside the package as `notslowapi.starlette`. Nothing is installed under the `starlette` name, so notslowapi can sit next to an upstream Starlette install without either overwriting the other. The first release is 0.1.0. FastAPI code is MIT licensed; the vendored Starlette keeps its BSD-3 license.

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

One core, Apple M3 Pro, Python 3.13, 64 keep-alive connections, median of 3 x 5 s runs. The first column is upstream FastAPI 0.141.1 on uvicorn at the start of the work; the other two are notslowapi 0.1.0.

| route | FastAPI 0.141 on uvicorn | notslowapi on uvicorn | notslowapi on granian |
|---|---|---|---|
| plain JSON route | 31.2 µs/req, 32,000 req/s | 17.1 µs/req, 58,000 req/s | 8.7 µs/req, 114,000 req/s |
| int path + str query param | 57.0 µs/req | 22.4 µs/req | 12.3 µs/req |
| pydantic body + response_model | 52.1 µs/req | 26.1 µs/req | 20.1 µs/req |
| 50 routes via include_router | 92.2 µs/req | 26.3 µs/req | 17.3 µs/req |

Staying on uvicorn: 1.8x the requests per core on the plain route, 2.5x on typed parameters, 3.5x on fifty included routes. Moving the plain route to granian: 3.6x. The before column is `bench/baseline/results_ladder_v1.json`; the after columns are the same-window runs recorded in the commit messages and `results_ladder_v3.json`. How they were taken is in [Benchmark method](benchmarks-method.md).

## Pages

- [Install](install.md): uv, pip, extras, Python versions
- [Deploy](deploy.md): granian, uvicorn flags, per-server numbers
- [What changed](what-changed.md): each change with its measured effect
- [Compatibility](compatibility.md): imports, Starlette, the test suite
- [Benchmark method](benchmarks-method.md): the ladder, the tools, the raw files
- [FAQ](faq.md)

Benchmark tables are at [notslowapi.com/benchmarks](https://notslowapi.com/benchmarks/). Source and issues: [github.com/4thel00z/notslowapi](https://github.com/4thel00z/notslowapi).
