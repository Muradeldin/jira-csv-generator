from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import ensure_indexes
from .routers import cases, jira

app = FastAPI(title="Cases → Jira Bulk Create")

# CORS (open for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    ensure_indexes()

app.include_router(cases.router)
app.include_router(jira.router)
