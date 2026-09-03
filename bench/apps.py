"""ASGI apps forming a calibration ladder: each rung adds one layer of the stack."""

import gc
import json
import os
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any

from notslowapi import APIRouter, Depends, FastAPI, Header
from pydantic import BaseModel
from notslowapi.starlette.applications import Starlette
from notslowapi.starlette.requests import Request
from notslowapi.starlette.responses import JSONResponse
from notslowapi.starlette.routing import Route

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

PAYLOAD: dict[str, Any] = {"message": "hello", "n": 1}
PAYLOAD_BYTES: bytes = json.dumps(PAYLOAD).encode()
OUT_DIR = Path(__file__).parent / "out"


async def l0_raw(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
                continue
            await send({"type": "lifespan.shutdown.complete"})
            return
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(PAYLOAD_BYTES)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": PAYLOAD_BYTES})


async def starlette_endpoint(request: Request) -> JSONResponse:
    return JSONResponse(PAYLOAD)


l1_starlette = Starlette(routes=[Route("/", starlette_endpoint)])


async def starlette_params_endpoint(request: Request) -> JSONResponse:
    return JSONResponse(
        {"item_id": request.path_params["item_id"], "q": request.query_params.get("q")}
    )


l1b_starlette_params = Starlette(routes=[Route("/items/{item_id:int}", starlette_params_endpoint)])

l2_fastapi_dict = FastAPI()


@l2_fastapi_dict.get("/")
async def fastapi_dict() -> dict[str, Any]:
    return PAYLOAD


l2b_fastapi_untyped = FastAPI()


@l2b_fastapi_untyped.get("/")
async def fastapi_untyped():  # type: ignore[no-untyped-def]
    return PAYLOAD


l2c_fastapi_included = FastAPI()
included_router = APIRouter()


@included_router.get("/")
async def fastapi_included() -> dict[str, Any]:
    return PAYLOAD


l2c_fastapi_included.include_router(included_router)


def many_routes_starlette() -> Starlette:
    async def param_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"id": request.path_params["item_id"]})

    routes = [Route(f"/p{i}/{{item_id}}", param_endpoint) for i in range(10)]
    routes += [Route(f"/r{i}", starlette_endpoint) for i in range(40)]
    return Starlette(routes=routes)


l1c_starlette_50routes = many_routes_starlette()


def many_routes_fastapi() -> FastAPI:
    app = FastAPI()

    async def param_endpoint(item_id: int) -> dict[str, Any]:
        return {"id": item_id}

    async def static_endpoint() -> dict[str, Any]:
        return PAYLOAD

    for i in range(10):
        app.add_api_route(f"/p{i}/{{item_id}}", param_endpoint)
    for i in range(40):
        app.add_api_route(f"/r{i}", static_endpoint)
    return app


l5_fastapi_50routes = many_routes_fastapi()


def many_routes_fastapi_included() -> FastAPI:
    router = APIRouter()

    async def param_endpoint(item_id: int) -> dict[str, Any]:
        return {"id": item_id}

    async def static_endpoint() -> dict[str, Any]:
        return PAYLOAD

    for i in range(10):
        router.add_api_route(f"/p{i}/{{item_id}}", param_endpoint)
    for i in range(40):
        router.add_api_route(f"/r{i}", static_endpoint)
    app = FastAPI()
    app.include_router(router)
    return app


l5b_fastapi_50routes_included = many_routes_fastapi_included()

l3_fastapi_params = FastAPI()


@l3_fastapi_params.get("/items/{item_id}")
async def fastapi_params(item_id: int, q: str | None = None) -> dict[str, Any]:
    return {"item_id": item_id, "q": q}


class Item(BaseModel):
    name: str
    price: float
    tags: list[str] = []


l4_fastapi_model = FastAPI()


@l4_fastapi_model.post("/items", response_model=Item)
async def fastapi_model(item: Item) -> Item:
    return item


l6_fastapi_depends = FastAPI()


async def pagination(skip: int = 0, limit: int = 20) -> dict[str, int]:
    return {"skip": skip, "limit": limit}


async def current_user(x_token: str | None = Header(None)) -> dict[str, Any]:
    return {"user": x_token or "anonymous"}


async def item_access(item_id: int, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"item_id": item_id, "user": user["user"]}


@l6_fastapi_depends.get("/items/{item_id}")
async def fastapi_depends(
    access: dict[str, Any] = Depends(item_access),
    page: dict[str, int] = Depends(pagination),
) -> dict[str, Any]:
    return {**access, **page}


def with_pyinstrument(app: ASGIApp, name: str) -> ASGIApp:
    from pyinstrument import Profiler

    profiler = Profiler(interval=0.0005, async_mode="disabled")

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            await app(scope, receive, send)
            return

        async def observing_receive() -> Message:
            message = await receive()
            if message["type"] == "lifespan.startup":
                profiler.start()
            if message["type"] == "lifespan.shutdown":
                profiler.stop()
                OUT_DIR.mkdir(exist_ok=True)
                (OUT_DIR / f"pyinstrument_{name}.html").write_text(profiler.output_html())
                (OUT_DIR / f"pyinstrument_{name}.txt").write_text(
                    profiler.output_text(unicode=True, color=False, show_all=True)
                )
            return message

        await app(scope, observing_receive, send)

    return wrapped


RUNGS: dict[str, ASGIApp] = {
    "l0_raw": l0_raw,
    "l1_starlette": l1_starlette,
    "l1b_starlette_params": l1b_starlette_params,
    "l2_fastapi_dict": l2_fastapi_dict,
    "l2b_fastapi_untyped": l2b_fastapi_untyped,
    "l2c_fastapi_included": l2c_fastapi_included,
    "l1c_starlette_50routes": l1c_starlette_50routes,
    "l5_fastapi_50routes": l5_fastapi_50routes,
    "l5b_fastapi_50routes_included": l5b_fastapi_50routes_included,
    "l3_fastapi_params": l3_fastapi_params,
    "l4_fastapi_model": l4_fastapi_model,
    "l6_fastapi_depends": l6_fastapi_depends,
}


def selected() -> ASGIApp:
    name = os.environ["BENCH_RUNG"]
    app = RUNGS[name]
    if os.environ.get("BENCH_GC_FREEZE") == "1":
        gc.collect()
        gc.freeze()
    if os.environ.get("BENCH_PROFILE") != "pyinstrument":
        return app
    return with_pyinstrument(app, os.environ.get("BENCH_LABEL", name))


app = selected()
