import warnings

import pytest

pytest.importorskip("orjson")

from notslowapi import FastAPI
from notslowapi.exceptions import FastAPIDeprecationWarning
from notslowapi.responses import ORJSONResponse  # ty: ignore[deprecated]
from notslowapi.testclient import TestClient
from sqlalchemy.sql.elements import quoted_name

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FastAPIDeprecationWarning)
    app = FastAPI(default_response_class=ORJSONResponse)  # ty: ignore[deprecated]


@app.get("/orjson_non_str_keys")
def get_orjson_non_str_keys():
    key = quoted_name(value="msg", quote=False)
    return {key: "Hello World", 1: 1}


client = TestClient(app)


def test_orjson_non_str_keys():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FastAPIDeprecationWarning)
        with client:
            response = client.get("/orjson_non_str_keys")
    assert response.json() == {"msg": "Hello World", "1": 1}
