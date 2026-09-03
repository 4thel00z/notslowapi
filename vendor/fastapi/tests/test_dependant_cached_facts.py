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
