from typing import Any

from notslowapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from notslowapi.responses import JSONResponse, PlainTextResponse
from notslowapi.routing import (
    APIRoute,
    ParamsHandlerParts,
    PlainHandlerParts,
    TrivialHandlerParts,
    route_app,
)
from notslowapi.starlette.background import BackgroundTask
from notslowapi.testclient import TestClient
from pydantic import BaseModel


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
    assert isinstance(
        getattr(route_for("/items/{item_id}").get_route_handler(), "parts", None),
        ParamsHandlerParts,
    )
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


class Item(BaseModel):
    name: str
    price: float


status_app = FastAPI()
task_runs: list[str] = []


@status_app.post("/created", status_code=201)
async def created() -> dict[str, str]:
    return {"state": "created"}


@status_app.delete("/gone", status_code=204)
async def gone() -> None:
    return None


@status_app.get("/wrong-type")
async def wrong_type() -> Item:
    return {"name": "widget"}  # type: ignore[return-value]


@status_app.get("/untyped")
async def untyped():  # type: ignore[no-untyped-def]
    return {"untyped": True, "nested": {"n": [1, 2]}}


@status_app.get("/with-task")
async def with_task() -> Response:
    return JSONResponse(
        {"task": True}, background=BackgroundTask(task_runs.append, "ran")
    )


@status_app.get("/model")
async def model() -> Item:
    return Item(name="widget", price=1.5)


status_client = TestClient(status_app, raise_server_exceptions=False)


def test_status_code_and_empty_body_decisions_are_precomputed() -> None:
    created_response = status_client.post("/created")
    assert created_response.status_code == 201
    assert created_response.json() == {"state": "created"}
    assert created_response.headers["content-length"] == str(
        len(created_response.content)
    )
    gone_response = status_client.delete("/gone")
    assert gone_response.status_code == 204
    assert gone_response.content == b""
    assert "content-length" not in gone_response.headers


def test_response_validation_error_still_reports_the_endpoint() -> None:
    response = status_client.get("/wrong-type")
    assert response.status_code == 500
    with TestClient(status_app) as raising:
        try:
            raising.get("/wrong-type")
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            assert "GET /wrong-type" in text
            assert "price" in text
        else:
            raise AssertionError("expected a ResponseValidationError")


def test_untyped_endpoint_uses_the_json_response_class() -> None:
    response = status_client.get("/untyped")
    assert response.status_code == 200
    assert response.json() == {"untyped": True, "nested": {"n": [1, 2]}}
    assert response.headers["content-type"] == "application/json"


def test_returned_response_with_background_task_runs_it() -> None:
    response = status_client.get("/with-task")
    assert response.json() == {"task": True}
    assert task_runs == ["ran"]


def test_direct_send_emits_the_same_messages_as_a_response() -> None:
    import anyio

    async def collect(path: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
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

        await status_app(scope, receive, send)
        return messages

    direct = anyio.run(collect, "/model")
    body = Item(name="widget", price=1.5).model_dump_json().encode()
    reference: list[dict[str, Any]] = []

    async def reference_send(message: dict[str, Any]) -> None:
        reference.append(message)

    async def run_reference() -> None:
        response = Response(body, media_type="application/json")
        await response({"type": "http"}, None, reference_send)  # type: ignore[arg-type]

    anyio.run(run_reference)
    assert direct == reference


plain_app = FastAPI()
plain_tasks: list[str] = []


@plain_app.get("/items/{item_id}")
async def plain_item(item_id: int, q: str | None = None) -> dict[str, Any]:
    return {"item_id": item_id, "q": q}


@plain_app.get("/typed/{item_id}")
async def plain_typed(item_id: int) -> Item:
    return Item(name=f"item-{item_id}", price=float(item_id))


@plain_app.get("/with-response/{item_id}")
async def plain_with_response(item_id: int, response: Response) -> dict[str, int]:
    response.headers["x-item"] = str(item_id)
    response.status_code = 202
    return {"item_id": item_id}


@plain_app.get("/with-tasks/{name}")
async def plain_with_tasks(name: str, tasks: BackgroundTasks) -> dict[str, str]:
    tasks.add_task(plain_tasks.append, name)
    return {"name": name}


@plain_app.get("/sync/{item_id}")
def plain_sync(item_id: int) -> dict[str, int]:
    return {"item_id": item_id}


plain_client = TestClient(plain_app)


def plain_route(path: str) -> APIRoute:
    return next(
        r for r in plain_app.routes if isinstance(r, APIRoute) and r.path == path
    )


def test_parameter_endpoints_get_the_params_or_plain_route_app() -> None:
    handler = plain_route("/items/{item_id}").get_route_handler()
    assert isinstance(getattr(handler, "parts", None), ParamsHandlerParts)
    assert (
        plain_route("/items/{item_id}").app.__qualname__
        == "params_route_app.<locals>.app"
    )
    with_response = plain_route("/with-response/{item_id}").get_route_handler()
    assert isinstance(getattr(with_response, "parts", None), PlainHandlerParts)
    assert (
        plain_route("/with-response/{item_id}").app.__qualname__
        == "plain_route_app.<locals>.app"
    )
    assert (
        plain_route("/sync/{item_id}").app.__qualname__
        == "trivial_request_response.<locals>.app"
    )


def test_plain_route_app_solves_validates_and_serializes() -> None:
    assert plain_client.get("/items/3?q=x").json() == {"item_id": 3, "q": "x"}
    assert plain_client.get("/typed/2").json() == {"name": "item-2", "price": 2.0}
    response = plain_client.get("/items/abc")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "item_id"]
    assert plain_client.get("/sync/5").json() == {"item_id": 5}


