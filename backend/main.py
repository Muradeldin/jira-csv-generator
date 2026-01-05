from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Any, Dict, Optional
import csv, os, datetime, time, secrets, urllib.parse, json
import requests
from pymongo import MongoClient, ASCENDING, DESCENDING


app = FastAPI(title="Cases → Jira Bulk Create")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8079")


# CORS (open for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- CSV (kept, optional) ----------
TEST_HEADERS = ['Summary', 'Issue Type', 'Description', 'Link "Relates"', 'Assignee', 'Labels', 'NSOC_Team', 'Severity']
BUG_HEADERS  = ['Summary', 'Issue Type', 'Description', 'Link "Problem/Incident"', 'Assignee', 'Labels', 'NSOC_Team', 'Severity']
Headers = {"Test": TEST_HEADERS, "Bug": BUG_HEADERS}

# ---------- MongoDB setup ----------
MONGO_HOST = os.getenv("MONGO_HOST", "mongo")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_USER = os.getenv("MONGO_USER", "root")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "example")
MONGO_DB = os.getenv("MONGO_DB", "casesdb")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "cases")

MONGO_URI = os.getenv(
    "MONGO_URI",
    f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/?authSource=admin"
)

# ---------- Atlassian OAuth / Jira config ----------
# IMPORTANT: do NOT hardcode these in code
ATLASSIAN_CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID", "")
ATLASSIAN_CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET", "")
ATLASSIAN_REDIRECT_URI = os.getenv("ATLASSIAN_REDIRECT_URI", "http://localhost:8000/oauth/atlassian/callback")

# Must match exactly what accessible-resources returns (usually https://<site>.atlassian.net)
JIRA_SITE_URL = os.getenv("JIRA_SITE_URL", "https://rnd-hub.atlassian.net")

# Scopes: create issues + read user + refresh tokens
ATLASSIAN_SCOPES = os.getenv("ATLASSIAN_SCOPES", "write:jira-work read:jira-user offline_access")

# Where to create issues
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "NSOC")

# Optional: customfield IDs (you can hardcode or env them)
CF_NSOC_TEAM = os.getenv("CF_NSOC_TEAM", "customfield_10337")
CF_SEVERITY  = os.getenv("CF_SEVERITY",  "customfield_10300")

# Link type names (these must match Jira's actual link type names)
JIRA_LINK_TYPE_TEST = os.getenv("JIRA_LINK_TYPE_TEST", "Relates")
JIRA_LINK_TYPE_BUG  = os.getenv("JIRA_LINK_TYPE_BUG",  "Relates")  # set to "Problem/Incident" IF it exists as link type

# Assignee mapping email -> accountId (optional)
ASSIGNEE_MAP = json.loads(os.getenv("ASSIGNEE_MAP_JSON", "{}"))


class Row(BaseModel):
    summary: str = ""
    issue_type: str = ""
    description: str = ""
    link_relates: str = ""     # can contain: "NSOC-1 NSOC-2" or "NSOC-1,NSOC-2"
    assignee: str = ""         # ideally accountId; if email, map via ASSIGNEE_MAP
    labels: str = ""
    nsoc_team: str = ""
    severity: str = ""

class Payload(BaseModel):
    rows: List[Row]


client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
col = db[MONGO_COLLECTION]
oauth_col = db["oauth_tokens"]  # stores OAuth tokens/state


@app.on_event("startup")
def _mongo_indexes():
    col.create_index([("summary", ASCENDING)])
    col.create_index([("issue_type", ASCENDING)])
    col.create_index([("nsoc_team", ASCENDING)])
    col.create_index([("labels", ASCENDING)])
    # NOTE: Do NOT create an _id index manually; Mongo already has it.


# -----------------------
# CSV endpoints (optional)
# -----------------------
@app.post("/save-csv")
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

@app.get("/download/{filename}")
def download_csv(filename: str):
    path = os.path.join(os.getcwd(), filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=filename)


# -----------------------
# Mongo endpoints (kept)
# -----------------------
@app.post("/save-db")
def save_db(payload: Dict[str, Any] = Body(...), issue_type: str = Query(...)):
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail='"rows" must be a non-empty array')

    col.delete_many({"issue_type": issue_type})

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

    res = col.insert_many(docs)
    return {"ok": True, "inserted": len(res.inserted_ids), "mode": "overwrite"}

@app.get("/cases")
def list_cases(issue_type: str = Query(...)):
    items = list(col.find({"issue_type": issue_type}, {"_id": 0}).sort([("created_at", DESCENDING)]))
    return {"rows": items}

@app.delete("/cases")
def clear_cases(issue_type: str = Query(...)):
    res = col.delete_many({"issue_type": issue_type})
    return {"ok": True, "deleted": res.deleted_count}


# -----------------------
# Atlassian OAuth helpers
# -----------------------
def _get_oauth_doc() -> Optional[Dict[str, Any]]:
    return oauth_col.find_one({"_id": "default"}, {"_id": 0})

def _save_oauth_doc(doc: Dict[str, Any]):
    oauth_col.update_one({"_id": "default"}, {"$set": {"_id": "default", **doc}}, upsert=True)

