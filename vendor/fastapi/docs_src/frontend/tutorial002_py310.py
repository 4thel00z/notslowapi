from notsoslow import FastAPI

app = FastAPI()

app.frontend("/", directory="dist", fallback="index.html")
