from notsoslow import FastAPI

app = FastAPI()

app.frontend("/", directory="dist", fallback="404.html")
