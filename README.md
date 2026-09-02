# notslowapi

Home of `notsoslow`, a fork of FastAPI that is being made faster, measured layer by layer.

- `vendor/fastapi`: the fork (Python package `notsoslow`), git subtree of github.com/4thel00z/fastapi
- `vendor/starlette`: git subtree of github.com/4thel00z/starlette, also modified
- `bench/`: the benchmark ladder (`uv run python -m bench.run`) and `bench/baseline/` with before/after numbers for every change

## Using notsoslow

`notsoslow` is FastAPI with the same API and the same test suite. Import it as `from notsoslow import FastAPI`;
`NotSoSlow` is an alias of `FastAPI`. Starlette is used unchanged in name but comes from `vendor/starlette`.

## Deploying

Measured on one core (M3 Pro, Python 3.13), 64 keep-alive connections, one route returning a small JSON body:

| server | raw ASGI µs/request | notsoslow route µs/request | requests/s |
|---|---|---|---|
| uvicorn defaults (uvloop, httptools) | 13.5 | 22.0 | 45,500 |
| uvicorn with `--no-proxy-headers --no-server-header --no-date-header` | 13.0 | 20.8 | 48,000 |
| granian `--interface asgi --workers 1 --loop uvloop` | 8.3 | 11.7 | 85,800 |

Use granian. Its Rust I/O threads run alongside the Python thread instead of sharing it, so the
framework's Python is the only thing left on the critical path. If you stay on uvicorn, pass the three
flags above unless you are behind a proxy that sets `X-Forwarded-*` headers.

```console
granian --interface asgi --workers 1 --loop uvloop myapp:app
```

Numbers, profiles and the method are in `bench/baseline/` and the commit messages under `git log -- vendor/`.
