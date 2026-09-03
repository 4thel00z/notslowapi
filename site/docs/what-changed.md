# What changed

Each change is one commit under `vendor/` with a same-window before and after, in µs per request on one core under the setup in [Benchmark method](benchmarks-method.md); uvicorn unless marked granian. Windows differ, so a before need not equal the previous after. Rungs are the apps in `bench/apps.py`. Themes are in the order their first change was made.

## Parameter extraction

Type annotations were introspected for every parameter on every request; `ModelField` now computes `is_sequence`, alias, `is_model` and location once, and `QueryParams` parses in one loop with `parse_qsl(keep_blank_values=True)` semantics. `ModelField` also caches `required` and whether the field is `Json`-annotated, `request_params_to_args` validates in one loop instead of three nested helpers, `solve_dependencies` looks up exit stacks only when a `yield` dependency runs, `plain_app` calls the endpoint directly, and `Request.query_params` builds `QueryParams` without the constructor's argument handling.

- l3_fastapi_params: 50.7 → 35.3 (19.7k → 28.3k req/s); later 24.8 → 22.4, on granian 14.5 → 12.3
- l1b_starlette_params: 20.1 → 19.2; l3_fastapi_params: 23.2 → 23.0, on granian 14.8 → 13.5

## Dependency solver

`solve_dependencies` built a throwaway `Response` and parsed query string, headers and cookies on every request; both now happen only when the route needs them, and endpoints with no dependencies or parameters skip the solver.

- l2_fastapi_dict: 31.0 → 26.3; l3_fastapi_params: 36.2 → 32.6; l4_fastapi_model: 42.7 → 36.7
- l2_fastapi_dict on granian, no-dependency fast path: 14.0 → 10.6

## Parameters read straight from the scope

Routes whose parameters are only path and query params still ran the general solver on every request: `solve_dependencies`, two `request_params_to_args` calls, two helpers per parameter, `request.query_params`, and a `Request` object that only the error paths read. `compile_param_specs` now builds one tuple per parameter when the route is built (routes with dependencies, body, header or cookie params, `Request`/`Response`/`BackgroundTasks` parameters or model query params keep the solver), and `params_route_app` reads `path_params` from the scope, parses the query string once, validates with the same defaults and errors, and sends the response the direct way; the `Request` exists only when an exception needs it.

- l3_fastapi_params: 21.4 → 18.9 (46.7k → 52.9k req/s); on granian 11.4 → 10.0 (87.7k → 100.0k req/s)

## Dependency facts computed once

