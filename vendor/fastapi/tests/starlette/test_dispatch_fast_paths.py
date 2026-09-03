from typing import Any

import anyio
from notslowapi.starlette.applications import Starlette
from notslowapi.starlette.background import BackgroundTask
from notslowapi.starlette.requests import Request
from notslowapi.starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from notslowapi.starlette.routing import Route
from notslowapi.starlette.testclient import TestClient

runs: list[str] = []


async def item(request: Request) -> JSONResponse:
    return JSONResponse({"item_id": request.path_params["item_id"], "q": request.query_params.get("q")})


async def hello(request: Request) -> PlainTextResponse:
    return PlainTextResponse("hello")


async def with_task(request: Request) -> JSONResponse:
    return JSONResponse({"task": True}, background=BackgroundTask(runs.append, "ran"))


async def stream(request: Request) -> StreamingResponse:
    async def parts() -> Any:
        yield b"a"
        yield b"b"

    return StreamingResponse(parts(), media_type="text/plain")


class TracingRoute(Route):
    async def handle(self, scope: Any, receive: Any, send: Any) -> None:
        runs.append(f"handle {scope['path']}")
        await super().handle(scope, receive, send)


app = Starlette(
    routes=[
        Route("/items/{item_id:int}", item),
        Route("/hello", hello, methods=["GET"]),
        Route("/task", with_task),
        Route("/stream", stream),
        TracingRoute("/traced/{name}", hello),
        TracingRoute("/traced", hello),
    ]
)
client = TestClient(app)


def test_dynamic_routes_match_convert_and_check_methods() -> None:
    assert client.get("/items/7?q=x").json() == {"item_id": 7, "q": "x"}
    assert client.get("/items/abc").status_code == 404
    response = client.post("/hello")
    assert response.status_code == 405
    assert set(response.headers["allow"].split(", ")) == {"GET", "HEAD"}
    assert client.get("/missing").status_code == 404


def test_background_and_streaming_responses_keep_their_paths() -> None:
    runs.clear()
    assert client.get("/task").json() == {"task": True}
    assert runs == ["ran"]
    assert client.get("/stream").text == "ab"


def test_route_subclass_handle_is_still_called() -> None:
    runs.clear()
    assert client.get("/traced/x").text == "hello"
    assert client.get("/traced").text == "hello"
    assert runs == ["handle /traced/x", "handle /traced"]


async def collect(path: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"q=x",
        "headers": [],
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "http_version": "1.1",
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


def test_direct_send_matches_response_call() -> None:
    direct = anyio.run(collect, "/items/3")
    reference: list[dict[str, Any]] = []

    async def reference_send(message: dict[str, Any]) -> None:
        reference.append(message)

    async def reference_response() -> None:
        await JSONResponse({"item_id": 3, "q": "x"})({"type": "http"}, None, reference_send)  # type: ignore[arg-type]

    anyio.run(reference_response)
    assert direct == reference


def test_json_response_headers_match_the_generic_constructor() -> None:
    fast = JSONResponse({"a": 1})
    generic = Response(JSONResponse.render(fast, {"a": 1}), media_type="application/json")
    assert fast.raw_headers == generic.raw_headers
    assert fast.body == generic.body
    assert JSONResponse(None, status_code=204).raw_headers == [(b"content-type", b"application/json")]

    class Problem(JSONResponse):
        media_type = "application/problem+json"

    assert (
        Problem({"a": 1}).raw_headers
        == Response(b"x" * len(Problem({"a": 1}).body), media_type="application/problem+json").raw_headers
    )
    custom = JSONResponse({"a": 1}, headers={"x-extra": "1"})
    assert (b"x-extra", b"1") in custom.raw_headers
    assert (b"content-type", b"application/json") in custom.raw_headers
    assert JSONResponse({"a": 1}, media_type="application/problem+json").raw_headers[-1] == (
        b"content-type",
        b"application/problem+json",
    )
