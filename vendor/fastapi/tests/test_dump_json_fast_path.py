from unittest.mock import patch

from notslowapi import FastAPI
from notslowapi.responses import JSONResponse
from notslowapi.testclient import TestClient
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    price: float


app = FastAPI()


@app.get("/default")
def get_default() -> Item:
    return Item(name="widget", price=9.99)


@app.get("/explicit", response_class=JSONResponse)
def get_explicit() -> Item:
    return Item(name="widget", price=9.99)


client = TestClient(app)


def test_default_response_class_skips_json_response_render():
    """When no response_class is set, the fast path serializes directly to
    JSON bytes via Pydantic's dump_json and never renders a JSONResponse."""
    with patch.object(
        JSONResponse, "render", autospec=True, side_effect=JSONResponse.render
    ) as mock_render:
        response = client.get("/default")
    assert response.status_code == 200
    assert response.json() == {"name": "widget", "price": 9.99}
    mock_render.assert_not_called()


def test_explicit_response_class_uses_json_response_render():
    """When response_class is explicitly set to JSONResponse, the normal path
    is used and the content goes through JSONResponse.render()."""
    with patch.object(
        JSONResponse, "render", autospec=True, side_effect=JSONResponse.render
    ) as mock_render:
        response = client.get("/explicit")
    assert response.status_code == 200
    assert response.json() == {"name": "widget", "price": 9.99}
    mock_render.assert_called_once()
