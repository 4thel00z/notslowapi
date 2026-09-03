from typing import Any
from unittest.mock import patch

from notslowapi import APIRouter, FastAPI
from notslowapi.routing import APIRoute
from notslowapi.starlette.applications import Starlette
from notslowapi.starlette.requests import Request
from notslowapi.starlette.responses import JSONResponse, PlainTextResponse
from notslowapi.starlette.routing import Mount, Route, build_route_index
from notslowapi.testclient import TestClient


def build_routes(target: FastAPI | APIRouter) -> None:
    @target.get("/p0/{item_id}")
    async def p0(item_id: int) -> dict[str, Any]:
        return {"p0": item_id}

    @target.get("/p1/{item_id}")
    async def p1(item_id: int) -> dict[str, Any]:
        return {"p1": item_id}

    @target.get("/files/{name:path}")
    async def files(name: str) -> dict[str, Any]:
        return {"file": name}

    @target.get("/r/{code}")
    async def dynamic_r(code: str) -> dict[str, Any]:
        return {"dynamic": code}

    @target.get("/r/1")
    async def static_r1() -> dict[str, Any]:
        return {"static": "r1"}

    @target.get("/filesystem")
    async def filesystem() -> dict[str, Any]:
        return {"static": "filesystem"}

    @target.get("/plain")
    async def plain() -> dict[str, Any]:
        return {"static": "plain"}


direct = FastAPI()
build_routes(direct)
direct_client = TestClient(direct)

included = FastAPI()
router = APIRouter()
build_routes(router)
included.include_router(router)
included_client = TestClient(included)


def test_earlier_dynamic_route_with_matching_prefix_still_wins() -> None:
    assert direct_client.get("/r/1").json() == {"dynamic": "1"}
    assert included_client.get("/r/1").json() == {"dynamic": "1"}


def test_static_route_is_served_when_dynamic_prefixes_cannot_match() -> None:
    assert direct_client.get("/plain").json() == {"static": "plain"}
    assert direct_client.get("/filesystem").json() == {"static": "filesystem"}
    assert included_client.get("/plain").json() == {"static": "plain"}
    assert included_client.get("/filesystem").json() == {"static": "filesystem"}


def test_dynamic_routes_still_match_their_own_paths() -> None:
    assert direct_client.get("/p1/7").json() == {"p1": 7}
    assert direct_client.get("/files/a/b.txt").json() == {"file": "a/b.txt"}
    assert included_client.get("/p0/3").json() == {"p0": 3}
    assert included_client.get("/files/x").json() == {"file": "x"}


def test_direct_static_hit_does_not_regex_test_unrelated_dynamic_routes() -> None:
    with patch.object(
        APIRoute, "matches", autospec=True, side_effect=APIRoute.matches
    ) as matches:
        response = direct_client.get("/plain")
    assert response.status_code == 200
    matches.assert_not_called()


def test_included_static_hit_tests_at_most_the_route_itself() -> None:
    with patch.object(
        APIRoute, "matches", autospec=True, side_effect=APIRoute.matches
    ) as matches:
        response = included_client.get("/plain")
    assert response.status_code == 200
    assert matches.call_count <= 1


def test_catch_all_declared_first_still_wins() -> None:
    app = FastAPI()

    @app.get("/{whole}")
    async def whole(whole: str) -> dict[str, Any]:
        return {"whole": whole}

    @app.get("/static")
    async def static() -> dict[str, Any]:
        return {"static": True}

    assert TestClient(app).get("/static").json() == {"whole": "static"}


def test_mount_declared_first_keeps_priority() -> None:
    async def mounted(scope: Any, receive: Any, send: Any) -> None:
        await PlainTextResponse("mounted")(scope, receive, send)

    async def route_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("route")

    app = Starlette(
        routes=[
            Mount("/r", app=mounted),
            Route("/r/x", route_endpoint),
            Route("/other", route_endpoint),
        ]
    )
    client = TestClient(app)
    assert client.get("/r/x").text == "mounted"
    assert client.get("/other").text == "route"


def test_starlette_static_hit_skips_unrelated_dynamic_routes() -> None:
    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"path": request.url.path})

    app = Starlette(
        routes=[
            Route("/p/{item}", endpoint),
            Route("/q/{item}", endpoint),
            Route("/r", endpoint),
        ]
    )
    client = TestClient(app)
    with patch.object(
        Route, "matches", autospec=True, side_effect=Route.matches
    ) as matches:
        response = client.get("/r")
    assert response.json() == {"path": "/r"}
    matches.assert_not_called()
    assert client.get("/p/1").json() == {"path": "/p/1"}


def test_build_route_index_prunes_by_literal_prefix() -> None:
    async def endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    p = Route("/p/{x}", endpoint)
    r = Route("/r", endpoint)
    r_dyn = Route("/r{suffix}", endpoint)
    everything = Route("/{all}", endpoint)
    mount = Mount("/m", app=endpoint)
    index, rest = build_route_index([p, r, r_dyn, everything, mount])
    assert index == {"/r": [r, r_dyn, everything, mount]}
    assert rest == [p, r_dyn, everything, mount]
