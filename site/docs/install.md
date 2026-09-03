# Install

notslowapi is published on PyPI as `notslowapi`. It requires Python 3.10 or newer (`requires-python = ">=3.10"`; 3.10 through 3.14 are listed in the package classifiers) and `pydantic>=2.9.0`. Pydantic v1 is not supported; see the [FAQ](faq.md).

## uv

```console
uv add notslowapi[granian]
```

## pip

```console
pip install "notslowapi[granian]"
```

Quote the argument if your shell expands square brackets.

## What the base install contains

`notslowapi` without extras installs the framework, the vendored Starlette under `notslowapi.starlette`, Starlette's own requirement `anyio`, and `pydantic`, `typing-extensions`, `typing-inspection` and `annotated-doc`. No ASGI server is included. Nothing is installed under the `starlette` or `fastapi` names, and existing installs of those packages are left alone.

## Extras

`granian` pulls `granian>=2.0`, the server this project recommends. See [Deploy](deploy.md).

```console
uv add notslowapi[granian]
```

`standard` is FastAPI's extra minus `fastapi-cli` and `fastar`, which depend on the PyPI `fastapi` package and would install it next to notslowapi. It adds `httpx` (test client), `jinja2` (templates), `python-multipart` (forms and uploads), `email-validator`, `uvicorn[standard]` (uvicorn with uvloop and httptools), `pydantic-settings` and `pydantic-extra-types`.

```console
uv add notslowapi[standard]
```

The two combine:

```console
uv add "notslowapi[granian,standard]"
```


## Check the install

```console
python -c "import notslowapi; print(notslowapi.__version__)"
```

prints `0.1.0`. The vendored Starlette reports its own version:

```console
python -c "import notslowapi.starlette; print(notslowapi.starlette.__version__)"
```

prints `1.6.0`.

## Next

[Deploy](deploy.md) covers the server command line. [Compatibility](compatibility.md) covers what to change in an existing FastAPI project, which is the imports.
