from typing import Annotated, Any

from notslowapi import Depends, FastAPI, Header, Response
from notslowapi.dependencies.models import (
    _get_cache_key,
    dependant_cache_key,
    dependant_call_kinds,
    dependant_needs_response,
)
from notslowapi.dependencies.utils import get_dependant
from notslowapi.routing import APIRoute
from notslowapi.testclient import TestClient


async def pagination(skip: int = 0, limit: int = 20) -> dict[str, int]:
    return {"skip": skip, "limit": limit}


def current_user(x_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    return {"user": x_token or "anonymous"}


def stamp(response: Response) -> str:
    response.headers["x-stamp"] = "yes"
    return "stamped"


def counting_gen() -> Any:
    calls.append("enter")
    yield "gen"
    calls.append("exit")


calls: list[str] = []
app = FastAPI()


@app.get("/items/{item_id}")
async def read_item(
    item_id: int,
    page: Annotated[dict[str, int], Depends(pagination)],
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> dict[str, Any]:
    return {"item_id": item_id, **page, **user}


@app.get("/stamped")
async def stamped(mark: Annotated[str, Depends(stamp)]) -> dict[str, str]:
    return {"mark": mark}


@app.get("/gen")
async def with_gen(value: Annotated[str, Depends(counting_gen)]) -> dict[str, str]:
    return {"value": value}


client = TestClient(app)


def route_for(path: str) -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)


def test_cached_facts_match_the_computed_ones() -> None:
    dependant = route_for("/items/{item_id}").dependant
    for sub in dependant.dependencies:
        assert dependant_cache_key(sub) == _get_cache_key(dependant=sub)
        assert sub.cache_key == _get_cache_key(dependant=sub)
    kinds = {sub.name: dependant_call_kinds(sub) for sub in dependant.dependencies}
    assert kinds == {"page": (False, True), "user": (False, False)}
    assert dependant_needs_response(dependant) is False
    assert dependant_needs_response(route_for("/stamped").dependant) is True
    gen_dependant = route_for("/gen").dependant.dependencies[0]
    assert dependant_call_kinds(gen_dependant) == (True, False)


def test_dependencies_resolve_with_and_without_a_response_parameter() -> None:
    response = client.get("/items/3?limit=2", headers={"x-token": "t"})
    assert response.json() == {"item_id": 3, "skip": 0, "limit": 2, "user": "t"}
    assert "x-stamp" not in response.headers
    stamped_response = client.get("/stamped")
    assert stamped_response.json() == {"mark": "stamped"}
    assert stamped_response.headers["x-stamp"] == "yes"


def test_generator_dependency_still_runs_through_the_exit_stack() -> None:
    calls.clear()
    assert client.get("/gen").json() == {"value": "gen"}
    assert calls == ["enter", "exit"]


def test_overrides_apply_after_the_facts_were_cached() -> None:
    assert client.get("/items/1").json()["user"] == "anonymous"

    async def other_user() -> dict[str, Any]:
        return {"user": "override"}

    app.dependency_overrides[current_user] = other_user
    try:
        assert client.get("/items/1").json()["user"] == "override"
    finally:
        app.dependency_overrides.clear()
    assert client.get("/items/1").json()["user"] == "anonymous"


def test_fresh_dependant_computes_lazily() -> None:
    dependant = get_dependant(path="/x", call=pagination)
    assert dependant.cache_key is None
    assert dependant.call_kinds is None
    assert dependant.needs_response is None
    assert dependant_call_kinds(dependant) == (False, True)
    assert dependant.call_kinds == (False, True)


from notslowapi.dependencies.models import dependant_is_leaf  # noqa: E402


def test_leaf_classification() -> None:
    dependant = route_for("/items/{item_id}").dependant
    leaves = {sub.name: dependant_is_leaf(sub) for sub in dependant.dependencies}
    assert leaves == {"page": True, "user": True}
    assert dependant_is_leaf(route_for("/stamped").dependant.dependencies[0]) is False
    assert dependant_is_leaf(route_for("/gen").dependant.dependencies[0]) is True


leaf_app = FastAPI()
leaf_calls: list[str] = []


def shared_leaf(tag: str = "none") -> str:
    leaf_calls.append(tag)
    return tag


def uncached_leaf(n: int = 1) -> int:
    leaf_calls.append(f"uncached-{n}")
    return n


async def parent(shared: Annotated[str, Depends(shared_leaf)]) -> str:
    return f"parent:{shared}"


@leaf_app.get("/leaves")
async def leaves(
    shared: Annotated[str, Depends(shared_leaf)],
    via_parent: Annotated[str, Depends(parent)],
    first: Annotated[int, Depends(uncached_leaf, use_cache=False)],
    second: Annotated[int, Depends(uncached_leaf, use_cache=False)],
) -> dict[str, Any]:
    return {
        "shared": shared,
        "via_parent": via_parent,
        "first": first,
        "second": second,
    }


leaf_client = TestClient(leaf_app)


def test_inlined_leaves_keep_caching_and_error_semantics() -> None:
    leaf_calls.clear()
    response = leaf_client.get("/leaves?tag=x&n=2")
    assert response.json() == {
        "shared": "x",
        "via_parent": "parent:x",
        "first": 2,
        "second": 2,
    }
    assert leaf_calls == ["x", "uncached-2", "uncached-2"]
    bad = leaf_client.get("/leaves?n=abc")
    assert bad.status_code == 422
    assert [e["loc"] for e in bad.json()["detail"]] == [["query", "n"], ["query", "n"]]
