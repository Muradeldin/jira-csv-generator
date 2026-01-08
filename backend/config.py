import os, json

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8079")

# ---------- MongoDB ----------
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

# ---------- Atlassian / Jira ----------
ATLASSIAN_CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID", "")
ATLASSIAN_CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET", "")
ATLASSIAN_REDIRECT_URI = os.getenv("ATLASSIAN_REDIRECT_URI", "http://localhost:8000/oauth/atlassian/callback")

JIRA_SITE_URL = os.getenv("JIRA_SITE_URL", "https://rnd-hub.atlassian.net")
ATLASSIAN_SCOPES = os.getenv("ATLASSIAN_SCOPES", "write:jira-work read:jira-user offline_access")

JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "NSOC")

CF_NSOC_TEAM = os.getenv("CF_NSOC_TEAM", "customfield_10337")
CF_SEVERITY  = os.getenv("CF_SEVERITY",  "customfield_10300")

JIRA_LINK_TYPE_TEST = os.getenv("JIRA_LINK_TYPE_TEST", "Relates")
JIRA_LINK_TYPE_BUG  = os.getenv("JIRA_LINK_TYPE_BUG",  "Problem/Incident")