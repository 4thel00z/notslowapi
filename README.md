# notslowapi

Home of `notsoslow`, a fork of FastAPI that is being made faster, measured layer by layer.

- `vendor/fastapi`: the fork (Python package `notsoslow`), git subtree of github.com/4thel00z/fastapi
- `vendor/starlette`: git subtree of github.com/4thel00z/starlette, also modified
- `bench/`: the benchmark ladder (`uv run python -m bench.run`) and `bench/baseline/` with before/after numbers for every change

## Using notsoslow

`notsoslow` is FastAPI with the same API and the same test suite. Import it as `from notsoslow import FastAPI`;
`NotSoSlow` is an alias of `FastAPI`. Starlette is used unchanged in name but comes from `vendor/starlette`.

## Deploying

Measured on one core (M3 Pro, Python 3.13), 64 keep-alive connections, one route returning a small JSON body,
after the changes in `git log -- vendor/` (ladder v3, `bench/baseline/results_ladder_v3.json`):

| server | raw ASGI µs/request | Starlette route | notsoslow route | notsoslow requests/s |
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
