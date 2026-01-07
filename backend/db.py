from pymongo import MongoClient, ASCENDING, DESCENDING
from .config import MONGO_URI, MONGO_DB, MONGO_COLLECTION

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]

cases_col = db[MONGO_COLLECTION]
oauth_col = db["oauth_tokens"]

def ensure_indexes():
    cases_col.create_index([("summary", ASCENDING)])
    cases_col.create_index([("issue_type", ASCENDING)])
    cases_col.create_index([("nsoc_team", ASCENDING)])
    cases_col.create_index([("labels", ASCENDING)])
