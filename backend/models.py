from pydantic import BaseModel
from typing import List

class Step(BaseModel):
    step: str = ""
    data: str = ""
    result: str = ""

class Row(BaseModel):
    summary: str = ""
    issue_type: str = ""
    description: str = ""
    link_relates: str = ""
    assignee: str = ""
    labels: str = ""
    nsoc_team: str = ""
    severity: str = ""
    steps: List[Step] = []

class Payload(BaseModel):
    rows: List[Row]
