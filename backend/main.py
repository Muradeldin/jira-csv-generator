from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Any, Dict, Optional
import csv, os, datetime

# ---------- Mongo ----------
from pymongo import MongoClient, ASCENDING, DESCENDING

app = FastAPI(title="Cases → CSV")

# CORS (open for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- CSV (UPDATED: added Labels column) ----------
CSV_HEADERS = ['Summary', 'Issue Type', 'Description', 'Link "Relates"', 'Assignee', 'Labels', 'NSOC_Team']

class Row(BaseModel):
    summary: str = ""
    issue_type: str = ""
    description: str = ""
    link_relates: str = ""
    assignee: str = ""
    labels: str = ""       
    nsoc_team: str = ""

class Payload(BaseModel):
    rows: List[Row]

@app.post("/save-csv")
def save_csv(payload: Payload):
    rows = [
        r for r in payload.rows
        if any([r.summary, r.issue_type, r.description, r.link_relates, r.assignee, r.labels, r.nsoc_team])
    ]
    if not rows:
        raise HTTPException(status_code=400, detail="No non-empty rows to save.")

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"cases-{ts}.csv"
    path = os.path.join(os.getcwd(), filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for r in rows:
            writer.writerow([r.summary, r.issue_type, r.description, r.link_relates, r.assignee, r.labels, r.nsoc_team])
    return {"ok": True, "filename": filename}

@app.get("/download/{filename}")
def download_csv(filename: str):
    path = os.path.join(os.getcwd(), filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=filename)

# ---------- MongoDB setup ----------
MONGO_HOST = os.getenv("MONGO_HOST", "mongo")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_USER = os.getenv("MONGO_USER", "root")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "example")
MONGO_DB = os.getenv("MONGO_DB", "casesdb")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "cases")

# Build URI; authSource=admin when using root user from official image
MONGO_URI = os.getenv(
    "MONGO_URI",
    f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/?authSource=admin"
)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
col = db[MONGO_COLLECTION]

@app.on_event("startup")
def _mongo_indexes():
    # Example indexes; optional but useful
    col.create_index([("summary", ASCENDING)])
    col.create_index([("issue_type", ASCENDING)])
    col.create_index([("nsoc_team", ASCENDING)])
    col.create_index([("labels", ASCENDING)]) 

# ---------- DB endpoints (Mongo) ----------
@app.post("/save-db")
def save_db(payload: Dict[str, Any] = Body(...)):
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail='"rows" must be a non-empty array')

    # Remove all existing documents first
    col.delete_many({})

    docs: List[Dict[str, str]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if any([
            r.get("summary"),
            r.get("issue_type"),
            r.get("description"),
            r.get("link_relates"),
            r.get("assignee"),
            r.get("labels"),
            r.get("nsoc_team")
        ]):
            docs.append({
                "summary": str(r.get("summary", "")).strip(),
                "issue_type": str(r.get("issue_type", "")).strip(),
                "description": str(r.get("description", "")).strip(),
                "link_relates": str(r.get("link_relates", "")).strip(),
                "assignee": str(r.get("assignee", "")).strip(),
                "labels": str(r.get("labels", "")).strip(),
                "nsoc_team": str(r.get("nsoc_team", "")).strip(),
                "created_at": datetime.datetime.utcnow(),
            })

    if not docs:
        raise HTTPException(status_code=400, detail="No non-empty rows to save.")

    res = col.insert_many(docs)
    return {"ok": True, "inserted": len(res.inserted_ids), "mode": "overwrite"}


@app.get("/cases")
def list_cases():
    # newest first
    items = list(col.find({}, {"_id": 0}).sort([("created_at", DESCENDING)]))
    return {"rows": items}

@app.delete("/cases")
def clear_cases():
    res = col.delete_many({})
    return {"ok": True, "deleted": res.deleted_count}
