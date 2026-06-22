import asyncio
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import Response

from . import database as db
from .routes import router, set_main_loop

app = FastAPI(title="Automação SISREG", version="2.0.0")

app.include_router(router)

static_dir = os.path.join(os.path.dirname(__file__), "static")
templates_dir = os.path.join(os.path.dirname(__file__), "templates")

os.makedirs(static_dir, exist_ok=True)
os.makedirs(templates_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return Response(status_code=204)

@app.get("/")
def index():
    return FileResponse(os.path.join(templates_dir, "index.html"))


@app.on_event("startup")
def startup():
    set_main_loop(asyncio.get_event_loop())
    db.init_db()
