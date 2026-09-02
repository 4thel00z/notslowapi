from notsoslow import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Tomato"}
