from contextlib import AsyncExitStack
from typing import Annotated, Any

import anyio
import pytest
from notslowapi import Cookie, Depends, FastAPI, Header, Request, Response
from notslowapi.dependencies.models import Dependant
from notslowapi.dependencies.utils import (
    compile_solve_plan,
    get_dependant,
    get_parameterless_sub_dependant,
    run_solve_plan,
    solve_dependencies,
)
from notslowapi.routing import APIRoute
from notslowapi.testclient import TestClient

calls: list[str] = []


def shared(tag: str) -> str:
    calls.append(f"shared:{tag}")
    return tag


async def via_parent(inner: Annotated[str, Depends(shared)]) -> str:
    calls.append("via_parent")
    return f"parent:{inner}"


async def uses_shared(
    first: Annotated[str, Depends(via_parent)],
    second: Annotated[str, Depends(shared)],
) -> dict[str, str]:
    return {"first": first, "second": second}


def counter() -> int:
    calls.append("counter")
    return len(calls)


async def uses_uncached(
    first: Annotated[int, Depends(counter, use_cache=False)],
    second: Annotated[int, Depends(counter, use_cache=False)],
    third: Annotated[int, Depends(counter)],
) -> dict[str, int]:
    return {"first": first, "second": second, "third": third}


async def user(x_token: Annotated[str | None, Header()] = None) -> str:
    calls.append("user")
    return x_token or "anonymous"


async def access(who: Annotated[str, Depends(user)], limit: int = 10) -> dict[str, Any]:
    calls.append("access")
    return {"who": who, "limit": limit}


async def uses_access(
    grant: Annotated[dict[str, Any], Depends(access)],
    who: Annotated[str, Depends(user)],
    item_id: int,
) -> dict[str, Any]:
    return {**grant, "again": who, "item_id": item_id}


def audit() -> None:
    calls.append("audit")


async def audited(q: str | None = None) -> dict[str, str | None]:
    return {"q": q}


async def with_cookie(
    x_required: Annotated[str, Header()],
    session: Annotated[str | None, Cookie()] = None,
) -> dict[str, str | None]:
    calls.append("with_cookie")
    return {"required": x_required, "session": session}


async def uses_cookie(
    value: Annotated[dict[str, str | None], Depends(with_cookie)],
) -> dict[str, Any]:
    return value


def dependant_for(endpoint: Any, path: str = "/") -> Dependant:
    return get_dependant(path=path, call=endpoint)


def audited_dependant() -> Dependant:
    dependant = dependant_for(audited)
    dependant.dependencies.insert(
        0, get_parameterless_sub_dependant(depends=Depends(audit), path="/")
    )
    return dependant


def make_scope(
    path: str = "/",
    query: str = "",
    headers: dict[str, str] | None = None,
    path_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query.encode(),
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in (headers or {}).items()
        ],
        "path_params": path_params or {},
    }


async def generic_solve(
    dependant: Dependant, scope: dict[str, Any]
) -> tuple[dict[str, Any], list[Any]]:
    request = Request(scope)
    async with AsyncExitStack() as stack:
        solved = await solve_dependencies(
            request=request,
            dependant=dependant,
            async_exit_stack=stack,
            embed_body_fields=False,
        )
    return solved.values, solved.errors


async def planned_solve(
    dependant: Dependant, scope: dict[str, Any]
) -> tuple[dict[str, Any], list[Any]]:
    plan = compile_solve_plan(dependant)
    if plan is None:
        raise AssertionError("expected a plan")
    cookies = Request(scope).cookies if plan.needs_cookies else None
    return await run_solve_plan(plan, scope, cookies)


