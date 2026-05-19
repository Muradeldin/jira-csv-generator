from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body, Query
from fastapi.responses import FileResponse
from typing import Any, Dict, List
import csv, os, datetime, json
import pandas as pd
import io
from pymongo import DESCENDING

from backend.models import Payload
from backend.db import cases_col

router = APIRouter(tags=["cases"])

# ADDED 'Test Steps' to the end of the Test headers
TEST_HEADERS = ['Summary', 'Issue Type', 'Description', 'Link "Relates"', 'Assignee', 'Labels', 'NSOC_Team', 'Severity', 'Test Steps']
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
            base_row = [r.summary, r.issue_type, r.description, r.link_relates, r.assignee, r.labels, r.nsoc_team, r.severity]
            
            # If it's a Test, serialize the steps into a JSON string for the CSV column
            if issue_type == "Test":
                steps_str = ""
                if r.steps:
                    steps_str = json.dumps([s.model_dump() if hasattr(s, "model_dump") else s.dict() for s in r.steps])
                writer.writerow(base_row + [steps_str])
            else:
                writer.writerow(base_row)

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
            r.get("assignee"), r.get("labels"), r.get("nsoc_team"), r.get("severity"), has_steps
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
    col_map = {
        "Summary": "summary", "Title": "summary",
        "Issue Type": "issue_type", "Type": "issue_type",
        "Description": "description",
        "Link": "link_relates", "Relates": "link_relates",
        "Assignee": "assignee",
        "Labels": "labels",
        "Team": "nsoc_team", "NSOC_Team": "nsoc_team",
        "Severity": "severity", "Priority": "severity",
        "Test Steps": "steps", "Steps": "steps" # Map Steps column
    }
    
    new_cols = {}
    for actual_col in df.columns:
        clean_col = str(actual_col).strip()
        for key, val in col_map.items():
            if clean_col.lower() == key.lower():
                new_cols[actual_col] = val
                break
    
    df.rename(columns=new_cols, inplace=True)

    # 3. PREPARE DATA
    required_cols = ["summary", "description", "link_relates", "assignee", "labels", "nsoc_team", "severity"]
    
    # Ensure all required columns AND steps exist
    for col in required_cols + ["steps"]:
        if col not in df.columns:
            df[col] = ""

    df = df.fillna("") 

    docs = []
    for _, row in df.iterrows():
        if not any(row[c] for c in required_cols if row[c]):
            continue

        # --- SMART STEP PARSER ---
        steps_raw = str(row.get("steps", "")).strip()
        parsed_steps = []
        
        # Only parse steps if it's a Test
        if steps_raw and issue_type == "Test":
            try:
                # First try to parse it as JSON (If it was exported from our app)
                parsed_list = json.loads(steps_raw)
                if isinstance(parsed_list, list):
                    for s in parsed_list:
                        if isinstance(s, dict):
                            parsed_steps.append({
                                "step": str(s.get("step", "")).strip(),
                                "data": str(s.get("data", "")).strip(),
                                "result": str(s.get("result", "")).strip(),
                            })
            except json.JSONDecodeError:
                # Fallback: If a human typed multiline text in Excel, treat each line as a step!
                lines = steps_raw.split('\n')
                for line in lines:
                    if line.strip():
                        parsed_steps.append({
                            "step": line.strip(),
                            "data": "",
                            "result": ""
                        })

        docs.append({
            "summary": str(row["summary"]).strip(),
            "issue_type": issue_type,
            "description": str(row["description"]).strip(),
            "link_relates": str(row["link_relates"]).strip(),
            "assignee": str(row["assignee"]).strip(),
            "labels": str(row["labels"]).strip(),
            "nsoc_team": str(row["nsoc_team"]).strip(),
            "severity": str(row["severity"]).strip(),
            "steps": parsed_steps,
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
        "mode": "overwrite"
    }