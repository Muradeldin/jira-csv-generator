from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from typing import Any, Dict, List, Optional
import time, secrets, urllib.parse, requests
import re
from backend.models import Payload, Row
from backend.db import oauth_col
from backend.config import (
    FRONTEND_URL,
    ATLASSIAN_CLIENT_ID, ATLASSIAN_CLIENT_SECRET, ATLASSIAN_REDIRECT_URI,
    ATLASSIAN_SCOPES, JIRA_SITE_URL, JIRA_PROJECT_KEY,
    CF_NSOC_TEAM, CF_SEVERITY,
    JIRA_LINK_TYPE_TEST, JIRA_LINK_TYPE_BUG,
)

router = APIRouter(tags=["jira"])

# ---- OAuth storage helpers ----------------------------------------------------------------
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
        raise HTTPException(status_code=401, detail="Not connected. Please connect to Jira first.")

    cloud_id = doc.get("cloud_id")
    cloud_url = doc.get("cloud_url")
    if not cloud_id:
        raise HTTPException(status_code=401, detail="Connected state is incomplete (missing cloud_id). Reconnect.")

    now = int(time.time())

    # Token still valid
    if doc.get("access_token") and doc.get("expires_at", 0) > now + 60:
        return {"access_token": doc["access_token"], "cloud_id": cloud_id, "cloud_url": cloud_url}

    # Need refresh
    refresh_token = doc.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Connection Expired. Reconnect.")

    try:
        new_tokens = _refresh_access_token(refresh_token)
    except requests.HTTPError:
        # refresh token is invalid/revoked -> force login again
        _save_oauth_doc({
            "access_token": None,
            "refresh_token": None,
            "expires_at": 0,
            "oauth_state": None,
            "cloud_id": doc.get("cloud_id"),
            "cloud_url": doc.get("cloud_url"),
        })
        raise HTTPException(status_code=401, detail="Session expired. Please reconnect to Jira.")
    access_token = new_tokens["access_token"]
    refresh_token_new = new_tokens.get("refresh_token", refresh_token)
    expires_at = now + int(new_tokens.get("expires_in", 3600))

    _save_oauth_doc({
        "access_token": access_token,
        "refresh_token": refresh_token_new,
        "expires_at": expires_at,
        "cloud_id": cloud_id,
        "cloud_url": cloud_url,
        "oauth_state": None,
    })

    return {"access_token": access_token, "cloud_id": cloud_id, "cloud_url": cloud_url}


# ------------------------------------------------------------------------------------------------

# ---- Bulk create helpers -----------------------------------------------------------------------

_BOLD_RE = re.compile(r"\*(.+?)\*")  # minimal: *bold*

def _adf_inline(text: str) -> List[Dict[str, Any]]:
    """
    Convert inline *bold* into ADF text nodes with strong marks.
    Everything else stays plain text.
    """
    nodes: List[Dict[str, Any]] = []
    if text is None:
        return nodes

    last = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > last:
            nodes.append({"type": "text", "text": text[last:m.start()]})
        nodes.append({"type": "text", "text": m.group(1), "marks": [{"type": "strong"}]})
        last = m.end()

    if last < len(text):
        nodes.append({"type": "text", "text": text[last:]})

    # If the whole line was empty, ADF paragraph can have empty content []
    return [n for n in nodes if n.get("text") != ""]


def adf_from_plain(text: str) -> Dict[str, Any]:
    """
    Supported syntax:
      - Paragraphs: any normal line
      - Blank lines: paragraph break
      - Bullet list: lines starting with "- "
      - Number list: lines starting with "# "   (your choice)
      - Inline bold: *bold*
    """
    text = (text or "").rstrip("\n")
    if not text.strip():
        return {"type": "doc", "version": 1, "content": []}

    lines = text.splitlines()

    content: List[Dict[str, Any]] = []

    # Buffers for current list block
    current_list_type: str | None = None   # "bullet" | "ordered"
    list_items: List[str] = []

    def flush_list():
        nonlocal current_list_type, list_items
        if not current_list_type or not list_items:
            current_list_type = None
            list_items = []
            return

        list_node_type = "bulletList" if current_list_type == "bullet" else "orderedList"

        list_node = {
            "type": list_node_type,
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": _adf_inline(item) or []
                        }
                    ],
                }
                for item in list_items
            ],
        }
        content.append(list_node)
        current_list_type = None
        list_items = []

    def add_paragraph(line: str):
        content.append({
            "type": "paragraph",
            "content": _adf_inline(line) or []
        })

    for raw in lines:
        line = raw.rstrip()

        # blank line -> end lists, add empty paragraph (keeps spacing)
        if not line.strip():
            flush_list()
            content.append({"type": "paragraph", "content": []})
            continue

        # bullet list
        if line.startswith("- "):
            item = line[2:].strip()
            if current_list_type not in (None, "bullet"):
                flush_list()
            current_list_type = "bullet"
            list_items.append(item)
            continue

        # numeric list using "# "
        if line.startswith("# "):
            item = line[2:].strip()
            if current_list_type not in (None, "ordered"):
                flush_list()
            current_list_type = "ordered"
            list_items.append(item)
            continue

        # normal paragraph
        flush_list()
        add_paragraph(line)

    flush_list()

    return {"type": "doc", "version": 1, "content": content}