def _exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    r = requests.post(
        "https://auth.atlassian.com/oauth/token",
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "authorization_code",
            "client_id": ATLASSIAN_CLIENT_ID,
            "client_secret": ATLASSIAN_CLIENT_SECRET,
            "code": code,
            "redirect_uri": ATLASSIAN_REDIRECT_URI,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def _refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    r = requests.post(
        "https://auth.atlassian.com/oauth/token",
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "refresh_token",
            "client_id": ATLASSIAN_CLIENT_ID,
            "client_secret": ATLASSIAN_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def _get_accessible_resources(access_token: str) -> List[Dict[str, Any]]:
    r = requests.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def _ensure_valid_access_token() -> Dict[str, str]:
    doc = _get_oauth_doc()
    if not doc:
        raise HTTPException(status_code=401, detail="Not connected. Go to /oauth/atlassian/start")

    now = int(time.time())
    if doc.get("access_token") and doc.get("expires_at", 0) > now + 60:
        return {"access_token": doc["access_token"], "cloud_id": doc["cloud_id"], "cloud_url": doc["cloud_url"]}

    refresh_token = doc.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Expired and no refresh_token stored. Reconnect.")

    new_tokens = _refresh_access_token(refresh_token)
    access_token = new_tokens["access_token"]
    refresh_token_new = new_tokens.get("refresh_token", refresh_token)
    expires_at = now + int(new_tokens.get("expires_in", 3600))

    _save_oauth_doc({
        "access_token": access_token,
        "refresh_token": refresh_token_new,
        "expires_at": expires_at,
        "cloud_id": doc["cloud_id"],
        "cloud_url": doc["cloud_url"],
        "oauth_state": None,
    })
    return {"access_token": access_token, "cloud_id": doc["cloud_id"], "cloud_url": doc["cloud_url"]}


@app.get("/oauth/atlassian/start")
def oauth_start():
    if not ATLASSIAN_CLIENT_ID or not ATLASSIAN_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Missing ATLASSIAN_CLIENT_ID / ATLASSIAN_CLIENT_SECRET")

    state = secrets.token_urlsafe(32)
    _save_oauth_doc({"oauth_state": state})

    params = {
        "audience": "api.atlassian.com",
        "client_id": ATLASSIAN_CLIENT_ID,
        "scope": ATLASSIAN_SCOPES,  # must be space-separated string
        "redirect_uri": ATLASSIAN_REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    url = "https://auth.atlassian.com/authorize?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return RedirectResponse(url)


@app.get("/oauth/atlassian/callback")
def oauth_callback(code: str | None = None, state: str | None = None):
    if not code or not state:
        return RedirectResponse(url=f"{FRONTEND_URL}/login.html?error=missing_code_or_state", status_code=302)

    doc = _get_oauth_doc() or {}
    if doc.get("oauth_state") != state:
        return RedirectResponse(url=f"{FRONTEND_URL}/login.html?error=invalid_state", status_code=302)

    tokens = _exchange_code_for_tokens(code)
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_at = int(time.time()) + int(tokens.get("expires_in", 3600))

    resources = _get_accessible_resources(access_token)

    match = next((r for r in resources if (r.get("url") == JIRA_SITE_URL)), None)
    if not match and resources:
        match = resources[0]

    if not match:
        raise HTTPException(status_code=400, detail="No accessible Jira resources found for this user.")

    _save_oauth_doc({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "cloud_id": match["id"],
        "cloud_url": match["url"],
        "oauth_state": None,
    })

    return RedirectResponse(url=f"{FRONTEND_URL}/index.html?jira=connected", status_code=302)


@app.get("/oauth/atlassian/status")
def oauth_status():
    doc = _get_oauth_doc()
    if not doc:
        return {"connected": False}
    now = int(time.time())
    return {
        "connected": True,
        "cloud_url": doc.get("cloud_url"),
        "has_refresh_token": bool(doc.get("refresh_token")),
        "expires_in_seconds": max(0, int(doc.get("expires_at", 0)) - now),
    }


# -----------------------
# Jira helper endpoints
# -----------------------

@app.get("/jira/link-types")
def jira_link_types():
    auth = _ensure_valid_access_token()
    access_token = auth["access_token"]
    cloud_id = auth["cloud_id"]

    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issueLinkType"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    data = r.json()
    values = data.get("issueLinkTypes", []) if isinstance(data, dict) else []
    return [{"name": v.get("name"), "inward": v.get("inward"), "outward": v.get("outward")} for v in values]


@app.get("/jira/user-search")
def jira_user_search(q: str = Query(..., min_length=1, description="email or name fragment")):
    auth = _ensure_valid_access_token()
    access_token = auth["access_token"]
    cloud_id = auth["cloud_id"]

    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/user/search"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        params={"query": q, "maxResults": 50},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    users = r.json()
    out = []
    for u in users:
        out.append({
            "accountId": u.get("accountId"),
            "displayName": u.get("displayName"),
            "emailAddress": u.get("emailAddress"),  # may be missing/None
            "active": u.get("active"),
        })
    return out


# -----------------------
# Jira Bulk Create + optional linking
# -----------------------
def adf_from_plain(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"type": "doc", "version": 1, "content": []}

    content = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            content.append({"type": "paragraph", "content": []})
        else:
            content.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
    return {"type": "doc", "version": 1, "content": content}


def _split_issue_keys(s: str) -> List[str]:
    if not s:
        return []
    return [t.strip() for t in s.replace(",", " ").split() if t.strip()]


def _parse_bulk_index_map(resp_json: Dict[str, Any], n_updates: int) -> Dict[int, str]:
    """
    Map issueUpdates index -> created issue key, for successful ones.
    Jira bulk response has:
      - issues: list of created issues
      - errors: list containing failedElementNumber
    """
    issues = resp_json.get("issues") or []
    errors = resp_json.get("errors") or []
    failed_nums = [e.get("failedElementNumber") for e in errors if isinstance(e, dict)]
    failed_nums = [n for n in failed_nums if isinstance(n, int)]

    # Some Jira responses use 1-based failedElementNumber. Detect and normalize.
    one_based = any(n >= n_updates for n in failed_nums)
    failed = set((n - 1) if one_based else n for n in failed_nums)

    success_indices = [i for i in range(n_updates) if i not in failed]

    mapping: Dict[int, str] = {}
    for idx, issue in zip(success_indices, issues):
        key = issue.get("key")
        if key:
            mapping[idx] = key
    return mapping


def _create_issue_link(cloud_id: str, access_token: str, link_type: str, from_key: str, to_key: str) -> Dict[str, Any]:
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issueLink"
    body = {
        "type": {"name": link_type},
        "inwardIssue": {"key": from_key},   # new issue
        "outwardIssue": {"key": to_key},    # existing issue (your link_relates)
    }

    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )

    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": r.text, "from": from_key, "to": to_key, "type": link_type}

    return {"ok": True, "status": r.status_code, "from": from_key, "to": to_key, "type": link_type}


@app.post("/jira/bulk-create")
def jira_bulk_create(
    payload: Payload,
    issue_type: str = Query(..., description='Must be "Test" or "Bug" (Jira issue type names)'),
    create_links: bool = Query(False, description="If true, create links from link_relates after creation"),
):
    if issue_type not in ("Test", "Bug"):
        raise HTTPException(status_code=400, detail='issue_type must be "Test" or "Bug"')

    rows = [
        r for r in payload.rows
        if any([r.summary, r.issue_type, r.description, r.link_relates, r.assignee, r.labels, r.nsoc_team, r.severity])
    ]
    if not rows:
        raise HTTPException(status_code=400, detail="No non-empty rows to create.")
    if len(rows) > 50:
        raise HTTPException(status_code=400, detail="Bulk create supports up to 50 issues per request.")

    auth = _ensure_valid_access_token()
    access_token = auth["access_token"]
    cloud_id = auth["cloud_id"]

    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/bulk"

    issue_updates: List[Dict[str, Any]] = []
    kept_rows: List[Row] = []

    for r in rows:
        summary = (r.summary or "").strip()
        if not summary:
            continue

        labels_list = [x for x in (r.labels or "").split() if x]

        # Your UI currently sends emails. Jira wants accountId.
        # We'll use mapping (ASSIGNEE_MAP_JSON) if you set it.
        assignee_value = (r.assignee or "").strip()
        assignee_account_id = ASSIGNEE_MAP.get(assignee_value)

        fields: Dict[str, Any] = {
            "project": {"key": JIRA_PROJECT_KEY},
            "issuetype": {"name": issue_type},
            "summary": summary,
            "description": adf_from_plain(r.description),
            "labels": labels_list,
        }

        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}

        if CF_NSOC_TEAM and (r.nsoc_team or "").strip():
            fields[CF_NSOC_TEAM] = (r.nsoc_team or "").strip()

        if CF_SEVERITY and (r.severity or "").strip():
            fields[CF_SEVERITY] = (r.severity or "").strip()

        issue_updates.append({"fields": fields, "update": {}})
        kept_rows.append(r)

    if not issue_updates:
        raise HTTPException(status_code=400, detail="No valid issues (missing summary?).")

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={"issueUpdates": issue_updates},
        timeout=60,
    )

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail=f"Unauthorized calling Jira: {resp.text}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    bulk_json = resp.json()

    link_results: List[Dict[str, Any]] = []
    if create_links:
        link_type = JIRA_LINK_TYPE_TEST if issue_type == "Test" else JIRA_LINK_TYPE_BUG
        idx_to_key = _parse_bulk_index_map(bulk_json, len(issue_updates))

        for idx, row in enumerate(kept_rows):
            created_key = idx_to_key.get(idx)
            if not created_key:
                continue

            targets = _split_issue_keys(row.link_relates)
            for to_key in targets:
                link_results.append(_create_issue_link(cloud_id, access_token, link_type, created_key, to_key))

    return {"bulk_create": bulk_json, "links": link_results}
