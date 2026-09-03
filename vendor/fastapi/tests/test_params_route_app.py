from typing import Annotated, Any

import pytest
from notslowapi import Depends, FastAPI, Header, Query
from notslowapi.routing import APIRoute, ParamsHandlerParts, PlainHandlerParts
from notslowapi.testclient import TestClient
from pydantic import BaseModel, Json


class Filter(BaseModel):
    limit: int = 5


def build(app: FastAPI, *dependencies: Any) -> None:
    @app.get("/items/{item_id}", dependencies=list(dependencies))
    async def read_item(
        item_id: int,
        q: str,
        generated: Annotated[str, Query(default_factory=lambda: "made")],
        limit: int = 10,
        maybe: str | None = None,
        word: str = "default",
        item_q: Annotated[str | None, Query(alias="item-q")] = None,
        tags: Annotated[list[str], Query()] = [],  # noqa: B006
    ) -> dict[str, Any]:
        return {
            "item_id": item_id,
            "q": q,
            "limit": limit,
            "maybe": maybe,
            "word": word,
            "generated": generated,
            "item_q": item_q,
            "tags": tags,
        }

    @app.get("/required-list", dependencies=list(dependencies))
    async def required_list(ids: Annotated[list[int], Query()]) -> dict[str, Any]:
        return {"ids": ids}

    @app.get("/empty", dependencies=list(dependencies))
    async def empty(flag: bool = False) -> dict[str, Any]:
        return {"flag": flag}

    @app.get("/json-list", dependencies=list(dependencies))
    async def json_list(
        ids: Annotated[list[int], Json(), Query()] = [],  # noqa: B006
    ) -> dict[str, Any]:
        return {"ids": ids}


async def noop() -> None:
    return None


fast = FastAPI()
build(fast)
generic = FastAPI()
build(generic, Depends(noop))
fast_client = TestClient(fast)
generic_client = TestClient(generic)

CASES = [
    "/items/3?q=x",
    "/items/3?q=x&limit=7&maybe=m&word=w&generated=g&item-q=iq&tags=a&tags=b",
    "/items/3",
    "/items/abc?q=x",
    "/items/3?q=x&limit=abc",
    "/items/3?q=&tags=",
    "/items/3?q=x&limit=",
    "/required-list?ids=1&ids=2",
    "/required-list",
    "/required-list?ids=1&ids=x",
    "/empty",
    "/empty?flag=1",
    "/empty?flag=maybe",
    "/json-list?ids=[1,2]",
    "/json-list",
    "/json-list?ids=nope",
]


@pytest.mark.parametrize("url", CASES)
def test_params_route_app_matches_the_general_solver(url: str) -> None:
    fast_response = fast_client.get(url)
    generic_response = generic_client.get(url)
    assert fast_response.status_code == generic_response.status_code
    assert fast_response.json() == generic_response.json()


def route_for(app: FastAPI, path: str) -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)


def test_only_path_and_query_routes_get_params_parts() -> None:
    for path in ("/items/{item_id}", "/required-list", "/empty"):
        parts = route_for(fast, path).get_route_handler().parts  # type: ignore[attr-defined]
        assert isinstance(parts, ParamsHandlerParts)
        assert route_for(fast, path).app.__qualname__ == "params_route_app.<locals>.app"
    assert not hasattr(
        route_for(generic, "/items/{item_id}").get_route_handler(), "parts"
    ) or not isinstance(
        route_for(generic, "/items/{item_id}").get_route_handler().parts,  # type: ignore[attr-defined]
        ParamsHandlerParts,
    )


def test_header_and_model_params_keep_the_solver() -> None:
    app = FastAPI()

    @app.get("/with-header")
    async def with_header(
        token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return {"token": token}

    @app.get("/with-model")
    async def with_model(filter_query: Annotated[Filter, Query()]) -> dict[str, Any]:
        return {"limit": filter_query.limit}

    for path in ("/with-header", "/with-model"):
        parts = route_for(app, path).get_route_handler().parts  # type: ignore[attr-defined]
        assert isinstance(parts, PlainHandlerParts)
    client = TestClient(app)
    assert client.get("/with-header", headers={"token": "t"}).json() == {"token": "t"}
    assert client.get("/with-model?limit=2").json() == {"limit": 2}


def test_default_factory_runs_per_request() -> None:
    counter = {"n": 0}

    def make() -> str:
        counter["n"] += 1
        return f"v{counter['n']}"

    app = FastAPI()

    @app.get("/gen")
    async def gen(
        value: Annotated[str, Query(default_factory=make)],
    ) -> dict[str, str]:
        return {"value": value}

    client = TestClient(app)
    assert client.get("/gen").json() == {"value": "v1"}
    assert client.get("/gen").json() == {"value": "v2"}
    assert client.get("/gen?value=given").json() == {"value": "given"}
