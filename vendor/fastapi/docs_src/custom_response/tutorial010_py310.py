from notsoslow import FastAPI
from notsoslow.responses import HTMLResponse

app = FastAPI(default_response_class=HTMLResponse)


@app.get("/items/")
async def read_items():
    return "<h1>Items</h1><p>This is a list of items.</p>"
