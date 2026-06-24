import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from . import database as db
from .routes import router, set_main_loop

app = FastAPI(title="Automação SISREG", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

_BASE_DIR = os.path.dirname(__file__)


@app.get("/")
def index():
    return HTMLResponse(open(os.path.join(_BASE_DIR, "templates", "index.html")).read())


@app.get("/static/style.css")
def serve_css():
    return FileResponse(os.path.join(_BASE_DIR, "static", "style.css"), media_type="text/css")


@app.get("/static/script.js")
def serve_js():
    return FileResponse(os.path.join(_BASE_DIR, "static", "script.js"), media_type="application/javascript")


@app.on_event("startup")
def startup():
    set_main_loop(asyncio.get_event_loop())
    db.init_db()
