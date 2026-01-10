from flask import Blueprint, request, make_response
from db import db
from utils import format_response

import uuid
import csv, io
from datetime import datetime
from zoneinfo import ZoneInfo

kpi_bp = Blueprint("kpi", __name__, url_prefix="/kpi")

# -----------------------------
# Timezone / Date Helpers
# -----------------------------

UTC = ZoneInfo("UTC")
DEFAULT_TZ = ZoneInfo("Asia/Kolkata")  # fallback if employee has no timezone

OFFICE_TZ_MAP = {
    "india": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "in": "Asia/Kolkata",
    "las vegas": "America/Los_Angeles",
    "vegas": "America/Los_Angeles",
    "usa": "America/Los_Angeles",
    "us": "America/Los_Angeles",
    "united states": "America/Los_Angeles",
    "america": "America/Los_Angeles",
}

def _tz_from_name(name: str | None):
    if not name:
        return DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return DEFAULT_TZ

def _normalize_employee_ids(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, (int, float)):
        return [str(raw)]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        parts = [p.strip() for p in s.replace(",", " ").split()]
        return [p for p in parts if p]
    return []

def _coerce_quality_point(raw):
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in {"-1", "neg", "negative", "minus", "bad"}:
            return -1
        if s in {"1", "pos", "positive", "plus", "good"}:
            return 1
        try:
            val = int(s)
        except Exception:
            raise ValueError("qualityPoint must be -1 or 1")
    else:
        try:
            val = int(raw)
        except Exception:
            raise ValueError("qualityPoint must be -1 or 1")

    if val not in (-1, 1):
        raise ValueError("qualityPoint must be -1 or 1")
    return val

def _as_utc(dt):
    """Convert aware/naive datetime to UTC. Naive treated as UTC (legacy)."""
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def _as_tz(dt, tz):
    return _as_utc(dt).astimezone(tz)

def _parse_date_in_tz(s: str, field_name: str, tz) -> datetime:
    """YYYY-MM-DD -> local midnight (tz-aware)."""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.replace(tzinfo=tz)
    except Exception:
        raise ValueError(f"Invalid {field_name}, must be YYYY-MM-DD")

def _end_of_day_local(local_dt: datetime) -> datetime:
    return local_dt.replace(hour=23, minute=59, second=59, microsecond=0)

def _parse_eod_in_tz(s: str, field_name: str, tz) -> datetime:
    return _end_of_day_local(_parse_date_in_tz(s, field_name, tz))

def _fmt_date_in_tz(dt, tz, f="%Y-%m-%d"):
    return _as_tz(dt, tz).strftime(f) if hasattr(dt, "strftime") else (dt if isinstance(dt, str) else None)

def _fmt_dt_in_tz(dt, tz, f="%Y-%m-%d %H:%M:%S"):
    return _as_tz(dt, tz).strftime(f) if hasattr(dt, "strftime") else (dt if isinstance(dt, str) else None)

def _fmt_iso_in_tz(dt, tz):
    return _as_tz(dt, tz).isoformat() if hasattr(dt, "isoformat") else (dt if isinstance(dt, str) else None)

def _employee_timezone(employee: dict) -> ZoneInfo:
    """
    Priority:
    1) employee['timezone'] or employee['tz'] (recommended to store)
    2) employee['office'] / 'branch' mapping (fallback)
    3) DEFAULT_TZ
    """
    tz_name = employee.get("timezone") or employee.get("tz")
    if tz_name:
        return _tz_from_name(tz_name)

    office = (employee.get("office") or employee.get("branch") or employee.get("location") or "").strip().lower()
    for key, tz in OFFICE_TZ_MAP.items():
        if key in office:
            return ZoneInfo(tz)

    return DEFAULT_TZ

