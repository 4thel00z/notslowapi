from typing import Annotated, Any

from notslowapi import Depends, FastAPI, Header, HTTPException, Response
from notslowapi.routing import APIRoute
from notslowapi.testclient import TestClient

events: list[str] = []


async def current_user(x_token: Annotated[str | None, Header()] = None) -> str:
    if x_token == "bad":
        raise HTTPException(status_code=401, detail="bad token")
    return x_token or "anonymous"


def stamp(response: Response) -> str:
    response.headers["x-stamp"] = "yes"
    return "stamped"


def with_yield() -> Any:
    events.append("enter")
    yield "resource"
    events.append("exit")


app = FastAPI()


@app.get("/who")
async def who(user: Annotated[str, Depends(current_user)]) -> dict[str, str]:
    return {"user": user}


@app.get("/stamped")
async def stamped(mark: Annotated[str, Depends(stamp)]) -> dict[str, str]:
    return {"mark": mark}


@app.get("/resource")
async def resource(value: Annotated[str, Depends(with_yield)]) -> dict[str, str]:
    return {"value": value}


client = TestClient(app)


def route_for(path: str) -> APIRoute:
    return next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path)


def test_dependency_routes_without_yield_get_the_one_frame_app() -> None:
    assert route_for("/who").app.__qualname__ == "plain_route_app.<locals>.app"
    assert route_for("/stamped").app.__qualname__ == "plain_route_app.<locals>.app"
    assert route_for("/resource").app.__qualname__ == "request_response.<locals>.app"


def test_dependencies_resolve_and_raise_through_the_one_frame_app() -> None:
    assert client.get("/who", headers={"x-token": "t"}).json() == {"user": "t"}
    assert client.get("/who").json() == {"user": "anonymous"}
    denied = client.get("/who", headers={"x-token": "bad"})
    assert denied.status_code == 401
    assert denied.json() == {"detail": "bad token"}
    stamped_response = client.get("/stamped")
    assert stamped_response.json() == {"mark": "stamped"}
    assert stamped_response.headers["x-stamp"] == "yes"


def test_overrides_send_the_request_through_the_general_app() -> None:
    def replacement() -> Any:
        events.append("override-enter")
        yield "swapped"
        events.append("override-exit")

    events.clear()
    app.dependency_overrides[current_user] = replacement
    try:
        assert client.get("/who").json() == {"user": "swapped"}
    finally:
        app.dependency_overrides.clear()
    assert events == ["override-enter", "override-exit"]
    assert client.get("/who").json() == {"user": "anonymous"}


def test_yield_dependency_route_keeps_the_exit_stack_path() -> None:
    events.clear()
    assert client.get("/resource").json() == {"value": "resource"}
    assert events == ["enter", "exit"]
