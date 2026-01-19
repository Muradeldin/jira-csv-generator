import time, hashlib
from urllib.parse import urlencode
from typing import Any, Dict, List
import requests
import jwt

from backend.config import (
    ZEPHYR_BASE_URL, ZEPHYR_ACCESS_KEY, ZEPHYR_SECRET_KEY,
    ZEPHYR_ACCOUNT_ID, ZEPHYR_PROJECT_ID
)

def _canonical_query(params: Dict[str, str]) -> str:
    # sort params so qsh is stable
    return urlencode(sorted(params.items()))

def _qsh(method: str, path: str, query: str) -> str:
    # Zephyr/Jira-connect style qsh: SHA256("METHOD&PATH&QUERY")
    canonical = f"{method.upper()}&{path}&{query}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _make_jwt(method: str, path: str, query: str) -> str:
    now = int(time.time())
    payload = {
        "iss": ZEPHYR_ACCESS_KEY,
        "sub": ZEPHYR_ACCOUNT_ID,
        "iat": now,
        "exp": now + 300,  # keep short (5 min)
        "qsh": _qsh(method, path, query),
    }
    return jwt.encode(payload, ZEPHYR_SECRET_KEY, algorithm="HS256")

def add_test_steps(issue_id: str, steps: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Adds steps to an existing Jira Test issue in Zephyr Squad Cloud.
    Returns list of results per step (ok / error).
    Endpoint shape is commonly: /public/rest/api/1.0/teststep/{issueId}?projectId=... :contentReference[oaicite:3]{index=3}
    """
    if not steps:
        return []

    if not (ZEPHYR_ACCESS_KEY and ZEPHYR_SECRET_KEY and ZEPHYR_ACCOUNT_ID and ZEPHYR_PROJECT_ID):
        return [{"ok": False, "error": "Missing Zephyr env vars (ACCESS/SECRET/ACCOUNT_ID/PROJECT_ID)"}]

    path = f"/public/rest/api/1.0/teststep/{issue_id}"
    query = _canonical_query({"projectId": str(ZEPHYR_PROJECT_ID)})
    url = f"{ZEPHYR_BASE_URL}{path}?{query}"

    token = _make_jwt("POST", path, query)
    headers = {
        "Authorization": f"JWT {token}",
        "zapiAccessKey": ZEPHYR_ACCESS_KEY,
        "Content-Type": "application/json",
    }

    results = []
    for s in steps:
        body = {
            "step": (s.get("step") or "").strip(),
            "data": (s.get("data") or "").strip(),
            "result": (s.get("result") or "").strip(),
        }
        # skip totally empty lines
        if not (body["step"] or body["data"] or body["result"]):
            continue

        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code >= 400:
            results.append({"ok": False, "status": r.status_code, "error": r.text})
        else:
            results.append({"ok": True, "status": r.status_code})
    return results
