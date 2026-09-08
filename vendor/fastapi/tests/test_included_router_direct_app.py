from typing import Any
from unittest.mock import patch

from notslowapi import APIRouter, FastAPI, Request
from notslowapi.routing import APIRoute
from notslowapi.starlette.routing import RouteList, RoutesGeneration
from notslowapi.testclient import TestClient

app = FastAPI()
router = APIRouter(prefix="/api")


@router.get("/plain")
async def plain() -> dict[str, str]:
    return {"route": "plain"}


@router.get("/items/{name}")
async def dynamic(name: str) -> dict[str, str]:
    return {"name": name}


@router.get("/scope")
async def scope_keys(request: Request) -> dict[str, Any]:
    fastapi_scope = request.scope["notslowapi"]
    return {
        "endpoint": request.scope["endpoint"].__name__,
        "route_path": request.scope["route"].path,
        "context_path": fastapi_scope["effective_route_context"].path,
        "included": fastapi_scope["included_router"].original_router.prefix,
    }


app.include_router(router)
client = TestClient(app)


def test_static_included_route_skips_the_handle_frame() -> None:
    with patch.object(
        APIRoute, "handle", autospec=True, side_effect=APIRoute.handle
    ) as handle:
        response = client.get("/api/plain")
    assert response.json() == {"route": "plain"}
    handle.assert_not_called()


def test_dynamic_included_route_still_goes_through_handle() -> None:
    with patch.object(
        APIRoute, "handle", autospec=True, side_effect=APIRoute.handle
    ) as handle:
        response = client.get("/api/items/x")
    assert response.json() == {"name": "x"}
    handle.assert_called_once()


def test_direct_dispatch_fills_the_scope_like_handle_does() -> None:
    assert client.get("/api/scope").json() == {
        "endpoint": "scope_keys",
        "route_path": "/api/scope",
        "context_path": "/api/scope",
        "included": "/api",
    }


def test_method_mismatch_on_a_static_included_route_is_a_405() -> None:
    response = client.post("/api/plain")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


def test_route_list_mutations_advance_the_generation() -> None:
    routes = RouteList()
    before = RoutesGeneration.value
    routes.append(APIRoute("/a", plain))
    assert RoutesGeneration.value == before + 1
    routes.pop()
    assert RoutesGeneration.value == before + 2
    other = APIRouter()
    other.add_api_route("/b", plain)
    assert RoutesGeneration.value > before + 2


def test_routes_added_after_requests_were_served_are_reachable() -> None:
    late_app = FastAPI()
    late_router = APIRouter(prefix="/late")

    @late_router.get("/first")
    async def first() -> dict[str, int]:
        return {"n": 1}

    late_app.include_router(late_router)
    late_client = TestClient(late_app)
    assert late_client.get("/late/first").json() == {"n": 1}
    assert late_client.get("/late/second").status_code == 404

    @late_router.get("/second")
    async def second() -> dict[str, int]:
        return {"n": 2}

    assert late_client.get("/late/second").json() == {"n": 2}
    late_router.routes.append(APIRoute("/late/third", first))
    assert late_client.get("/late/third").json() == {"n": 1}
