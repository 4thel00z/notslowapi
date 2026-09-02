from notsoslow import FastAPI
from notsoslow.routing import APIRoute


def custom_generate_unique_id(route: APIRoute) -> str:
    return route.name


app = FastAPI(generate_unique_id_function=custom_generate_unique_id)


@app.get("/items/")
async def read_items():
    return [{"item_id": "Foo"}]
