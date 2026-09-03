from typing import Any
from unittest.mock import patch

import pytest
from notslowapi import FastAPI
from notslowapi.requests import Request
from notslowapi.testclient import TestClient
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    price: float


app = FastAPI()


@app.post("/fast")
async def create_fast(item: Item) -> Item:
    return item


@app.post("/fast-sync")
def create_fast_sync(item: Item) -> Item:
    return item


@app.post("/generic")
async def create_generic(item: Item, q: str | None = None) -> Item:
    return item


@app.post("/optional")
async def create_optional(item: Item | None = None) -> dict[str, Any]:
    return {"received": item is not None}


@app.post("/optional-generic")
async def create_optional_generic(
    item: Item | None = None, q: str | None = None
) -> dict[str, Any]:
    return {"received": item is not None}


@app.post("/nullable")
async def create_nullable(item: Item | None) -> dict[str, Any]:
    return {"received": item is not None}


@app.post("/nullable-generic")
async def create_nullable_generic(
    item: Item | None, q: str | None = None
) -> dict[str, Any]:
    return {"received": item is not None}


client = TestClient(app)

VALID = b'{"name": "widget", "price": 9.99}'
JSON = {"content-type": "application/json"}

BODIES = [
    pytest.param(VALID, JSON, id="valid"),
    pytest.param(VALID, {"content-type": "application/vnd.api+json"}, id="plus-json"),
    pytest.param(VALID, {"content-type": "text/plain"}, id="text-plain"),
    pytest.param(VALID, {}, id="no-content-type"),
    pytest.param(b"", JSON, id="empty"),
    pytest.param(b"null", JSON, id="null"),
    pytest.param(b'{"name": "widget", "price": 9.99', JSON, id="truncated"),
    pytest.param(b'{"name": "widget"}', JSON, id="missing-field"),
    pytest.param(b'{"name": "widget", "price": "free"}', JSON, id="wrong-type"),
    pytest.param(b"[1, 2]", JSON, id="list"),
    pytest.param(b"\xef\xbb\xbf" + VALID, JSON, id="utf8-bom"),
    pytest.param(VALID.decode().encode("utf-16"), JSON, id="utf16"),
]


def test_fast_path_skips_request_json() -> None:
    with patch.object(Request, "json", autospec=True, side_effect=Request.json) as mock:
        response = client.post("/fast", content=VALID, headers=JSON)
    assert response.status_code == 200
    assert response.json() == {"name": "widget", "price": 9.99}
    mock.assert_not_called()


def test_generic_path_still_uses_request_json() -> None:
    with patch.object(Request, "json", autospec=True, side_effect=Request.json) as mock:
        response = client.post("/generic", content=VALID, headers=JSON)
    assert response.status_code == 200
    mock.assert_called_once()


def test_sync_endpoint_uses_fast_path() -> None:
    with patch.object(Request, "json", autospec=True, side_effect=Request.json) as mock:
        response = client.post("/fast-sync", content=VALID, headers=JSON)
    assert response.status_code == 200
    assert response.json() == {"name": "widget", "price": 9.99}
    mock.assert_not_called()


@pytest.mark.parametrize(("content", "headers"), BODIES)
def test_same_result_as_general_handler(
    content: bytes, headers: dict[str, str]
) -> None:
    fast = client.post("/fast", content=content, headers=headers)
    generic = client.post("/generic", content=content, headers=headers)
    assert (fast.status_code, fast.json()) == (generic.status_code, generic.json())


@pytest.mark.parametrize(("content", "headers"), BODIES)
def test_optional_body_same_result(content: bytes, headers: dict[str, str]) -> None:
    fast = client.post("/optional", content=content, headers=headers)
    generic = client.post("/optional-generic", content=content, headers=headers)
    assert (fast.status_code, fast.json()) == (generic.status_code, generic.json())


@pytest.mark.parametrize(("content", "headers"), BODIES)
def test_nullable_required_body_same_result(
    content: bytes, headers: dict[str, str]
) -> None:
    fast = client.post("/nullable", content=content, headers=headers)
    generic = client.post("/nullable-generic", content=content, headers=headers)
    assert (fast.status_code, fast.json()) == (generic.status_code, generic.json())


def test_null_body_uses_default() -> None:
    response = client.post("/optional", content=b"null", headers=JSON)
    assert response.status_code == 200
    assert response.json() == {"received": False}


def test_null_body_for_required_nullable_is_missing() -> None:
    response = client.post("/nullable", content=b"null", headers=JSON)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "missing"


def test_invalid_json_error_matches_upstream_format() -> None:
    response = client.post(
        "/fast", content=b'{"name": "widget", "price": 9.99', headers=JSON
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "json_invalid",
                "loc": ["body", 32],
                "msg": "JSON decode error",
                "input": {},
                "ctx": {"error": "Expecting ',' delimiter"},
            }
        ]
    }
