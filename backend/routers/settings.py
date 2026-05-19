from fastapi import APIRouter, Body
from typing import Dict, Any
import re
# Import cases_col so we can modify the main table rows
from backend.db import settings_col, cases_col 

router = APIRouter(tags=["settings"])

@router.get("/settings")
def get_settings():
    doc = settings_col.find_one({"_id": "global_settings"}, {"_id": 0})
    if not doc:
        return {"is_empty": True} 
    return doc

@router.post("/settings")
def save_settings(payload: Dict[str, Any] = Body(...)):
    bug_labels = payload.get("bug_labels", [])
    test_labels = payload.get("test_labels", [])
    assignees = payload.get("assignees", [])

    # 1. Update Global Settings
    settings_col.update_one(
        {"_id": "global_settings"},
        {"$set": {
            "bug_labels": bug_labels,
            "test_labels": test_labels,
            "assignees": assignees
        }},
        upsert=True
    )

    # 2. Scrub existing table rows in the database to remove deleted labels
    for case in cases_col.find():
        issue_type = case.get("issue_type")
        valid_labels = test_labels if issue_type == "Test" else bug_labels
        
        current_labels_str = case.get("labels", "")
        if current_labels_str:
            # Split the string by spaces or commas
            current_labels = [x for x in re.split(r'[,\s]+', current_labels_str) if x]
            
            # Filter out any label that is no longer in the valid global list
            cleaned_labels = [lbl for lbl in current_labels if lbl in valid_labels]
            cleaned_str = " ".join(cleaned_labels)
            
            # If the labels changed, update the row in the DB instantly
            if cleaned_str != current_labels_str:
                cases_col.update_one({"_id": case["_id"]}, {"$set": {"labels": cleaned_str}})
        
        # 3. Bonus: Also remove deleted assignees from rows
        current_assignee = case.get("assignee", "").strip()
        if current_assignee and current_assignee not in assignees:
            cases_col.update_one({"_id": case["_id"]}, {"$set": {"assignee": ""}})

    return {"ok": True}