CASES: list[tuple[str, Dependant, dict[str, Any]]] = [
    ("shared-ok", dependant_for(uses_shared), make_scope(query="tag=x")),
    ("shared-missing", dependant_for(uses_shared), make_scope()),
    ("uncached", dependant_for(uses_uncached), make_scope()),
    (
        "deep-ok",
        dependant_for(uses_access, "/items/{item_id}"),
        make_scope(
            path="/items/7",
            query="limit=3",
            headers={"x-token": "t"},
            path_params={"item_id": "7"},
        ),
    ),
    (
        "deep-limit-invalid",
        dependant_for(uses_access, "/items/{item_id}"),
        make_scope(path="/items/7", query="limit=abc", path_params={"item_id": "7"}),
    ),
    (
        "deep-path-invalid",
        dependant_for(uses_access, "/items/{item_id}"),
        make_scope(path="/items/x", path_params={"item_id": "x"}),
    ),
    ("path-level", audited_dependant(), make_scope(query="q=1")),
    (
        "cookie-ok",
        dependant_for(uses_cookie),
        make_scope(headers={"x-required": "r", "cookie": "session=s1"}),
    ),
    ("cookie-missing-header", dependant_for(uses_cookie), make_scope()),
]


@pytest.mark.parametrize(
    "dependant, scope", [case[1:] for case in CASES], ids=[case[0] for case in CASES]
)
def test_plan_matches_the_generic_solver(
    dependant: Dependant, scope: dict[str, Any]
) -> None:
    calls.clear()
    generic_values, generic_errors = anyio.run(generic_solve, dependant, scope)
    generic_calls = list(calls)
    calls.clear()
    planned_values, planned_errors = anyio.run(planned_solve, dependant, scope)
    assert planned_values == generic_values
    assert planned_errors == generic_errors
    assert calls == generic_calls


def test_shared_dependency_is_called_once_and_reported_twice_when_missing() -> None:
    calls.clear()
    values, errors = anyio.run(
        planned_solve, dependant_for(uses_shared), make_scope(query="tag=x")
    )
    assert values == {"first": "parent:x", "second": "x"}
    assert errors == []
    assert calls == ["shared:x", "via_parent"]
    calls.clear()
    values, errors = anyio.run(planned_solve, dependant_for(uses_shared), make_scope())
    assert [error["loc"] for error in errors] == [("query", "tag"), ("query", "tag")]
    assert calls == []


def test_uncached_dependency_runs_again_and_a_cached_one_reuses_the_first() -> None:
    calls.clear()
    values, errors = anyio.run(
        planned_solve, dependant_for(uses_uncached), make_scope()
    )
    assert errors == []
    assert calls == ["counter", "counter"]
    assert values == {"first": 1, "second": 2, "third": 1}


def test_failure_deep_in_the_tree_skips_the_caller_but_not_its_siblings() -> None:
    calls.clear()
    dependant = dependant_for(uses_access, "/items/{item_id}")
    scope = make_scope(path="/items/7", query="limit=abc", path_params={"item_id": "7"})
    values, errors = anyio.run(planned_solve, dependant, scope)
    assert [error["loc"] for error in errors] == [("query", "limit")]
    assert calls == ["user"]
    assert "grant" not in values
    assert values["who"] == "anonymous"


def test_plan_shape() -> None:
    plan = compile_solve_plan(dependant_for(uses_access, "/items/{item_id}"))
    assert plan is not None
    assert len(plan.steps) == 3
    assert plan.slot_count == 1
    assert plan.needs_cookies is False
    shared_plan = compile_solve_plan(dependant_for(uses_shared))
    assert shared_plan is not None
    assert shared_plan.slot_count == 1
    single = compile_solve_plan(dependant_for(access))
    assert single is not None
    assert single.slot_count == 0
    assert len(single.steps) == 1
    cookie_plan = compile_solve_plan(dependant_for(uses_cookie))
    assert cookie_plan is not None
    assert cookie_plan.needs_cookies is True


def wants_request(request: Request) -> str:
    return request.url.path


async def uses_request(path: Annotated[str, Depends(wants_request)]) -> dict[str, str]:
    return {"path": path}


def with_yield() -> Any:
    yield "resource"


async def uses_yield(value: Annotated[str, Depends(with_yield)]) -> dict[str, str]:
    return {"value": value}


