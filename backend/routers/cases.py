from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body, Query
from fastapi.responses import FileResponse
from typing import Any, Dict, List
import csv, os, datetime
import pandas as pd
import io
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

        steps = r.get("steps", [])
        has_steps = isinstance(steps, list) and len(steps) > 0

        if any([
            r.get("summary"), r.get("issue_type"), r.get("description"), r.get("link_relates"),
            r.get("assignee"), r.get("labels"), r.get("nsoc_team"), r.get("severity", has_steps)
        ]):
            issue_type_row = str(r.get("issue_type", "")).strip()

            # Disable steps for Bugs (backend rule)
            if issue_type_row == "Bug":
                steps = []

            norm_steps = []
            if isinstance(steps, list):
                for s in steps:
                    if not isinstance(s, dict):
                        continue
                    norm_steps.append({
                        "step": str(s.get("step", "")).strip(),
                        "data": str(s.get("data", "")).strip(),
                        "result": str(s.get("result", "")).strip(),
                    })

            
            docs.append({
                "summary": str(r.get("summary", "")).strip(),
                "issue_type": str(r.get("issue_type", "")).strip(),
                "description": str(r.get("description", "")).strip(),
                "link_relates": str(r.get("link_relates", "")).strip(),
                "assignee": str(r.get("assignee", "")).strip(),
                "labels": str(r.get("labels", "")).strip(),
                "nsoc_team": str(r.get("nsoc_team", "")).strip(),
                "severity": str(r.get("severity", "")).strip(),
                "steps": norm_steps,
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


@router.post("/upload-file-db")
async def upload_file_db(
    file: UploadFile = File(...),
    issue_type: str = Form(...),
):
    # 1. READ FILE
    content = await file.read()
    filename = (file.filename or "").lower()

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        elif filename.endswith((".xls", ".xlsx")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(400, "Invalid file type. Use .csv or .xlsx")
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {str(e)}")

    if df.empty:
        raise HTTPException(400, "File is empty")

    # 2. NORMALIZE HEADERS
    # Map common variations to your DB keys
    col_map = {
        "Summary": "summary", "Title": "summary",
        "Issue Type": "issue_type", "Type": "issue_type",
        "Description": "description",
        "Link": "link_relates", "Relates": "link_relates",
        "Assignee": "assignee",
        "Labels": "labels",
        "Team": "nsoc_team", "NSOC_Team": "nsoc_team",
        "Severity": "severity", "Priority": "severity"
    }
    
    # Rename columns based on map (case-insensitive search)
    new_cols = {}
    for actual_col in df.columns:
        clean_col = str(actual_col).strip()
        # Check if this column matches any of our known keys
        for key, val in col_map.items():
            if clean_col.lower() == key.lower():
                new_cols[actual_col] = val
                break
    
    df.rename(columns=new_cols, inplace=True)

    # 3. PREPARE DATA
    # Ensure required columns exist, fill missing with empty string
    required_cols = ["summary", "description", "link_relates", "assignee", "labels", "nsoc_team", "severity"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    df = df.fillna("") # Remove NaNs

    docs = []
    for _, row in df.iterrows():
        # Skip rows that are essentially empty
        if not any(row[c] for c in required_cols if row[c]):
            continue

        docs.append({
            "summary": str(row["summary"]).strip(),
            "issue_type": issue_type, # Force the selected issue type
            "description": str(row["description"]).strip(),
            "link_relates": str(row["link_relates"]).strip(),
            "assignee": str(row["assignee"]).strip(),
            "labels": str(row["labels"]).strip(),
            "nsoc_team": str(row["nsoc_team"]).strip(),
            "severity": str(row["severity"]).strip(),
            "created_at": datetime.datetime.utcnow(),
        })

    if not docs:
        raise HTTPException(400, "No valid data found in file")

    # 4. SAVE TO DB
    cases_col.delete_many({"issue_type": issue_type})
    result = cases_col.insert_many(docs)

    return {
        "ok": True, 
        "inserted": len(result.inserted_ids), 
    }