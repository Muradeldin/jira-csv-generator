from pydantic import BaseModel
from typing import List

class Row(BaseModel):
    summary: str = ""
    issue_type: str = ""
    description: str = ""
    link_relates: str = ""
    assignee: str = ""
    labels: str = ""
    nsoc_team: str = ""
    severity: str = ""

class Payload(BaseModel):
    rows: List[Row]