def test_no_plan_for_request_parameters_or_generators() -> None:
    assert compile_solve_plan(dependant_for(uses_request)) is None
    assert compile_solve_plan(dependant_for(uses_yield)) is None


app = FastAPI()
route_events: list[str] = []


async def current_user(x_token: Annotated[str | None, Header()] = None) -> str:
    return x_token or "anonymous"


async def pagination(skip: int = 0, limit: int = 20) -> dict[str, int]:
    return {"skip": skip, "limit": limit}


def sync_lookup(item_id: int) -> str:
    route_events.append("lookup")
    return f"item-{item_id}"


def stamp(response: Response) -> str:
    response.headers["x-stamp"] = "yes"
    return "stamped"


def path_audit() -> None:
    route_events.append("audit")


@app.get("/who")
async def who(user_name: Annotated[str, Depends(current_user)]) -> dict[str, str]:
    return {"user": user_name}


@app.get("/items/{item_id}")
async def item(
    name: Annotated[str, Depends(sync_lookup)],
    page: Annotated[dict[str, int], Depends(pagination)],
    user_name: Annotated[str, Depends(current_user)],
) -> dict[str, Any]:
    return {"name": name, "user": user_name, **page}


@app.get("/stamped")
async def stamped(mark: Annotated[str, Depends(stamp)]) -> dict[str, str]:
    return {"mark": mark}


@app.get("/audited", dependencies=[Depends(path_audit)])
async def audited_route() -> dict[str, bool]:
    return {"ok": True}


@app.get("/cookie")
async def cookie_route(
    session: Annotated[str | None, Cookie()] = None,
) -> dict[str, str | None]:
    return {"session": session}


client = TestClient(app)


def route_for(path: str) -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)


def test_simple_dependency_routes_get_the_planned_app() -> None:
    assert route_for("/who").app.__qualname__ == "planned_route_app.<locals>.app"
    assert (
        route_for("/items/{item_id}").app.__qualname__
        == "planned_route_app.<locals>.app"
    )
    assert route_for("/audited").app.__qualname__ == "planned_route_app.<locals>.app"
    assert route_for("/cookie").app.__qualname__ == "planned_route_app.<locals>.app"
    assert route_for("/stamped").app.__qualname__ == "plain_route_app.<locals>.app"


def test_planned_routes_resolve_validate_and_serialize() -> None:
    route_events.clear()
    assert client.get("/who", headers={"x-token": "t"}).json() == {"user": "t"}
    assert client.get("/who").json() == {"user": "anonymous"}
    response = client.get("/items/4?limit=2", headers={"x-token": "me"})
    assert response.json() == {"name": "item-4", "user": "me", "skip": 0, "limit": 2}
    assert route_events == ["lookup"]
    invalid = client.get("/items/abc?limit=x")
    assert invalid.status_code == 422
    assert [e["loc"] for e in invalid.json()["detail"]] == [
        ["path", "item_id"],
        ["query", "limit"],
    ]
    assert client.get("/audited").json() == {"ok": True}
    assert route_events == ["lookup", "audit"]
    client.cookies.set("session", "abc")
    assert client.get("/cookie").json() == {"session": "abc"}
    client.cookies.clear()
    assert client.get("/cookie").json() == {"session": None}
    stamped_response = client.get("/stamped")
    assert stamped_response.json() == {"mark": "stamped"}
    assert stamped_response.headers["x-stamp"] == "yes"


def test_overrides_still_take_the_general_path() -> None:
    def replacement() -> Any:
        route_events.append("override-enter")
        yield "swapped"
        route_events.append("override-exit")

    route_events.clear()
    app.dependency_overrides[current_user] = replacement
    try:
        assert client.get("/who").json() == {"user": "swapped"}
    finally:
        app.dependency_overrides.clear()
    assert route_events == ["override-enter", "override-exit"]
    assert client.get("/who").json() == {"user": "anonymous"}