def _split_issue_keys(s: str) -> List[str]:
    if not s:
        return []
    return [t.strip() for t in s.replace(",", " ").split() if t.strip()]

def _parse_bulk_index_map(resp_json: Dict[str, Any], n_updates: int) -> Dict[int, str]:
    issues = resp_json.get("issues") or []
    errors = resp_json.get("errors") or []
    failed_nums = [e.get("failedElementNumber") for e in errors if isinstance(e, dict)]
    failed_nums = [n for n in failed_nums if isinstance(n, int)]
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
        "inwardIssue": {"key": from_key},
        "outwardIssue": {"key": to_key},
    }
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": r.text, "from": from_key, "to": to_key, "type": link_type}
    return {"ok": True, "status": r.status_code, "from": from_key, "to": to_key, "type": link_type}
# ------------------------------------------------------------------------------------------------


# ---- OAuth routes ------------------------------------------------------------------------------
@router.get("/oauth/atlassian/start")
def oauth_start():
    if not ATLASSIAN_CLIENT_ID or not ATLASSIAN_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Missing ATLASSIAN_CLIENT_ID / ATLASSIAN_CLIENT_SECRET")

    state = secrets.token_urlsafe(32)
    _save_oauth_doc({"oauth_state": state})

    params = {
        "audience": "api.atlassian.com",
        "client_id": ATLASSIAN_CLIENT_ID,
        "scope": ATLASSIAN_SCOPES,
        "redirect_uri": ATLASSIAN_REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    url = "https://auth.atlassian.com/authorize?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return RedirectResponse(url)

@router.get("/oauth/atlassian/callback")
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

@router.get("/oauth/atlassian/status")
def oauth_status():
    doc = _get_oauth_doc()
    if not doc:
        return {"connected": False}
    
    if not doc.get("access_token") and not doc.get("refresh_token"):
        return {"connected": False}

    now = int(time.time())
    expires_in = int(doc.get("expires_at", 0)) - now
    has_refresh = bool(doc.get("refresh_token"))

    # If token expired and can't refresh -> not connected
    if expires_in <= 0 and not has_refresh:
        return {"connected": False}

    return {
        "connected": True,
        "cloud_url": doc.get("cloud_url"),
        "has_refresh_token": has_refresh,
        "expires_in_seconds": max(0, expires_in),
    }
# ------------------------------------------------------------------------------------------------

# ---- Jira helper endpoints ---------------------------------------------------------------------
@router.get("/jira/user-search")
def jira_user_search(q: str = Query(..., min_length=1)):
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
    return [{
        "accountId": u.get("accountId"),
        "displayName": u.get("displayName"),
        "emailAddress": u.get("emailAddress"),
        "active": u.get("active"),
    } for u in users]
# ------------------------------------------------------------------------------------------------

# ---- Bulk create route -------------------------------------------------------------------------
@router.post("/jira/bulk-create")
def jira_bulk_create(
    payload: Payload,
    issue_type: str = Query(..., description='Must be "Test" or "Bug"'),
    create_links: bool = Query(False),
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

        assignee_value = (r.assignee or "").strip()

        fields: Dict[str, Any] = {
            "project": {"key": JIRA_PROJECT_KEY},
            "issuetype": {"name": issue_type},
            "summary": summary,
            "description": adf_from_plain(r.description),
            "labels": labels_list,
        }

        if assignee_value:
            fields["assignee"] = {"accountId": assignee_value}

        if CF_NSOC_TEAM and (r.nsoc_team or "").strip():
            fields[CF_NSOC_TEAM] = {"value": (r.nsoc_team or "").strip()}

        if CF_SEVERITY and (r.severity or "").strip():
            fields[CF_SEVERITY] = {"value": (r.severity or "").strip()}

        issue_updates.append({"fields": fields, "update": {}})
        kept_rows.append(r)

    if not issue_updates:
        raise HTTPException(status_code=400, detail="No valid issues (missing summary?).")

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "Content-Type": "application/json"},
        json={"issueUpdates": issue_updates},
        timeout=60,
    )
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail=f"Unauthorized calling Jira: {resp.text}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    bulk_json = resp.json()

    idx_to_key = _parse_bulk_index_map(bulk_json, len(issue_updates))
    created = [
        {"index": idx, "key": key}
        for idx, key in sorted(idx_to_key.items(), key=lambda x: x[0])
    ] 

    if create_links:
        link_type = JIRA_LINK_TYPE_TEST if issue_type == "Test" else JIRA_LINK_TYPE_BUG
               
        for idx, row in enumerate(kept_rows):
            created_key = idx_to_key.get(idx)
            if not created_key:
                continue
            for to_key in _split_issue_keys(row.link_relates):
                _create_issue_link(cloud_id, access_token, link_type, created_key, to_key)

    return {"created": created, "jira_base_url": auth.get("cloud_url")}

