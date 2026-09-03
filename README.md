# notslowapi

Home of `notslowapi`, a fork of FastAPI that is being made faster, measured layer by layer.

- `vendor/fastapi`: the fork, Python package `notslowapi`, git subtree of github.com/4thel00z/fastapi
- `vendor/fastapi/notslowapi/starlette`: the modified Starlette, vendored inside the package as `notslowapi.starlette`
- `bench/`: the benchmark ladder (`uv run python -m bench.run`) and `bench/baseline/` with before/after numbers for every change

## Using notslowapi

`notslowapi` is FastAPI with the same API and the same test suite, plus the modified Starlette it depends on
shipped inside the package. Nothing else is installed under the `starlette` name.

```console
uv add notslowapi[granian]
```

```python
from notslowapi import FastAPI
```

Import responses, requests and middleware from `notslowapi.*` as the FastAPI docs already recommend, or from
`notslowapi.starlette.*`. Code that imports `starlette.*` directly needs upstream Starlette installed and gets
upstream behavior for those objects.

## Deploying

Measured on one core (M3 Pro, Python 3.13), 64 keep-alive connections, one route returning a small JSON body,
after the changes in `git log -- vendor/` (ladder v3, `bench/baseline/results_ladder_v3.json`):

| server | raw ASGI µs/request | Starlette route | notslowapi route | notslowapi requests/s |
|---|---|---|---|---|
| uvicorn defaults (uvloop, httptools) | 13.5 | 17.4 | 18.3 | 54,800 |
| granian `--interface asgi --workers 1 --loop uvloop` | 7.8 | 8.5 | 9.1 | 110,200 |

For comparison, upstream FastAPI 0.141.1 on the same uvicorn config measured 31.2 µs/request (32,000 requests/s)
at the start of this work. Typed path and query parameters: 57.0 → 24.2 µs. A pydantic body with
response_model: 52.1 → 26.1 µs. Fifty routes mounted via `include_router`: 92.2 → 26.3 µs.

Use granian. Its Rust I/O threads run alongside the Python thread instead of sharing it, so the
framework's Python is the only thing left on the critical path. If you stay on uvicorn, pass
`--no-proxy-headers --no-server-header --no-date-header` unless you are behind a proxy that sets
`X-Forwarded-*` headers; that is worth about 5 percent.

```console
granian --interface asgi --workers 1 --loop uvloop myapp:app
```

Numbers, profiles and the method are in `bench/baseline/` and the commit messages under `git log -- vendor/`.