def _resolve_kpi_tz(kpi: dict, employee_cache: dict[str, ZoneInfo]) -> ZoneInfo:
    tz_name = kpi.get("timezone")
    if tz_name:
        return _tz_from_name(tz_name)

    emp_id = kpi.get("employeeId")
    if emp_id and emp_id in employee_cache:
        return employee_cache[emp_id]

    if emp_id:
        emp = db.employees.find_one({"employeeId": emp_id}, {"timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1})
        if emp:
            tz = _employee_timezone(emp)
            employee_cache[emp_id] = tz
            return tz

    return DEFAULT_TZ

def _parse_filter_range_to_utc(sd: str, ed: str, tz: ZoneInfo):
    """Parse sd/ed (YYYY-MM-DD) in tz, then convert to UTC inclusive range."""
    start_local = _parse_date_in_tz(sd, "startDate", tz)
    end_local = _parse_eod_in_tz(ed, "endDate", tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)

# -----------------------------
# Routes
# -----------------------------

@kpi_bp.route("/addkpi", methods=["POST"])
def addKpi():
    data = request.get_json() or {}
    employee_id  = data.get("employeeId")
    project_name = data.get("projectName")
    deadline_str = data.get("deadline")
    remark       = data.get("Remark/comment") or data.get("Remark") or data.get("comment")

    if not all([employee_id, project_name, deadline_str]):
        return format_response(False, "Missing required fields", None, 400)

    employee = db.employees.find_one({"employeeId": employee_id})
    if not employee:
        return format_response(False, "Employee not found", None, 404)

    tz = _employee_timezone(employee)
    now_utc = datetime.now(UTC)

    try:
        deadline_local = _parse_eod_in_tz(deadline_str, "deadline", tz)
        deadline_utc = deadline_local.astimezone(UTC)
    except ValueError as ve:
        return format_response(False, str(ve), None, 400)

    kpi_id = str(uuid.uuid4())
    kpi_doc = {
        "kpiId": kpi_id,
        "employeeId": employee_id,
        "employeeName": employee.get("name"),
        "project_name": project_name,

        # ✅ Store in UTC always
        "startdate": now_utc,
        "deadline": deadline_utc,
        "timezone": tz.key,  # ✅ remember how it was intended

        "remark": remark,
        "points": -1,
        "qualityPoints": None,
        "punches": [],

        "createdAt": now_utc,
        "updatedAt": now_utc,
    }

    db.kpi.insert_one(kpi_doc)
    return format_response(True, "KPI added", {"kpiId": kpi_id}, 201)


@kpi_bp.route("/updateKPi", methods=["POST"])
def updateKpi():
    data = request.get_json() or {}
    kpi_id = data.get("kpiId")
    if not kpi_id:
        return format_response(False, "Missing KPI ID", None, 400)

    kpi = db.kpi.find_one({"kpiId": kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    updates = {}
    if "projectName" in data:
        updates["project_name"] = data["projectName"]

    remark = data.get("Remark/comment") or data.get("Remark") or data.get("comment")
    if remark is not None:
        updates["remark"] = remark

    # Optional: allow deadline update (YYYY-MM-DD) using KPI timezone
    if "deadline" in data and (data.get("deadline") or "").strip():
        tz = _tz_from_name(kpi.get("timezone"))
        try:
            dl_local = _parse_eod_in_tz(data["deadline"].strip(), "deadline", tz)
            updates["deadline"] = dl_local.astimezone(UTC)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)

    if not updates:
        return format_response(False, "No fields to update", None, 400)

    now_utc = datetime.now(UTC)
    updates["updatedAt"] = now_utc

    db.kpi.update_one({"kpiId": kpi_id}, {"$set": updates})
    kpi = db.kpi.find_one({"kpiId": kpi_id})

    tz = _tz_from_name(kpi.get("timezone"))
    payload = {
        "kpiId": kpi["kpiId"],
        "employeeId": kpi["employeeId"],
        "employeeName": kpi.get("employeeName"),
        "projectName": kpi.get("project_name"),
        "timezone": tz.key,
        "startdate": _fmt_dt_in_tz(kpi.get("startdate"), tz),
        "deadline": _fmt_dt_in_tz(kpi.get("deadline"), tz),
        "Remark": kpi.get("remark"),
        "points": kpi.get("points"),
        "createdAt": _fmt_iso_in_tz(kpi.get("createdAt"), tz),
        "updatedAt": _fmt_iso_in_tz(kpi.get("updatedAt"), tz),
    }
    return format_response(True, "KPI updated", payload, 200)


@kpi_bp.route("/punch", methods=["POST"])
def punchKpi():
    data = request.get_json(force=True) or {}
    kpi_id = data.get("kpiId")
    if not kpi_id:
        return format_response(False, "Missing kpiId", None, 400)

    kpi = db.kpi.find_one({"kpiId": kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    tz = _tz_from_name(kpi.get("timezone"))
    now_utc = datetime.now(UTC)

    deadline = kpi.get("deadline")
    on_time = isinstance(deadline, datetime) and (now_utc <= _as_utc(deadline))

    old_pts = kpi.get("points", -1)
    if on_time and old_pts == -1:
        new_pts = 1
        change = new_pts - old_pts
    else:
        new_pts = old_pts
        change = 0

    status = "On Time" if on_time else "Late Submission"

    punch_record = {
        "punchDate": now_utc,  # ✅ store UTC
        "remark": data.get("remark", ""),
        "pointChange": change,
        "status": status,
    }

    res = db.kpi.update_one(
        {"kpiId": kpi_id},
        {"$push": {"punches": punch_record},
         "$set": {"updatedAt": now_utc, "points": new_pts}},
    )
    if res.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    return format_response(True, "Punch recorded", {
        "kpiId": kpi_id,
        "timezone": tz.key,
        "punchDate": _fmt_dt_in_tz(now_utc, tz),
        "remark": punch_record["remark"],
        "pointChange": change,
        "status": status,
        "points": new_pts,
        "updatedAt": _fmt_iso_in_tz(now_utc, tz),
    }, 200)


@kpi_bp.route("/getAll", methods=["POST"])
def getAll():
    data = request.get_json() or {}

    # Pagination
    try:
        page = int(data.get("page", 1))
        page_size = int(data.get("pageSize", 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    # Optional: admin-selected timezone for filtering (not for display per-row)
    filter_tz = _tz_from_name(data.get("tz") or data.get("timezone"))  # e.g. "Asia/Kolkata"

    query = {}

    # Search
    if (s := (data.get("search") or "").strip()):
        rx = {"$regex": s, "$options": "i"}
        query["$or"] = [{"project_name": rx}, {"employeeName": rx}]

    # Employee IDs filter
    employee_ids_raw = data.get("employeeIds", data.get("employesids"))
    employee_ids = _normalize_employee_ids(employee_ids_raw)
    if employee_ids:
        query["employeeId"] = {"$in": employee_ids}

    # Date range filter (on startdate, stored UTC)
    sd = data.get("startDate")
    ed = data.get("endDate")
    if sd and ed:
        try:
            start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, filter_tz)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)
        query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

    total = db.kpi.count_documents(query)

    skip = max(0, (page - 1) * page_size)

    sort_by = (data.get("sortBy") or "createdAt").strip()
    sort_order = (data.get("sortOrder") or "desc").lower()
    sort_dir = -1 if sort_order == "desc" else 1

    allowed_sort = {"startdate", "deadline", "createdAt", "updatedAt"}
    sort_field = sort_by if sort_by in allowed_sort else "createdAt"

    cursor = (
        db.kpi.find(query)
            .sort(sort_field, sort_dir)
            .skip(skip)
            .limit(page_size)
    )

    employee_cache: dict[str, ZoneInfo] = {}

    kpis = []
    for k in cursor:
        tz = _resolve_kpi_tz(k, employee_cache)

        punches = []
        for p in k.get("punches", []):
            pd = p.get("punchDate")
            punches.append({
                "punchDate": _fmt_dt_in_tz(pd, tz),
                "remark": p.get("remark"),
                "status": p.get("status"),
            })

        kpis.append({
            "kpiId": k.get("kpiId"),
            "employeeId": k.get("employeeId"),
            "employeeName": k.get("employeeName"),
            "projectName": k.get("project_name"),
            "timezone": tz.key,

            # ✅ list view date-only (employee timezone)
            "startdate": _fmt_date_in_tz(k.get("startdate"), tz),
            "deadline": _fmt_date_in_tz(k.get("deadline"), tz),

            "Remark": k.get("remark"),
            "points": k.get("points"),
            "qualityPoints": k.get("qualityPoints"),
            "createdAt": _fmt_iso_in_tz(k.get("createdAt"), tz),
            "updatedAt": _fmt_iso_in_tz(k.get("updatedAt"), tz),
            "punches": punches,
        })

    return format_response(True, "KPIs retrieved", {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "kpis": kpis
    }, 200)


@kpi_bp.route("/deleteKpi", methods=["POST"])
def deleteKpi():
    data = request.get_json(force=True) or {}
    kpi_id = data.get("kpiId")
    if not kpi_id:
        return format_response(False, "Missing KPI ID", None, 400)

    result = db.kpi.delete_one({"kpiId": kpi_id})
    if result.deleted_count == 0:
        return format_response(False, "KPI not found", None, 404)

    return format_response(True, "KPI deleted", None, 200)


@kpi_bp.route("/getByKpiId/<kpi_id>", methods=["GET"])
def getByKpiId(kpi_id):
    kpi = db.kpi.find_one({"kpiId": kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    tz = _tz_from_name(kpi.get("timezone"))

    data = {
        "kpiId": kpi.get("kpiId"),
        "employeeId": kpi.get("employeeId"),
        "employeeName": kpi.get("employeeName"),
        "projectName": kpi.get("project_name"),
        "timezone": tz.key,
        "startdate": _fmt_dt_in_tz(kpi.get("startdate"), tz),
        "deadline": _fmt_dt_in_tz(kpi.get("deadline"), tz),
        "Remark": kpi.get("remark"),
        "points": kpi.get("points"),
        "qualityPoints": kpi.get("qualityPoints"),
        "createdAt": _fmt_iso_in_tz(kpi.get("createdAt"), tz),
        "updatedAt": _fmt_iso_in_tz(kpi.get("updatedAt"), tz),
        "punches": [{
            "punchDate": _fmt_dt_in_tz(p.get("punchDate"), tz),
            "remark": p.get("remark"),
            "status": p.get("status"),
            "pointChange": p.get("pointChange"),
        } for p in kpi.get("punches", [])]
    }
    return format_response(True, "KPI retrieved", data, 200)


@kpi_bp.route("/getByEmployeeId", methods=["POST"])
def getByEmployeeId():
    data = request.get_json() or {}
    employee_id = data.get("employeeId")
    if not employee_id:
        return format_response(False, "Missing employeeId", None, 400)

    employee = db.employees.find_one({"employeeId": employee_id})
    if not employee:
        return format_response(False, "Employee not found", None, 404)

    tz = _employee_timezone(employee)

    query = {"employeeId": employee_id}

    if (s := (data.get("search") or "").strip()):
        query["project_name"] = {"$regex": s, "$options": "i"}

    sd = data.get("startDate")
    ed = data.get("endDate")
    if sd and ed:
        try:
            start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, tz)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)
        query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

    try:
        page = int(data.get("page", 1))
        page_size = int(data.get("pageSize", 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    total = db.kpi.count_documents(query)
    skip = max(0, (page - 1) * page_size)

    cursor = (
        db.kpi.find(query)
            .sort("createdAt", -1)
            .skip(skip)
            .limit(page_size)
    )

    kpis = []
    for kpi in cursor:
        kpi_tz = _tz_from_name(kpi.get("timezone"))  # prefer KPI timezone if present, else employee tz
        if not kpi.get("timezone"):
            kpi_tz = tz

        punches_list = []
        for p in kpi.get("punches", []):
            punches_list.append({
                "punchDate": _fmt_dt_in_tz(p.get("punchDate"), kpi_tz),
                "remark": p.get("remark"),
                "status": p.get("status"),
            })

        kpis.append({
            "kpiId": kpi.get("kpiId"),
            "employeeId": kpi.get("employeeId"),
            "employeeName": kpi.get("employeeName"),
            "projectName": kpi.get("project_name"),
            "timezone": kpi_tz.key,
            "startdate": _fmt_dt_in_tz(kpi.get("startdate"), kpi_tz),
            "deadline": _fmt_dt_in_tz(kpi.get("deadline"), kpi_tz),
            "Remark": kpi.get("remark"),
            "points": kpi.get("points"),
            "qualityPoints": kpi.get("qualityPoints"),
            "createdAt": _fmt_iso_in_tz(kpi.get("createdAt"), kpi_tz),
            "updatedAt": _fmt_iso_in_tz(kpi.get("updatedAt"), kpi_tz),
            "punches": punches_list,
        })

    return format_response(True, f"Found {len(kpis)} KPI(s) for employee {employee_id}", {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "kpis": kpis,
    }, 200)


@kpi_bp.route("/setQualityPoint", methods=["POST"])
def add_quality_points():
    data = request.get_json(force=True) or {}
    kpi_id = data.get("kpiId") or data.get("kpi_id")
    qp_raw = data.get("qualityPoint") or data.get("qualityPoints") or data.get("quality_point")

    if not kpi_id or qp_raw is None:
        return format_response(False, "Missing kpiId or qualityPoint", None, 400)

    try:
        qp = _coerce_quality_point(qp_raw)
    except ValueError as e:
        return format_response(False, str(e), None, 400)

    now_utc = datetime.now(UTC)
    res = db.kpi.update_one(
        {"kpiId": kpi_id},
        {"$set": {"qualityPoints": qp, "updatedAt": now_utc}}
    )
    if res.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    kpi = db.kpi.find_one({"kpiId": kpi_id}, {"timezone": 1})
    tz = _tz_from_name((kpi or {}).get("timezone"))

    return format_response(True, "Quality points saved", {
        "kpiId": kpi_id,
        "qualityPoints": qp,
        "timezone": tz.key,
        "updatedAt": _fmt_iso_in_tz(now_utc, tz),
    }, 200)


@kpi_bp.route("/exportCsv", methods=["POST"])
def export_csv():
    """
    Export KPIs as CSV.
    - Uses same filters as getAll/getByEmployeeId
    - Stores UTC but exports in each KPI timezone (and includes Timezone column).
    - Excludes ID fields (kpiId, employeeId).
    """
    data = request.get_json() or {}

    search = (data.get("search") or "").strip()
    sd = data.get("startDate")
    ed = data.get("endDate")
    sort_by = (data.get("sortBy") or "createdAt").strip()
    sort_order = (data.get("sortOrder") or "desc").lower()
    sort_dir = -1 if sort_order == "desc" else 1

    try:
        page = int(data.get("page", 1))
        page_size = int(data.get("pageSize", 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    export_all = bool(data.get("all") or data.get("exportAll"))

    query = {}

    # Employee filter: allow employeeId (single/many)
    employee_ids = _normalize_employee_ids(data.get("employeeId"))
    if employee_ids:
        query["employeeId"] = employee_ids[0] if len(employee_ids) == 1 else {"$in": employee_ids}

    if search:
        rx = {"$regex": search, "$options": "i"}
        query["$or"] = [{"project_name": rx}, {"employeeName": rx}]

    # For global export filter range, use request timezone (admin)
    filter_tz = _tz_from_name(data.get("tz") or data.get("timezone"))
    if sd and ed:
        try:
            start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, filter_tz)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)
        query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

    allowed_sort = {"startdate", "deadline", "createdAt", "updatedAt"}
    sort_field = sort_by if sort_by in allowed_sort else "createdAt"

    cursor = db.kpi.find(query).sort(sort_field, sort_dir)

    if not export_all:
        skip = max(0, (page - 1) * page_size)
        cursor = cursor.skip(skip).limit(page_size)

    employee_cache: dict[str, ZoneInfo] = {}

    fieldnames = [
        "EmployeeName", "ProjectName", "Timezone",
        "StartDate", "Deadline",
        "Remark", "DeadlinePoints", "QualityPoints",
        "LastPunchDate", "LastPunchStatus", "LastPunchRemark"
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for k in cursor:
        tz = _resolve_kpi_tz(k, employee_cache)

        punches = k.get("punches", [])
        last = punches[-1] if punches else {}
        lp_date = last.get("punchDate")

        writer.writerow({
            "EmployeeName": k.get("employeeName", ""),
            "ProjectName": k.get("project_name", ""),
            "Timezone": tz.key,
            "StartDate": _fmt_dt_in_tz(k.get("startdate"), tz) or "",
            "Deadline": _fmt_dt_in_tz(k.get("deadline"), tz) or "",
            "Remark": k.get("remark", ""),
            "DeadlinePoints": k.get("points", ""),
            "QualityPoints": k.get("qualityPoints", ""),
            "LastPunchDate": _fmt_dt_in_tz(lp_date, tz) or "",
            "LastPunchStatus": last.get("status") or "",
            "LastPunchRemark": last.get("remark") or "",
        })

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="kpi_export_{ts}.csv"'
    return resp
