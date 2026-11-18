from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routes import router


app = FastAPI(title="Schedule MILP 调度平台", version="0.1.0")
app.include_router(router)
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        return {"status": "ok", "message": "web assets have not been generated"}
    return FileResponse(index_path)


MODULE_PAGES = {"optimization", "inputs", "results", "control"}
WEB_PAGES = {name: MODULE_PAGES for name in ("weekly_plan", "daily_plan", "hourly_plan")}
WEB_PAGES["shared"] = {"devices", "network"}


@app.get("/{module}/{page}.html", include_in_schema=False)
def web_page(module: str, page: str):
    if page not in WEB_PAGES.get(module, set()):
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(WEB_DIR / module / f"{page}.html")


@app.get("/{module}/", include_in_schema=False)
def module_home(module: str):
    if module not in WEB_PAGES:
        raise HTTPException(status_code=404, detail="module not found")
    page = "devices" if module == "shared" else "optimization"
    return RedirectResponse(f"/{module}/{page}.html", status_code=307)
