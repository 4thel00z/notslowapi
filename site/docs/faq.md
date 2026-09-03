# FAQ

## Is notslowapi a drop-in replacement for FastAPI?

For code that imports from `fastapi.*`, yes: change the package name to `notslowapi` and the rest stays. The public API is FastAPI 0.141.1's, and the upstream test suite (3,335 tests) plus Starlette's (1,154) pass. Code that imports `starlette.*` directly is the one exception; see the next question and [Compatibility](compatibility.md).

## What about Starlette middleware from PyPI?

`add_middleware` accepts any ASGI middleware class. A package that imports from `starlette.*` needs upstream Starlette installed alongside notslowapi; nothing is installed under that name, so the two do not collide. Its classes then run upstream Starlette code, and the objects it creates are upstream objects rather than `notslowapi.starlette` ones. ASGI scope keys keep their upstream names, so middleware reading `starlette.exception_handlers` and similar keys sees the same values. Middleware written against `notslowapi.starlette.middleware.base.BaseHTTPMiddleware` runs on the modified code.

## Why a fork instead of upstream pull requests?

The changes cut across FastAPI and Starlette at once: the combined exception layer, the shared response-started tracker and the static-route index live in both packages, and several commits port a FastAPI-side change into Starlette itself. They were developed, tested and measured as one tree with one merged test suite, which is what the fork is.

## Will it track FastAPI releases?

notslowapi 0.1.0 is built from FastAPI 0.141.1 and Starlette 1.6.0. The fork is a git subtree of github.com/4thel00z/fastapi with upstream history intact, so upstream releases can be merged and re-measured on the ladder. Releases are built from tags `v*.*.*` and published to PyPI by the release workflow.

## Does it work with Pydantic v1?

No. Upstream FastAPI dropped Pydantic v1 in 0.126.0 and `pydantic.v1` in 0.128.0, and notslowapi is built from 0.141.1. The package requires `pydantic>=2.9.0`.

## How do I report a regression?

Open an issue at [github.com/4thel00z/notslowapi/issues](https://github.com/4thel00z/notslowapi/issues) with the notslowapi version, a minimal app, and what FastAPI 0.141.1 does with the same code. For a performance regression, include the rung or your own app run through `bench.run` before and after:

```console
BENCH_ONLY=l3_fastapi_params uv run python -m bench.run
```

Attach `bench/out/results.json` from both runs, and name the machine, Python version and server used.
