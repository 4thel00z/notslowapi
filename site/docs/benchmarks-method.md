# Benchmark method

## The ladder

`bench/apps.py` defines ASGI apps where each rung adds one layer; all return a small JSON body.

| rung | app | request |
|---|---|---|
| l0_raw | bare ASGI callable, fixed bytes | GET / |
| l1_starlette | one Starlette `Route`, `JSONResponse` | GET / |
| l1b_starlette_params | Starlette `/items/{item_id:int}` reading path and query | GET /items/42?q=hello |
| l1c_starlette_50routes | 10 param plus 40 static Starlette routes | GET /r39, the last |
| l2_fastapi_dict | FastAPI route returning an annotated dict | GET / |
| l2b_fastapi_untyped | same, no return annotation | GET / |
| l2c_fastapi_included | same route via `include_router` | GET / |
| l5_fastapi_50routes | 50 routes via `add_api_route` | GET /r39 |
| l5b_fastapi_50routes_included | 50 routes on an `APIRouter`, included | GET /r39 |
| l3_fastapi_params | `item_id: int` path, optional `q: str` query | GET /items/42?q=hello |
| l4_fastapi_model | pydantic body with `response_model` | POST /items |

A rung's µs/request minus l0_raw is the cost of everything above the server; `bench.run` prints it as `vs l0`.

## Load

`bench/run.py` starts the server for one rung, warms it for 2 s, then runs oha three times:

```console
oha -z 5s -c 64 --no-tui --output-format json http://127.0.0.1:8123/
```

A success rate below 100% aborts. It records requests/s, p50 and p99 per repeat; µs/request is 1,000,000 over the median requests/s. uvicorn runs with `--loop uvloop --http httptools --no-access-log --log-level warning`, granian with `--interface asgi --workers 1 --loop uvloop --no-log`; other server setups are tagged, as in `l2_fastapi_dict[granian]`.

```console
uv run python -m bench.run
BENCH_ONLY=l2_fastapi_dict,l3_fastapi_params uv run python -m bench.run
```

`BENCH_REPEATS`, `BENCH_DURATION` and `BENCH_CONCURRENCY` override 3, 5s and 64. oha must be on `PATH`; granian comes from the `bench` dependency group.

## Profiles

`BENCH_SAMPLE=1` runs macOS `sample(1)` on the server for 8 s under a 9 s load; `bench/analyze_sample.py` buckets top-of-stack frames by library (kernel, malloc, uvloop, httptools, pydantic_core, interpreter, other). `BENCH_PYINSTRUMENT=1` wraps the app in pyinstrument (0.5 ms interval, async mode disabled) and writes HTML and text at shutdown. Output goes to `bench/out/`.

## Before and after

Each change was measured in one window against the previous commit, stashed, at a load average low enough that repeats agree; later changes alternate after/before/after. Runs during a system stall (indexing, a backup, load average of 7 and above) were discarded and the commit says so; one commit's window was too noisy to measure at all. A `gc.freeze()` control left medians unchanged with p99 spikes present: the tail is sporadic stalls, not garbage collection.

A rung's same-window figure and its full-ladder figure differ by a few percent: the plain route is 17.1 µs in the last same-window run and 18.3 µs in `results_ladder_v3.json`. This site quotes same-window figures for before/after comparisons and the full ladder for the per-server table.

## The single-machine ceiling

Multi-worker runs put the load generator and the server on the same cores. Six granian workers measured 140,000 requests/s with oha and about 160,000 with wrk; six uvicorn workers 153,000 and 175,000; twelve granian workers were slower than six, with p99 above 30 ms. These numbers describe the machine, not the framework. Cross-core scaling needs a separate client machine.

## Raw files

Under `bench/baseline/`: `results_ladder_v1.json` (upstream FastAPI 0.141.1, day one), `results_ladder_v3.json` (current full ladder; v2 is older), `results_fixN_before.json` and `results_fixN_after.json` (one pair per change), `results_servers_v1.json` (uvicorn default and tuned, granian, granian `--task-impl rust`), `results_workers_sweep_v1.json` and `wrk_vs_oha_w6_v1.txt` (multi-worker), `results_controls_v1.json` and `results_gc_freeze_check.json`. Compare two files rung by rung:

```console
uv run python bench/compare.py bench/baseline/results_fix1_before.json bench/baseline/results_fix1_after.json
```