A route with three `Depends` (one nested; a path param, a header and pagination query params arriving through them, the shape most applications have) cost twice the params route, and the profile showed work that is constant per dependant being redone on every request: the dependency cache key (`_uses_scopes` walking the sub-tree and unwrapping callables, `_get_computed_scope` re-running the generator checks), the coroutine and generator classification of each dependency, a `typing.cast(Callable[..., Any], …)` that builds a generic alias, and a throwaway `Response` for every route with dependencies. `Dependant` now caches its cache key, call kinds and whether any dependency takes a `Response`, and `solve_dependencies` uses them. Each dependant also compiles its parameter plan once (path, query, header and cookie params in the solver's order, with alias, multi-value and model flags), so the solver runs one extraction pass instead of four helper layers per parameter, and optional defaults are read from the field directly instead of through pydantic's `get_default` and a second `deepcopy`. A leaf dependency (no sub-dependencies, no body or special parameters, which is most of them) is then solved inside its parent's loop from its compiled plan instead of through a recursive `solve_dependencies` call and a `SolvedDependency` of its own; caching, `use_cache=False`, error collection and `yield` handling are unchanged, and overrides keep the recursive path.

- l6_fastapi_depends: 38.1 → 28.9 (26.2k → 34.6k req/s); on granian 29.6 → 19.8 (33.8k → 50.5k req/s)
- l6_fastapi_depends: 29.0 → 27.3; on granian 19.5 → 18.1
- l6_fastapi_depends: 25.9 → 25.0; on granian 16.4 → 15.0

## Exit stacks and middleware only where needed

Two `AsyncExitStack`s were opened per request though only dependencies with `yield` and SSE use them; routes now decide at build time, `AsyncExitStackMiddleware` is no longer installed, and routes that never need a stack get a one-frame app.

- l2_fastapi_dict: 26.3 → 25.4, then 23.8 → 22.7, then 18.4 → 18.0; l4_fastapi_model: 32.3 → 31.5

## Request handler built once

Included routes rebuilt their handler on every request; it is cached now, routes without a body parameter or streaming get a specialized handler, coroutine endpoints serialize synchronously through pydantic-core, and `Request.body()` no longer goes through an async generator.

- l2c_fastapi_included: 33.4 → 29.2; l3_fastapi_params: 31.6 → 29.7, then 29.7 → 27.5
- l4_fastapi_model: 36.5 → 32.3, then 31.5 → 30.4, then 30.6 → 28.0

## Exception handling and dispatch frames

Response-start tracking became plain functions, then one tracker shared through the scope; without user middleware, `ServerErrorMiddleware`, `ExceptionMiddleware` and the router became one `ExceptionHandlingMiddleware` (apps with user middleware keep all three); `APIRoute.handle`, `FastAPI.__call__` and `request_response` each dropped a frame; `JSONResponse.render` calls the C encoder directly. The shared-tracker commit went unmeasured; its window was too noisy. Later, `APIRouter.app` matches dynamic routes inline and awaits the route's ASGI app directly on a full match, and a coroutine endpoint without parameters runs inside the request wrapper's own coroutine (`trivial_route_app`) instead of behind a handler frame. Routes with dependencies but no `yield` dependency get the one-frame app too, with one per-request check that hands the request to the general app whenever `dependency_overrides` are set. The vendored Starlette router got the same treatment: plain routes are matched inline and dispatched to their app directly, `request_response` sends a plain response itself, and `JSONResponse` builds its headers without the generic walk.

- l2_fastapi_dict: 24.6 → 23.8, then 18.9 → 18.2, then 19.4 → 18.9
- l1_starlette: 18.6 → 18.0, then 17.5 → 16.8 (granian 10.2 → 9.4)
- l2_fastapi_dict: 17.5 → 17.2, on granian 9.2 → 8.9; l3_fastapi_params: 22.4 → 22.0, on granian 11.9 → 11.3
- l6_fastapi_depends: 27.1 → 25.8; on granian 17.7 → 16.1
- l1_starlette: 16.9 → 16.3; l1b_starlette_params: 18.7 → 17.8; l1c_starlette_50routes: 16.8 → 16.3; on granian l1_starlette flat (8.8 → 8.8)

## JSON encoding

Content-type headers come from a cache, `JSONResponse` reuses one encoder, and `jsonable_encoder` returns plain `str`, `int`, `float`, `bool`, `None`, `list` and str-keyed `dict` values unchanged when no include, exclude or custom encoder is set. For a coroutine endpoint without parameters the wrapper now validates and serializes straight to bytes, decides status, body and `content-length` at build time, sends the two ASGI messages itself instead of building a `Response`, and creates the `Request` only when an exception needs it. Coroutine endpoints with parameters and no dependencies take the same path after the solver runs, unless a `Response` or `BackgroundTasks` parameter took part. Untyped returns with the default response class are encoded to the same bytes `JSONResponse` would produce and sent the same way.

- l1_starlette: 19.4 → 18.6; l2b_fastapi_untyped: 20.3 → 18.0 (49.2k → 55.4k req/s)
- l2_fastapi_dict: 17.9 → 16.6 (55.9k → 60.2k req/s), on granian 9.9 → 9.1; l2b_fastapi_untyped: 18.9 → 18.3
- l3_fastapi_params: 22.7 → 21.7 (minimums 22.5 → 21.2), on granian minimums 12.4 → 11.4 in a loaded window
- l2b_fastapi_untyped: 18.4 → 17.1 (54.3k → 58.5k req/s)

## Routing

Every route was matched in order; an index per routes version now maps each static path to the routes that can match it (a plain list assigned to `router.routes` falls back to the scan), included routes are matched once instead of twice, and exact static-path hits skip `matches()`. A static route mounted with `include_router` went through eight matching and handling layers, including a regex match on a static path; the app's router now asks the included router for a static full match and dispatches to the route directly, with the general path kept for router and route subclasses, dynamic matches and method mismatches.

- l1c_starlette_50routes: 26.7 → 20.5; l5_fastapi_50routes: 36.3 → 25.2
- l5b_fastapi_50routes_included: 92.2 → 31.7 (10.8k → 31.6k req/s), then 31.7 → 29.8
- l2c_fastapi_included: 26.8 → 23.1; l2_fastapi_dict: 17.8 → 17.1
- l2c_fastapi_included: 21.0 → 18.3; l5b_fastapi_50routes_included: 26.6 → 20.6 (37.6k → 48.5k req/s), on granian 17.5 → 10.7 (57.1k → 93.5k req/s)

## Route index by literal prefix

The route index put every dynamic route into every static path's candidate list, so an app declaring `/p0/{item_id}` … `/p9/{item_id}` before forty static routes regex-tested all ten on each request for a static path. A route's regex is anchored and starts with the literal before its first parameter, so a dynamic route now joins only the buckets whose path starts with that literal; declaration order inside a bucket is unchanged and `Mount`, `Host` and custom routes stay candidates everywhere.

- l1c_starlette_50routes: 19.7 → 16.9; l5_fastapi_50routes: 22.1 → 18.3 (45.2k → 54.6k req/s); l5b_fastapi_50routes_included: 26.3 → 21.2

## Starlette vendored

The last commit moves the modified Starlette into the package as `notslowapi.starlette` and drops the PyPI `starlette` dependency; ladder check afterwards: l2 17.8 and l3 22.3 against 17.1 and 22.4, within noise.

## JSON body validated from bytes

A route whose only parameter is one JSON body read the body, built `Headers` to find the content type, ran `json.loads`, then had the solver validate the dict with `validate_python`. Such routes now get a handler that reads the content type from the raw ASGI headers and hands the bytes to pydantic-core's JSON validator in one pass, skipping the solver. Empty, `null`, non-JSON and invalid bodies, and any validation error, go through the upstream handler so the responses stay identical; strict models are the one documented difference (see [Compatibility](compatibility.md)). The wrapper then reads the body straight from `receive`, validates the bytes, awaits the endpoint and sends the two ASGI messages itself; cases it cannot decide identically replay the body into the previous handler.

- l4_fastapi_model: 26.7 → 22.1 (37.4k → 45.4k req/s); on granian 21.4 → 15.7 (46.6k → 64.1k req/s)
- l4_fastapi_model: 21.2 → 19.3 (47.2k → 51.8k req/s); on granian 14.6 → 13.1 (68.5k → 76.3k req/s)

## What did not change

The public API: each commit's probe (routing, included routers, `yield` dependencies, exceptions around response start, forms, response types) is identical before and after. The OpenAPI path list. The test suite: the same FastAPI and Starlette tests pass before and after every change, 4,493 today.
