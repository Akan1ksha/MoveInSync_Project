"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, auth
from app.models.database import init_db

app = FastAPI(
    title="MoveInSync Shift-Change Agent",
    version="0.1.0",
    description="AI-powered shift-change request assistant for employee transport.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])


@app.get("/health")
def health():
    return {"status": "ok"}
