from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.db import init_db
from app.stats import router as stats_router
from app.webhooks.razorpay import router as webhook_router

app = FastAPI(title="RecoverAI", version="0.1.0")
app.include_router(webhook_router)
app.include_router(stats_router)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
