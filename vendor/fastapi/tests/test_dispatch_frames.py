from typing import Any

from notslowapi import FastAPI, HTTPException, Request, Response
from notslowapi.responses import JSONResponse, PlainTextResponse
from notslowapi.routing import (
    APIRoute,
    TrivialHandlerParts,
    route_app,
)
from notslowapi.testclient import TestClient


class Boom(Exception):
    pass


app = FastAPI()


@app.exception_handler(Boom)
async def handle_boom(request: Request, exc: Boom) -> JSONResponse:
    return JSONResponse({"handled": "boom", "path": request.url.path}, status_code=418)


@app.get("/items/{item_id}")
async def dynamic(item_id: int) -> dict[str, Any]:
    return {"item_id": item_id}


@app.post("/items/{item_id}")
async def dynamic_post(item_id: int) -> dict[str, Any]:
    return {"posted": item_id}


@app.get("/only-get/{name}")
async def only_get(name: str) -> dict[str, Any]:
    return {"name": name}


@app.get("/plain")
async def plain() -> dict[str, Any]:
    return {"plain": True}


@app.get("/raw")
async def raw() -> Response:
    return PlainTextResponse("raw")


@app.get("/http-error")
async def http_error() -> dict[str, Any]:
    raise HTTPException(status_code=404, detail="nope")


@app.get("/custom-error")
async def custom_error() -> dict[str, Any]:
    raise Boom()


@app.get("/sync")
def sync_endpoint() -> dict[str, Any]:
    return {"sync": True}


@app.get("/typed")
async def typed() -> list[int]:
    return [1, 2, 3]


client = TestClient(app)


def route_for(path: str) -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)


def test_coroutine_endpoints_without_parameters_get_the_merged_app() -> None:
    handler = route_for("/plain").get_route_handler()
    assert isinstance(getattr(handler, "parts", None), TrivialHandlerParts)
    assert route_for("/plain").app.__qualname__ == "trivial_route_app.<locals>.app"


def test_sync_and_parameter_endpoints_keep_the_two_frame_app() -> None:
    assert not hasattr(route_for("/sync").get_route_handler(), "parts")
    assert not hasattr(route_for("/items/{item_id}").get_route_handler(), "parts")
    assert (
        route_for("/sync").app.__qualname__ == "trivial_request_response.<locals>.app"
    )


def test_wrapped_handler_from_a_get_route_handler_override_is_not_inlined() -> None:
    class WrappingRoute(APIRoute):
        def get_route_handler(self) -> Any:
            handler = super().get_route_handler()

            async def custom(request: Request) -> Response:
                response = await handler(request)
                response.headers["x-wrapped"] = "1"
                return response

            return custom

    wrapped = FastAPI()
    wrapped.router.route_class = WrappingRoute

    @wrapped.get("/w")
    async def w() -> dict[str, Any]:
        return {"w": True}

    response = TestClient(wrapped).get("/w")
    assert response.json() == {"w": True}
    assert response.headers["x-wrapped"] == "1"


def test_direct_dispatch_still_calls_an_overridden_handle() -> None:
    calls: list[str] = []

    class TracingRoute(APIRoute):
        async def handle(self, scope: Any, receive: Any, send: Any) -> None:
            calls.append(scope["path"])
            await super().handle(scope, receive, send)

    traced = FastAPI()
    traced.router.route_class = TracingRoute

    @traced.get("/t")
    async def t() -> dict[str, Any]:
        return {"t": True}

    @traced.get("/t/{x}")
    async def tx(x: str) -> dict[str, Any]:
        return {"x": x}

    tracing_client = TestClient(traced)
    assert tracing_client.get("/t").json() == {"t": True}
    assert tracing_client.get("/t/1").json() == {"x": "1"}
    assert calls == ["/t", "/t/1"]


def test_dynamic_routes_match_convert_and_pick_the_method() -> None:
    assert client.get("/items/7").json() == {"item_id": 7}
    assert client.post("/items/7").json() == {"posted": 7}
    assert client.get("/items/abc").status_code == 422
    assert client.get("/nothing/here").status_code == 404


def test_method_mismatch_on_a_dynamic_route_is_405_with_allow() -> None:
    response = client.post("/only-get/x")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


def test_merged_app_returns_responses_and_serializes_values() -> None:
    assert client.get("/plain").json() == {"plain": True}
    assert client.get("/raw").text == "raw"
    assert client.get("/typed").json() == [1, 2, 3]
    assert client.get("/sync").json() == {"sync": True}


def test_merged_app_routes_exceptions_to_handlers() -> None:
    response = client.get("/http-error")
    assert response.status_code == 404
    assert response.json() == {"detail": "nope"}
    response = client.get("/custom-error")
    assert response.status_code == 418
    assert response.json() == {"handled": "boom", "path": "/custom-error"}


def test_route_app_selects_by_parts() -> None:
    plain = route_for("/plain")
    assert route_app(plain, plain.get_route_handler()).__qualname__.startswith(
        "trivial_route_app"
    )
    sync_route = route_for("/sync")
    assert route_app(
        sync_route, sync_route.get_route_handler()
    ).__qualname__.startswith("trivial_request_response")
