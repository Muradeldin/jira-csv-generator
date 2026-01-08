from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import FileResponse
from typing import Any, Dict, List
import csv, os, datetime
from pymongo import DESCENDING

from backend.models import Payload
from backend.db import cases_col

router = APIRouter(tags=["cases"])

TEST_HEADERS = ['Summary', 'Issue Type', 'Description', 'Link "Relates"', 'Assignee', 'Labels', 'NSOC_Team', 'Severity']
BUG_HEADERS  = ['Summary', 'Issue Type', 'Description', 'Link "Problem/Incident"', 'Assignee', 'Labels', 'NSOC_Team', 'Severity']
Headers = {"Test": TEST_HEADERS, "Bug": BUG_HEADERS}

@router.post("/save-csv")
def save_csv(payload: Payload, issue_type: str = Query(...)):
    if issue_type not in Headers:
        raise HTTPException(status_code=400, detail='issue_type must be "Test" or "Bug"')

    rows = [
        r for r in payload.rows
        if any([r.summary, r.issue_type, r.description, r.link_relates, r.assignee, r.labels, r.nsoc_team, r.severity])
    ]
    if not rows:
        raise HTTPException(status_code=400, detail="No non-empty rows to save.")

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{issue_type}-ticket-{ts}.csv"
    path = os.path.join(os.getcwd(), filename)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(Headers[issue_type])
        for r in rows:
            writer.writerow([r.summary, r.issue_type, r.description, r.link_relates, r.assignee, r.labels, r.nsoc_team, r.severity])

    return {"ok": True, "filename": filename}

@router.get("/download/{filename}")
def download_csv(filename: str):
    path = os.path.join(os.getcwd(), filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=filename)


@router.post("/save-db")
def save_db(payload: Dict[str, Any] = Body(...), issue_type: str = Query(...)):
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail='"rows" must be a non-empty array')

    cases_col.delete_many({"issue_type": issue_type})

    docs: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if any([
            r.get("summary"), r.get("issue_type"), r.get("description"), r.get("link_relates"),
            r.get("assignee"), r.get("labels"), r.get("nsoc_team"), r.get("severity")
        ]):
            docs.append({
                "summary": str(r.get("summary", "")).strip(),
                "issue_type": str(r.get("issue_type", "")).strip(),
                "description": str(r.get("description", "")).strip(),
                "link_relates": str(r.get("link_relates", "")).strip(),
                "assignee": str(r.get("assignee", "")).strip(),
                "labels": str(r.get("labels", "")).strip(),
                "nsoc_team": str(r.get("nsoc_team", "")).strip(),
                "severity": str(r.get("severity", "")).strip(),
                "created_at": datetime.datetime.utcnow(),
            })

    if not docs:
        raise HTTPException(status_code=400, detail="No non-empty rows to save.")

    res = cases_col.insert_many(docs)
    return {"ok": True, "inserted": len(res.inserted_ids), "mode": "overwrite"}

@router.get("/cases")
def list_cases(issue_type: str = Query(...)):
    items = list(cases_col.find({"issue_type": issue_type}, {"_id": 0}).sort([("created_at", DESCENDING)]))
    return {"rows": items}

@router.delete("/cases")
def clear_cases(issue_type: str = Query(...)):
    res = cases_col.delete_many({"issue_type": issue_type})
    return {"ok": True, "deleted": res.deleted_count}
