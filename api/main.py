from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import router


app = FastAPI(title="Schedule MILP 调度平台", version="0.1.0")
app.include_router(router)
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        return {"status": "ok", "message": "web assets have not been generated"}
    return FileResponse(index_path)
