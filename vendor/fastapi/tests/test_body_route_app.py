from typing import Any

import anyio
from notslowapi import FastAPI, Response
from notslowapi.responses import PlainTextResponse
from notslowapi.routing import APIRoute, BodyHandlerParts
from notslowapi.testclient import TestClient
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    price: float


app = FastAPI()


@app.post("/fast")
async def fast(item: Item) -> Item:
    return item


@app.post("/general")
async def general(item: Item, q: str | None = None) -> Item:
    return item


@app.post("/raw")
async def raw(item: Item) -> Response:
    return PlainTextResponse(item.name)


@app.post("/text", response_class=PlainTextResponse)
async def text(item: Item):  # type: ignore[no-untyped-def]
    return item.name


@app.post("/sync")
def sync(item: Item) -> Item:
    return item


@app.post("/created", status_code=201)
async def created(item: Item) -> Item:
    return item


client = TestClient(app)
VALID = b'{"name": "widget", "price": 9.99}'
JSON = {"content-type": "application/json"}


def route_for(path: str) -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)


def test_lone_json_body_coroutine_routes_get_the_body_route_app() -> None:
    assert isinstance(route_for("/fast").get_route_handler().parts, BodyHandlerParts)  # type: ignore[attr-defined]
    assert route_for("/fast").app.__qualname__ == "body_route_app.<locals>.app"
    assert (
        route_for("/sync").app.__qualname__ == "trivial_request_response.<locals>.app"
    )
    assert (
        route_for("/general").app.__qualname__ == "params_route_app.<locals>.app"
        or route_for("/general").app.__qualname__ != "body_route_app.<locals>.app"
    )


def test_body_route_app_matches_the_general_handler() -> None:
    cases = [
        (VALID, JSON),
        (b"", JSON),
        (b"null", JSON),
        (b'{"name": "widget", "price": 9.99', JSON),
        (b'{"name": "widget"}', JSON),
        (b'{"name": "widget", "price": "free"}', JSON),
        (VALID, {"content-type": "text/plain"}),
        (VALID, {}),
        (b"\xef\xbb\xbf" + VALID, JSON),
        (VALID, {"content-type": "application/vnd.api+json"}),
    ]
    for content, headers in cases:
        fast_response = client.post("/fast", content=content, headers=headers)
        general_response = client.post("/general", content=content, headers=headers)
        assert (fast_response.status_code, fast_response.json()) == (
            general_response.status_code,
            general_response.json(),
        ), (content, headers)


def test_other_return_shapes_still_work() -> None:
    assert client.post("/raw", content=VALID, headers=JSON).text == "widget"
    assert client.post("/text", content=VALID, headers=JSON).text == "widget"
    assert client.post("/sync", content=VALID, headers=JSON).json() == {
        "name": "widget",
        "price": 9.99,
    }
    created_response = client.post("/created", content=VALID, headers=JSON)
    assert created_response.status_code == 201
    assert created_response.headers["content-length"] == str(
        len(created_response.content)
    )


async def run(
    path: str, messages: list[dict[str, Any]], headers: list[tuple[bytes, bytes]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pending = list(messages)
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "http_version": "1.1",
    }

    async def receive() -> dict[str, Any]:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        out.append(message)

    await app(scope, receive, send)
    return out


def test_chunked_body_and_direct_send_messages() -> None:
    chunks = [
        {"type": "http.request", "body": VALID[:10], "more_body": True},
        {"type": "http.request", "body": VALID[10:], "more_body": False},
    ]
    headers = [(b"content-type", b"application/json")]
    direct = anyio.run(run, "/fast", chunks, headers)
    reference: list[dict[str, Any]] = []

    async def reference_send(message: dict[str, Any]) -> None:
        reference.append(message)

    async def reference_response() -> None:
        body = Item(name="widget", price=9.99).model_dump_json().encode()
        await Response(body, media_type="application/json")(
            {"type": "http"}, None, reference_send
        )  # type: ignore[arg-type]

    anyio.run(reference_response)
    assert direct == reference


def test_disconnect_while_reading_matches_the_general_handler() -> None:
    disconnect = [
        {"type": "http.request", "body": VALID[:5], "more_body": True},
        {"type": "http.disconnect"},
    ]
    headers = [(b"content-type", b"application/json")]
    fast_messages = anyio.run(run, "/fast", disconnect, headers)
    general_messages = anyio.run(run, "/general", disconnect, headers)
    assert fast_messages == general_messages
    assert fast_messages[0]["status"] == 400
