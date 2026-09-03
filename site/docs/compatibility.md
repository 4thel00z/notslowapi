# Compatibility

notslowapi 0.1.0 has the same public API as FastAPI 0.141.1. Classes, functions, parameters and behaviors are upstream's; the changes are internal. The check is the upstream test suite, run unchanged apart from import paths.

## Imports

Replace the `fastapi` package name with `notslowapi`:

```python
from notslowapi import FastAPI, APIRouter, Depends, Query, Path, Body, HTTPException
from notslowapi.responses import JSONResponse, StreamingResponse
from notslowapi.requests import Request
from notslowapi.middleware.cors import CORSMiddleware
from notslowapi.testclient import TestClient
```

The modules upstream exposes under `fastapi.*` exist under `notslowapi.*`: `responses`, `requests`, `middleware`, `security`, `openapi`, `encoders`, `exceptions`, `background`, `staticfiles`, `templating`, `testclient`, `websockets`, `sse`, `status`.

## Starlette

The modified Starlette 1.6.0 ships inside the package:

```python
from notslowapi.starlette.middleware.base import BaseHTTPMiddleware
from notslowapi.starlette.responses import Response
```

Nothing is installed under the `starlette` name. Code that imports `starlette.*` directly needs upstream Starlette installed and gets upstream behavior for those objects. ASGI scope keys keep their upstream strings (`starlette.exception_handlers` and the rest), so ASGI middleware that reads the scope sees the same keys.

## Behaviors kept

- `include_router`: direct, nested and late-added included routes, param-before-static and static-before-param ordering, partial matches with 405 `Allow`, and the OpenAPI path list were probed before and after each routing change and are identical. `APIRouter.matches` remains an override point for subclasses.
- Dependencies with `yield`: request- and function-scoped, `HTTPException` raised through them, SSE, and `dependency_overrides` swapping in a `yield` dependency behave as before. Overrides force the exit-stack path at request time.
- Middleware: `add_middleware` works as before. Apps with user middleware keep upstream's three-layer exception stack (`ServerErrorMiddleware`, `ExceptionMiddleware`, router); the single combined layer is installed only when there is no user middleware.
- Exception handlers, `debug` tracebacks, custom 500 handlers, handled and unhandled errors before and after the response started: a 112-line probe is identical across 8 configurations.
- Forms and uploads: uploaded files are closed after the response is sent, as before.

## Observable differences

- `notslowapi.middleware.asyncexitstack.AsyncExitStackMiddleware` is still importable but is no longer installed, so the scope no longer carries `fastapi_middleware_astack`.
- `solve_dependencies` raises `RuntimeError` instead of failing an `assert` when a `yield` dependency runs without an exit stack.

## The test suite

The merged suite is FastAPI's 3,335 tests plus Starlette's 1,154: 4,489 in total. All pass. Eight further tests fail for environmental reasons (the OpenTelemetry SDK not installed, `strawberry.fastapi`, `fastapi-cli`, tests that depend on the working directory) and fail the same way before and after every change. CI runs ruff on both trees and then the suite:

```console
uv sync --group test
uv run pytest -c vendor/fastapi/pyproject.toml --rootdir vendor/fastapi vendor/fastapi/tests
```

CI adds `--ignore` flags for the benchmark and GraphQL tutorial directories.
