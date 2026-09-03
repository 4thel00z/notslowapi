from notslowapi import FastAPI

app = FastAPI()

app.frontend("/", directory="dist", fallback=None)
