"""
One-time migration: set employees.timezone
Rule:
  - employeeId == 51 OR "51"  -> America/Los_Angeles
  - everyone else             -> Asia/Kolkata

✅ Uses your MongoDB Atlas URI.

Run:
  pip install "pymongo[srv]"
  python set_employee_timezones.py

Optional:
  export TARGET_DB=Invoice   # if your DB name is different
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pymongo import MongoClient

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb+srv://Invoice:Invoice123@invoice.nlglhbe.mongodb.net/?retryWrites=true&w=majority&appName=Invoice"
)

UTC = ZoneInfo("UTC")
SYSTEM_DBS = {"admin", "local", "config"}


def pick_database(client: MongoClient) -> str:
    """
    Auto-pick DB safely:
      1) If TARGET_DB env is set -> use it
      2) If 'invoice' exists -> use it
      3) If 'Invoice' exists -> use it
      4) If exactly one non-system DB exists -> use it
      5) Else raise with list so you can set TARGET_DB
    """
    forced = (os.getenv("TARGET_DB") or "").strip()
    if forced:
        return forced

    dbs = [d["name"] for d in client.list_databases()]
    candidates = [d for d in dbs if d not in SYSTEM_DBS]

    if "invoice" in candidates:
        return "invoice"
    if "Invoice" in candidates:
        return "Invoice"
    if len(candidates) == 1:
        return candidates[0]

    raise RuntimeError(
        "Could not auto-pick database. Available DBs: "
        + ", ".join(candidates)
        + " | Set env TARGET_DB to the correct one."
    )


def main():
    client = MongoClient(MONGODB_URI)
    try:
        db_name = pick_database(client)
        db = client[db_name]

        employees = db["employees"]
        now = datetime.now(UTC)

        res_all = employees.update_many(
            {},
            {"$set": {"timezone": "Asia/Kolkata", "updated_at": now}}
        )

        res_51 = employees.update_many(
            {"employeeId": {"$in": [51, "51"]}},
            {"$set": {"timezone": "America/Los_Angeles", "updated_at": now}}
        )

        print("✅ Timezone migration done")
        print(f"DB: {db_name}, Collection: employees")
        print(f"All employees  -> matched={res_all.matched_count}, modified={res_all.modified_count}")
        print(f"EmployeeId 51  -> matched={res_51.matched_count}, modified={res_51.modified_count}")

        sample = employees.find_one(
            {"employeeId": {"$in": [51, "51"]}},
            {"_id": 0, "employeeId": 1, "name": 1, "timezone": 1}
        )
        print("Employee 51 sample:", sample)

    finally:
        client.close()

if __name__ == "__main__":
    main()