def test_plain_route_app_keeps_response_and_background_parameters() -> None:
    response = plain_client.get("/with-response/9")
    assert response.status_code == 202
    assert response.headers["x-item"] == "9"
    assert response.json() == {"item_id": 9}
    assert plain_client.get("/with-tasks/job").json() == {"name": "job"}
    assert plain_tasks == ["job"]


def test_plain_direct_send_emits_the_same_messages_as_a_response() -> None:
    import anyio

    async def collect() -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/typed/4",
            "raw_path": b"/typed/4",
            "query_string": b"",
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

        await plain_app(scope, receive, send)
        return messages

    direct = anyio.run(collect)
    body = Item(name="item-4", price=4.0).model_dump_json().encode()
    reference: list[dict[str, Any]] = []

    async def reference_send(message: dict[str, Any]) -> None:
        reference.append(message)

    async def run_reference() -> None:
        await Response(body, media_type="application/json")(
            {"type": "http"}, None, reference_send
        )  # type: ignore[arg-type]

    anyio.run(run_reference)
    assert direct == reference


untyped_app = FastAPI()


@untyped_app.get("/dict")
async def untyped_dict():  # type: ignore[no-untyped-def]
    return {"a": 1, "b": [1, 2.5, "x", None], "c": {"d": True}}


@untyped_app.get("/none")
async def untyped_none():  # type: ignore[no-untyped-def]
    return None


@untyped_app.get("/text", response_class=PlainTextResponse)
async def untyped_text():  # type: ignore[no-untyped-def]
    return "plain text"


@untyped_app.get("/params/{n}")
async def untyped_params(n: int):  # type: ignore[no-untyped-def]
    return {"n": n}


untyped_client = TestClient(untyped_app)


def test_untyped_returns_take_the_direct_send_path() -> None:
    for path in ("/dict", "/none", "/params/{n}"):
        route = next(
            r for r in untyped_app.routes if isinstance(r, APIRoute) and r.path == path
        )
        assert route.get_route_handler().parts.serialize is not None  # type: ignore[attr-defined]
    text_route = next(
        r for r in untyped_app.routes if isinstance(r, APIRoute) and r.path == "/text"
    )
    assert text_route.get_route_handler().parts.serialize is None  # type: ignore[attr-defined]


def test_untyped_bodies_match_json_response() -> None:
    import anyio

    async def collect(path: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
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

        await untyped_app(scope, receive, send)
        return messages

    async def reference(content: Any) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await JSONResponse(content)({"type": "http"}, None, send)  # type: ignore[arg-type]
        return messages

    assert anyio.run(collect, "/dict") == anyio.run(
        reference, {"a": 1, "b": [1, 2.5, "x", None], "c": {"d": True}}
    )
    assert anyio.run(collect, "/none") == anyio.run(reference, None)
    assert anyio.run(collect, "/params/7") == anyio.run(reference, {"n": 7})
    assert untyped_client.get("/text").text == "plain text"
    assert untyped_client.get("/text").headers["content-type"].startswith("text/plain")
