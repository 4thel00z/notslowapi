from typing import Annotated, Any

from notslowapi import Cookie, Depends, FastAPI, Header, Query
from notslowapi.dependencies.utils import compile_param_plan, dependant_param_plan
from notslowapi.routing import APIRoute
from notslowapi.testclient import TestClient
from pydantic import BaseModel


class Filter(BaseModel):
    limit: int = 5
    order: str = "asc"


def headers_and_cookies(
    x_token: Annotated[str, Header()],
    x_tags: Annotated[list[str], Header()] = [],  # noqa: B006
    session: Annotated[str | None, Cookie()] = None,
    accept_language: Annotated[str, Header()] = "en",
) -> dict[str, Any]:
    return {
        "token": x_token,
        "tags": x_tags,
        "session": session,
        "language": accept_language,
    }


def filters(filter_query: Annotated[Filter, Query()]) -> Filter:
    return filter_query


app = FastAPI()


@app.get("/items/{item_id}")
async def read_item(
    item_id: int,
    meta: Annotated[dict[str, Any], Depends(headers_and_cookies)],
    filter_query: Annotated[Filter, Depends(filters)],
    q: str | None = None,
) -> dict[str, Any]:
    return {"item_id": item_id, "q": q, **meta, "filter": filter_query.model_dump()}


client = TestClient(app)


def route() -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute))


def test_plan_lists_every_location_in_solver_order() -> None:
    dependant = route().dependant
    own = dependant_param_plan(dependant)
    assert [(s[0], s[2], s[3], s[6]) for s in own.specs] == [
        ("item_id", "path", False, False),
        ("q", "query", False, False),
    ]
    assert (own.needs_path, own.needs_query, own.needs_headers, own.needs_cookies) == (
        True,
        True,
        False,
        False,
    )
    meta = next(d for d in dependant.dependencies if d.name == "meta")
    meta_plan = compile_param_plan(meta)
    assert [(s[0], s[1], s[2], s[3]) for s in meta_plan.specs] == [
        ("x_token", "x-token", "header", False),
        ("x_tags", "x-tags", "header", True),
        ("accept_language", "accept-language", "header", False),
        ("session", "session", "cookie", False),
    ]
    assert meta_plan.needs_headers and meta_plan.needs_cookies
    filters_plan = compile_param_plan(
        next(d for d in dependant.dependencies if d.name == "filter_query")
    )
    assert [(s[0], s[2], s[6]) for s in filters_plan.specs] == [
        ("filter_query", "query", True)
    ]


def test_headers_cookies_and_model_params_resolve_through_the_plan() -> None:
    with TestClient(app) as cookie_client:
        cookie_client.cookies.set("session", "s1")
        response = cookie_client.get(
            "/items/3?q=x&limit=2&order=desc",
            headers=[
                ("x-token", "t"),
                ("x-tags", "a"),
                ("x-tags", "b"),
                ("accept-language", "de"),
            ],
        )
    assert response.status_code == 200
    assert response.json() == {
        "item_id": 3,
        "q": "x",
        "token": "t",
        "tags": ["a", "b"],
        "session": "s1",
        "language": "de",
        "filter": {"limit": 2, "order": "desc"},
    }


def test_defaults_and_missing_values_match_the_solver_rules() -> None:
    response = client.get("/items/3", headers={"x-token": "t"})
    assert response.json() == {
        "item_id": 3,
        "q": None,
        "token": "t",
        "tags": [],
        "session": None,
        "language": "en",
        "filter": {"limit": 5, "order": "asc"},
    }
    missing = client.get("/items/3")
    assert missing.status_code == 422
    assert missing.json()["detail"] == [
        {
            "type": "missing",
            "loc": ["header", "x-token"],
            "msg": "Field required",
            "input": None,
        }
    ]
    bad = client.get("/items/3?limit=x", headers={"x-token": "t"})
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"] == ["query", "limit"]
