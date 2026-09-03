# What changed

Each change is one commit under `vendor/`, measured before and after in the same window: one core (Apple M3 Pro, Python 3.13), uvicorn with uvloop and httptools unless marked granian, 64 connections, median of 3 x 5 s runs, µs per request. Windows differ, so one change's before need not equal the previous after. Rungs are the apps in `bench/apps.py`; see [Benchmark method](benchmarks-method.md). Themes are in the order their first change was made.

## Parameter extraction

Type annotations were introspected for every parameter on every request; `ModelField` now computes `is_sequence`, alias, `is_model` and location once, and `QueryParams` parses in one loop with `parse_qsl(keep_blank_values=True)` semantics.

- l3_fastapi_params: 50.7 → 35.3 (19.7k → 28.3k req/s); later 24.8 → 22.4, on granian 14.5 → 12.3

## Dependency solver

`solve_dependencies` built a throwaway `Response` and parsed query string, headers and cookies on every request; both now happen only when the route needs them, and endpoints with no dependencies or parameters skip the solver.

- l2_fastapi_dict: 31.0 → 26.3; l3_fastapi_params: 36.2 → 32.6; l4_fastapi_model: 42.7 → 36.7
- l2_fastapi_dict on granian, no-dependency fast path: 14.0 → 10.6

## Exit stacks and middleware only where needed

Two `AsyncExitStack`s were opened per request though only dependencies with `yield` and SSE use them; each route now decides at build time, `AsyncExitStackMiddleware` is no longer installed, and routes that never need a stack get a one-frame route app.

- l2_fastapi_dict: 26.3 → 25.4, then 23.8 → 22.7, then 18.4 → 18.0; l4_fastapi_model: 32.3 → 31.5

## Request handler built once

Included routes rebuilt their handler on every request; it is cached now, routes without a body parameter or streaming get a specialized handler, coroutine endpoints serialize synchronously through pydantic-core, and `Request.body()` no longer goes through an async generator.

- l2c_fastapi_included: 33.4 → 29.2; l3_fastapi_params: 31.6 → 29.7, then 29.7 → 27.5
- l4_fastapi_model: 36.5 → 32.3, then 31.5 → 30.4, then 30.6 → 28.0

## Exception handling and dispatch frames

Response-start tracking became plain functions, then one tracker shared through the scope; without user middleware, `ServerErrorMiddleware`, `ExceptionMiddleware` and the router became one `ExceptionHandlingMiddleware` (apps with user middleware keep all three); `APIRoute.handle`, `FastAPI.__call__` and `request_response` each dropped a frame; `JSONResponse.render` calls the C encoder directly. The shared-tracker commit was not measured: its window was too noisy, and it says so.

- l2_fastapi_dict: 24.6 → 23.8, then 18.9 → 18.2, then 19.4 → 18.9
- l1_starlette: 18.6 → 18.0, then 17.5 → 16.8 (granian 10.2 → 9.4)

## JSON encoding

Content-type headers come from a cache, `JSONResponse` reuses one encoder, and `jsonable_encoder` returns plain `str`, `int`, `float`, `bool`, `None`, `list` and str-keyed `dict` values unchanged when no include, exclude or custom encoder is set.

- l1_starlette: 19.4 → 18.6; l2b_fastapi_untyped: 20.3 → 18.0 (49.2k → 55.4k req/s)

## Routing

Every route was matched in order; an index per routes version now maps each static path to the routes that can match it (a plain list assigned to `router.routes` falls back to the scan), included routes are matched once instead of twice, and exact static-path hits skip `matches()`.

- l1c_starlette_50routes: 26.7 → 20.5; l5_fastapi_50routes: 36.3 → 25.2
- l5b_fastapi_50routes_included: 92.2 → 31.7 (10.8k → 31.6k req/s), then 31.7 → 29.8
- l2c_fastapi_included: 26.8 → 23.1; l2_fastapi_dict: 17.8 → 17.1

## Starlette vendored

The last commit moves the modified Starlette into the package as `notslowapi.starlette` and drops the PyPI `starlette` dependency; ladder check afterwards: l2 17.8 and l3 22.3 against 17.1 and 22.4, within noise.

## What did not change

The public API: each commit's probe (routing order, included routers, dependencies with `yield`, exceptions before and after response start, forms, response types) is identical before and after. The OpenAPI path list, checked in the included-router probe. The test suite: 3,335 FastAPI and 1,154 Starlette tests, 4,489 in total, with the same 8 environmental failures throughout.
