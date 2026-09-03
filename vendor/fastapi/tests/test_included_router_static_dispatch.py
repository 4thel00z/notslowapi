from typing import Any
from unittest.mock import patch

import pytest
from notslowapi import APIRouter, FastAPI, Request
from notslowapi.routing import _IncludedRouter
from notslowapi.testclient import TestClient


def build_routes(router: APIRouter | FastAPI) -> None:
    @router.get("/items/{name}")
    async def dynamic_first(name: str) -> dict[str, Any]:
        return {"dynamic": name}

    @router.get("/items/special")
    async def shadowed_static() -> dict[str, Any]:
        return {"static": "special"}

    @router.get("/plain")
    async def plain_get() -> dict[str, Any]:
        return {"method": "GET"}

    @router.post("/plain")
    async def plain_post() -> dict[str, Any]:
        return {"method": "POST"}

    @router.get("/only-get")
    async def only_get() -> dict[str, Any]:
        return {"method": "GET"}

    @router.get("/scope")
    async def scope_keys(request: Request) -> dict[str, Any]:
        fastapi_scope = request.scope.get("notslowapi", {})
        context = fastapi_scope.get("effective_route_context")
        included = fastapi_scope.get("included_router")
        return {
            "endpoint": request.scope["endpoint"].__name__,
            "route_path": request.scope["route"].path,
            "context_path": context.path if context else None,
            "included": included.original_router.prefix if included else None,
            "path_params": request.path_params,
        }


direct = FastAPI()
build_routes(direct)

included = FastAPI()
router = APIRouter(prefix="/api")
build_routes(router)
included.include_router(router)

direct_client = TestClient(direct)
included_client = TestClient(included)

CASES = [
    ("GET", "/items/special"),
    ("GET", "/items/other"),
    ("GET", "/plain"),
    ("POST", "/plain"),
    ("HEAD", "/plain"),
    ("PUT", "/plain"),
    ("GET", "/only-get"),
    ("POST", "/only-get"),
    ("GET", "/missing"),
]


@pytest.mark.parametrize(("method", "path"), CASES)
def test_included_static_routes_answer_like_direct_routes(
    method: str, path: str
) -> None:
    expected = direct_client.request(method, path)
    actual = included_client.request(method, path, headers={})
    actual = included_client.request(method, "/api" + path)
    assert actual.status_code == expected.status_code
    assert actual.content == expected.content
    assert actual.headers.get("allow") == expected.headers.get("allow")


def test_static_included_route_skips_general_matching() -> None:
    with patch.object(
        _IncludedRouter, "_match", autospec=True, side_effect=_IncludedRouter._match
    ) as general:
        response = included_client.get("/api/plain")
    assert response.status_code == 200
    general.assert_not_called()


def test_dynamic_included_route_uses_general_matching() -> None:
    with patch.object(
        _IncludedRouter, "_match", autospec=True, side_effect=_IncludedRouter._match
    ) as general:
        response = included_client.get("/api/items/other")
    assert response.json() == {"dynamic": "other"}
    general.assert_called_once()


def test_method_mismatch_uses_general_matching() -> None:
    with patch.object(
        _IncludedRouter, "_match", autospec=True, side_effect=_IncludedRouter._match
    ) as general:
        response = included_client.post("/api/only-get")
    assert response.status_code == 405
    general.assert_called_once()


def test_scope_carries_route_context_and_included_router() -> None:
    response = included_client.get("/api/scope")
    assert response.json() == {
        "endpoint": "scope_keys",
        "route_path": "/api/scope",
        "context_path": "/api/scope",
        "included": "/api",
        "path_params": {},
    }


def test_nested_include_dispatches_to_innermost_router() -> None:
    app = FastAPI()
    outer = APIRouter(prefix="/outer")
    inner = APIRouter(prefix="/inner")

    @inner.get("/leaf")
    async def leaf(request: Request) -> dict[str, Any]:
        fastapi_scope = request.scope["notslowapi"]
        return {
            "context_path": fastapi_scope["effective_route_context"].path,
            "included": fastapi_scope["included_router"].original_router.prefix,
        }

    outer.include_router(inner)
    app.include_router(outer)
    client = TestClient(app)
    with patch.object(
        _IncludedRouter, "_match", autospec=True, side_effect=_IncludedRouter._match
    ) as general:
        response = client.get("/outer/inner/leaf")
    assert response.json() == {
        "context_path": "/outer/inner/leaf",
        "included": "/inner",
    }
    general.assert_not_called()


def test_mounted_app_keeps_parent_path_params() -> None:
    sub = FastAPI()
    sub_router = APIRouter()

    @sub_router.get("/info")
    async def info(request: Request) -> dict[str, Any]:
        return {"path_params": request.path_params}

    sub.include_router(sub_router)
    app = FastAPI()
    app.mount("/tenants/{tenant}", sub)
    client = TestClient(app)
    response = client.get("/tenants/acme/info")
    assert response.status_code == 200
    assert response.json() == {"path_params": {"tenant": "acme"}}


def test_router_subclass_keeps_general_matching() -> None:
    class CustomRouter(APIRouter):
        def matches(self, scope: dict[str, Any]) -> Any:
            scope["custom_matches"] = True
            return super().matches(scope)

    app = FastAPI()
    custom = CustomRouter(prefix="/custom")

    @custom.get("/route")
    async def route(request: Request) -> dict[str, Any]:
        return {"custom": request.scope.get("custom_matches", False)}

    app.include_router(custom)
    response = TestClient(app).get("/custom/route")
    assert response.json() == {"custom": True}


def test_routes_added_after_first_request_are_served() -> None:
    app = FastAPI()
    live = APIRouter(prefix="/live")

    @live.get("/first")
    async def first() -> dict[str, str]:
        return {"route": "first"}

    app.include_router(live)
    client = TestClient(app)
    assert client.get("/live/first").json() == {"route": "first"}
    assert client.get("/live/second").status_code == 404

    @live.get("/second")
    async def second() -> dict[str, str]:
        return {"route": "second"}

    assert client.get("/live/second").json() == {"route": "second"}
