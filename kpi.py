import re
import uuid
import csv, io
from datetime import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from flask import Blueprint, request, make_response
from flask_jwt_extended import jwt_required, get_jwt

from db import db
from utils import format_response

kpi_bp = Blueprint("kpi", __name__, url_prefix="/kpi")

UTC = ZoneInfo("UTC")
DEFAULT_TZ = ZoneInfo("Asia/Kolkata")

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

# ======================================================
# Auth / Scope Helpers (ZONE + KPI rules)
# ======================================================

def _scope():
    """
    JWT claims expected:
      role: admin/subadmin/employee...
      zoneIds: list of allowed zoneIds (admin can be ["*"] or empty)
      employeeId: caller employeeId (for subadmin and employee)
      permissions: dict with "KPI" and/or "Manage KPI"
    """
    claims = get_jwt() or {}
    role = (claims.get("role") or "").lower()
    zone_ids = claims.get("zoneIds") or []
    perms = claims.get("permissions") or {}
    is_admin_all = role == "admin" and (not zone_ids or "*" in zone_ids)
    return role, zone_ids, perms, is_admin_all

def _caller_employee_id() -> str:
    claims = get_jwt() or {}
    return (claims.get("employeeId") or "").strip()

def _kpi_mode():
    """
    Returns:
      - "admin"  : role == admin
      - "manage" : Manage KPI permission
      - "self"   : KPI permission only (self-only)
    """
    claims = get_jwt() or {}
    role = (claims.get("role") or "").lower()
    perms = claims.get("permissions") or {}

    if role == "admin":
        return "admin"
    if int(perms.get("Manage KPI", 0)) == 1:
        return "manage"
    if int(perms.get("KPI", 0)) == 1:
        return "self"
    raise PermissionError("Permission denied (KPI)")

def _require_manage_kpi():
    """Only Admin or Manage KPI can access."""
    mode = _kpi_mode()
    if mode not in ("admin", "manage"):
        raise PermissionError("Permission denied (Manage KPI required)")

def _zone_query(field="zoneId") -> dict:
    """Mongo filter enforcing zone scope."""
    _role, zone_ids, _perms, is_admin_all = _scope()
    if is_admin_all:
        return {}
    return {field: {"$in": zone_ids}}

def _ensure_zone_allowed(zone_id: Optional[str]):
    """Raise 403 if zone_id not in caller zone scope (unless admin-all)."""
    _role, zone_ids, _perms, is_admin_all = _scope()
    if is_admin_all:
        return
    if not zone_id or zone_id not in zone_ids:
        raise PermissionError("Forbidden (different zone)")

# ======================================================
# Timezone Helpers (UTC storage)
# ======================================================

def _now_utc() -> datetime:
    return datetime.now(UTC)

def _tz_from_name(name: Optional[str]) -> ZoneInfo:
    if not name:
        return DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return DEFAULT_TZ

def _tz_key(tz: ZoneInfo) -> str:
    return getattr(tz, "key", str(tz))

def _employee_timezone(employee: Dict[str, Any]) -> ZoneInfo:
    tz_name = employee.get("timezone") or employee.get("tz")
    if tz_name:
        return _tz_from_name(tz_name)

    office = (employee.get("office") or employee.get("branch") or employee.get("location") or "").strip().lower()
    for key, tz in OFFICE_TZ_MAP.items():
        if key in office:
            return ZoneInfo(tz)

    return DEFAULT_TZ

def _as_utc(dt):
    """Ensure datetime is UTC aware. If naive, treat as UTC (legacy)."""
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def _as_tz(dt, tz: ZoneInfo):
    return _as_utc(dt).astimezone(tz) if isinstance(dt, datetime) else dt

def _parse_date_in_tz(s: str, field_name: str, tz: ZoneInfo) -> datetime:
    """YYYY-MM-DD -> tz-aware local midnight"""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.replace(tzinfo=tz)
    except Exception:
        raise ValueError(f"Invalid {field_name}, must be YYYY-MM-DD")

def _end_of_day_local(local_dt: datetime) -> datetime:
    return local_dt.replace(hour=23, minute=59, second=59, microsecond=0)

def _parse_eod_in_tz(s: str, field_name: str, tz: ZoneInfo) -> datetime:
    return _end_of_day_local(_parse_date_in_tz(s, field_name, tz))

def _fmt_date_in_tz(dt, tz: ZoneInfo, f="%Y-%m-%d"):
    return _as_tz(dt, tz).strftime(f) if isinstance(dt, datetime) else (dt if isinstance(dt, str) else None)

def _fmt_dt_in_tz(dt, tz: ZoneInfo, f="%Y-%m-%d %H:%M:%S"):
    return _as_tz(dt, tz).strftime(f) if isinstance(dt, datetime) else (dt if isinstance(dt, str) else None)

def _fmt_iso_in_tz(dt, tz: ZoneInfo):
    return _as_tz(dt, tz).isoformat() if isinstance(dt, datetime) else (dt if isinstance(dt, str) else None)

def _parse_filter_range_to_utc(sd: str, ed: str, tz: ZoneInfo):
    """Parse start/end in request timezone -> convert to UTC inclusive range."""
    start_local = _parse_date_in_tz(sd, "startDate", tz)
    end_local = _parse_eod_in_tz(ed, "endDate", tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)

def _normalize_employee_ids(raw) -> List[str]:
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
    try:
        val = int(raw)
    except Exception:
        raise ValueError("qualityPoint must be -1 or 1")
    if val not in (-1, 1):
        raise ValueError("qualityPoint must be -1 or 1")
    return val

# ======================================================
# KPI Permission Logic (SELF vs MANAGE by TIMEZONE)
# ======================================================

def _caller_timezone_key() -> str:
    """
    Caller timezone derived from employees collection via JWT employeeId.
    Used for Manage KPI filtering (same-timezone employees only).
    """
    emp_id = _caller_employee_id()
    if not emp_id:
        return _tz_key(DEFAULT_TZ)

    emp = db.employees.find_one(
        {"employeeId": emp_id},
        {"timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1}
    ) or {}

    tz = _employee_timezone(emp)
    return _tz_key(tz)

def _ensure_employee_scope(employee_doc: dict):
    """
    Enforces:
      - ZONE scope
      - KPI/self  -> only caller's own employeeId
      - Manage KPI -> only employees with SAME timezone as caller
      - Admin -> bypass (still zone scoped unless admin-all)
    """
    mode = _kpi_mode()

    # Always enforce zone scope (unless admin-all)
    _ensure_zone_allowed(employee_doc.get("zoneId"))

    if mode == "admin":
        return

    if mode == "self":
        if employee_doc.get("employeeId") != _caller_employee_id():
            raise PermissionError("Forbidden: KPI permission allows self-only")

    if mode == "manage":
        caller_tz = _caller_timezone_key()
        target_tz = _tz_key(_employee_timezone(employee_doc))
        if target_tz != caller_tz:
            raise PermissionError("Forbidden: Manage KPI allows same-timezone employees only")

def _resolve_employee_id_from_request(data: dict) -> str:
    """
    If mode=self -> force employeeId from JWT.
    Else -> take from request.
    """
    mode = _kpi_mode()
    if mode == "self":
        emp_id = _caller_employee_id()
        if not emp_id:
            raise PermissionError("Missing employeeId in token")
        return emp_id
    emp_id = (data.get("employeeId") or "").strip()
    if not emp_id:
        raise ValueError("Missing employeeId")
    return emp_id

# ======================================================
# Legacy Auto-fix (safe migration on read)
# ======================================================

def _ensure_kpi_has_zone_and_timezone(kpi: Dict[str, Any]) -> Dict[str, Any]:
    """
    If old KPI docs are missing zoneId/timezone, derive from employee and update once.
    """
    updates = {}
    zone_id = kpi.get("zoneId")
    tz_name = kpi.get("timezone")

    if (not zone_id) or (not tz_name):
        emp = db.employees.find_one(
            {"employeeId": kpi.get("employeeId")},
            {"zoneId": 1, "timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1, "name": 1}
        )
        if emp:
            if not zone_id and emp.get("zoneId"):
                zone_id = emp.get("zoneId")
                updates["zoneId"] = zone_id
            if not tz_name:
                tz = _employee_timezone(emp)
                tz_name = _tz_key(tz)
                updates["timezone"] = tz_name
            if not kpi.get("employeeName") and emp.get("name"):
                updates["employeeName"] = emp.get("name")

    if updates:
        db.kpi.update_one({"kpiId": kpi.get("kpiId")}, {"$set": updates})
        kpi = {**kpi, **updates}

    return kpi

# ======================================================
# Routes
# ======================================================

@kpi_bp.route("/addkpi", methods=["POST"])
@jwt_required()
def addKpi():
    try:
        data = request.get_json(force=True) or {}

        employee_id = _resolve_employee_id_from_request(data)
        project_name = (data.get("projectName") or "").strip()
        deadline_str = (data.get("deadline") or "").strip()
        remark = data.get("Remark/comment") or data.get("Remark") or data.get("comment") or ""

        if not project_name or not deadline_str:
            return format_response(False, "Missing required fields: projectName, deadline", None, 400)

        employee = db.employees.find_one({"employeeId": employee_id})
        if not employee:
            return format_response(False, "Employee not found", None, 404)

        # ✅ enforce self-only OR same-timezone OR admin
        _ensure_employee_scope(employee)

        tz = _employee_timezone(employee)
        now_utc = _now_utc()

        try:
            deadline_local = _parse_eod_in_tz(deadline_str, "deadline", tz)
            deadline_utc = deadline_local.astimezone(UTC)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)

        kpi_id = str(uuid.uuid4())
        kpi_doc = {
            "kpiId": kpi_id,
            "zoneId": employee.get("zoneId"),
            "employeeId": employee_id,
            "employeeName": employee.get("name"),
            "project_name": project_name,

            # store UTC
            "startdate": now_utc,
            "deadline": deadline_utc,

            # remember intended timezone (for display + manager filtering)
            "timezone": _tz_key(tz),

            "remark": remark,
            "points": -1,
            "qualityPoints": None,
            "punches": [],
            "createdAt": now_utc,
            "updatedAt": now_utc,
        }

        db.kpi.insert_one(kpi_doc)
        return format_response(True, "KPI added", {"kpiId": kpi_id}, 201)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except ValueError as e:
        return format_response(False, str(e), None, 400)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/updateKPi", methods=["POST"])
@jwt_required()
def updateKpi():
    try:
        data = request.get_json(force=True) or {}
        kpi_id = (data.get("kpiId") or "").strip()
        if not kpi_id:
            return format_response(False, "Missing kpiId", None, 400)

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        # ✅ enforce zone + self/manage rules based on KPI employee
        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")}) or {}
        if emp:
            _ensure_employee_scope(emp)
        else:
            # fallback: at least enforce zone
            _ensure_zone_allowed(kpi.get("zoneId"))

        updates = {}

        if "projectName" in data and (data.get("projectName") or "").strip():
            updates["project_name"] = data.get("projectName").strip()

        remark = data.get("Remark/comment") or data.get("Remark") or data.get("comment")
        if remark is not None:
            updates["remark"] = remark

        # deadline update uses KPI timezone for consistency
        if "deadline" in data and (data.get("deadline") or "").strip():
            tz = _tz_from_name(kpi.get("timezone"))
            try:
                dl_local = _parse_eod_in_tz(data["deadline"].strip(), "deadline", tz)
                updates["deadline"] = dl_local.astimezone(UTC)
            except ValueError as ve:
                return format_response(False, str(ve), None, 400)

        if not updates:
            return format_response(False, "No fields to update", None, 400)

        updates["updatedAt"] = _now_utc()
        db.kpi.update_one({"kpiId": kpi_id}, {"$set": updates})

        return format_response(True, "KPI updated", {"kpiId": kpi_id}, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/punch", methods=["POST"])
@jwt_required()
def punchKpi():
    try:
        data = request.get_json(force=True) or {}
        kpi_id = (data.get("kpiId") or "").strip()
        if not kpi_id:
            return format_response(False, "Missing kpiId", None, 400)

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        # ✅ enforce zone + self/manage rules based on KPI employee
        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")}) or {}
        if emp:
            _ensure_employee_scope(emp)
        else:
            _ensure_zone_allowed(kpi.get("zoneId"))

        now_utc = _now_utc()
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
            "punchDate": now_utc,  # store UTC
            "remark": data.get("remark", "") or "",
            "pointChange": change,
            "status": status,
        }

        db.kpi.update_one(
            {"kpiId": kpi_id},
            {
                "$push": {"punches": punch_record},
                "$set": {"updatedAt": now_utc, "points": new_pts}
            }
        )

        tz = _tz_from_name(kpi.get("timezone"))
        return format_response(True, "Punch recorded", {
            "kpiId": kpi_id,
            "timezone": _tz_key(tz),
            "punchDate": _fmt_dt_in_tz(now_utc, tz),
            "status": status,
            "pointChange": change,
            "points": new_pts,
            "updatedAt": _fmt_iso_in_tz(now_utc, tz),
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/getAll", methods=["POST"])
@jwt_required()
def getAll():
    """
    Manager/Admin list.
    - Manage KPI: only same-timezone KPIs (within zone scope)
    - Admin: all KPIs within zone scope (or all zones if admin-all)
    """
    try:
        _require_manage_kpi()

        data = request.get_json(force=True) or {}

        # Pagination
        try:
            page = max(int(data.get("page", 1)), 1)
            page_size = max(int(data.get("pageSize", 10)), 1)
        except (TypeError, ValueError):
            return format_response(False, "Invalid pagination parameters", None, 400)

        filter_tz = _tz_from_name(data.get("tz") or data.get("timezone"))

        query = {}
        query.update(_zone_query("zoneId"))

        # ✅ Manage KPI: same timezone only (KPI docs store timezone)
        if _kpi_mode() == "manage":
            query["timezone"] = _caller_timezone_key()

        # Search
        if (s := (data.get("search") or "").strip()):
            rx = {"$regex": re.escape(s), "$options": "i"}
            query["$or"] = [{"project_name": rx}, {"employeeName": rx}, {"employeeId": rx}]

        # Employee IDs filter
        employee_ids = _normalize_employee_ids(data.get("employeeIds", data.get("employesids")))
        if employee_ids:
            query["employeeId"] = {"$in": employee_ids}

        # Date range filter (on startdate stored UTC)
        sd = (data.get("startDate") or "").strip()
        ed = (data.get("endDate") or "").strip()
        if sd and ed:
            try:
                start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, filter_tz)
            except ValueError as ve:
                return format_response(False, str(ve), None, 400)
            query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

        # Sorting
        sort_by = (data.get("sortBy") or "createdAt").strip()
        sort_order = (data.get("sortOrder") or "desc").lower()
        sort_dir = -1 if sort_order == "desc" else 1
        allowed_sort = {"startdate", "deadline", "createdAt", "updatedAt"}
        sort_field = sort_by if sort_by in allowed_sort else "createdAt"

        total = db.kpi.count_documents(query)
        skip = (page - 1) * page_size

        cursor = (
            db.kpi.find(query)
                .sort(sort_field, sort_dir)
                .skip(skip)
                .limit(page_size)
        )

        include_punches = bool(data.get("includePunches"))
        include_last_punch = bool(data.get("includeLastPunch", True))

        out = []
        for k in cursor:
            k = _ensure_kpi_has_zone_and_timezone(k)

            tz = _tz_from_name(k.get("timezone"))
            punches = k.get("punches", []) or []
            last = punches[-1] if punches else {}

            row = {
                "kpiId": k.get("kpiId"),
                "zoneId": k.get("zoneId"),
                "employeeId": k.get("employeeId"),
                "employeeName": k.get("employeeName"),
                "projectName": k.get("project_name"),
                "timezone": _tz_key(tz),

                "startdate": _fmt_date_in_tz(k.get("startdate"), tz),
                "deadline": _fmt_date_in_tz(k.get("deadline"), tz),

                "Remark": k.get("remark"),
                "points": k.get("points"),
                "qualityPoints": k.get("qualityPoints"),
                "createdAt": _fmt_iso_in_tz(k.get("createdAt"), tz),
                "updatedAt": _fmt_iso_in_tz(k.get("updatedAt"), tz),
            }

            if include_last_punch:
                lp = last.get("punchDate")
                row["lastPunchDate"] = _fmt_dt_in_tz(lp, tz) if lp else None
                row["lastPunchStatus"] = last.get("status")
                row["lastPunchRemark"] = last.get("remark")

            if include_punches:
                row["punches"] = [{
                    "punchDate": _fmt_dt_in_tz(p.get("punchDate"), tz),
                    "remark": p.get("remark"),
                    "status": p.get("status"),
                    "pointChange": p.get("pointChange"),
                } for p in punches]

            out.append(row)

        return format_response(True, "KPIs retrieved", {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": (total + page_size - 1) // page_size if page_size else 0,
            "kpis": out
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/getByKpiId/<kpi_id>", methods=["GET"])
@jwt_required()
def getByKpiId(kpi_id):
    try:
        _kpi_mode()

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        # ✅ enforce zone + self/manage rules based on KPI employee
        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")}) or {}
        if emp:
            _ensure_employee_scope(emp)
        else:
            _ensure_zone_allowed(kpi.get("zoneId"))

        tz = _tz_from_name(kpi.get("timezone"))
        punches = kpi.get("punches", []) or []

        payload = {
            "kpiId": kpi.get("kpiId"),
            "zoneId": kpi.get("zoneId"),
            "employeeId": kpi.get("employeeId"),
            "employeeName": kpi.get("employeeName"),
            "projectName": kpi.get("project_name"),
            "timezone": _tz_key(tz),

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
            } for p in punches]
        }

        return format_response(True, "KPI retrieved", payload, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/getByEmployeeId", methods=["POST"])
@jwt_required()
def getByEmployeeId():
    """
    KPI/self:
      - only own employeeId (forced from JWT)
    Manage KPI/Admin:
      - can query employeeId, but must pass same-timezone (manage) + zone checks
    """
    try:
        data = request.get_json(force=True) or {}
        mode = _kpi_mode()

        if mode == "self":
            employee_id = _caller_employee_id()
            if not employee_id:
                return format_response(False, "Missing employeeId in token", None, 403)
        else:
            employee_id = (data.get("employeeId") or "").strip()

        if not employee_id:
            return format_response(False, "Missing employeeId", None, 400)

        employee = db.employees.find_one({"employeeId": employee_id})
        if not employee:
            return format_response(False, "Employee not found", None, 404)

        # ✅ enforce self/manage rules and zone
        _ensure_employee_scope(employee)

        emp_tz = _employee_timezone(employee)

        query = {
            "employeeId": employee_id,
            "zoneId": employee.get("zoneId"),
        }

        # Manage KPI: ensure KPI docs are same timezone too
        if mode == "manage":
            query["timezone"] = _caller_timezone_key()

        if (s := (data.get("search") or "").strip()):
            query["project_name"] = {"$regex": re.escape(s), "$options": "i"}

        sd = (data.get("startDate") or "").strip()
        ed = (data.get("endDate") or "").strip()
        if sd and ed:
            try:
                start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, emp_tz)
            except ValueError as ve:
                return format_response(False, str(ve), None, 400)
            query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

        page = max(int(data.get("page", 1)), 1)
        page_size = max(int(data.get("pageSize", 10)), 1)
        skip = (page - 1) * page_size

        total = db.kpi.count_documents(query)
        cursor = (
            db.kpi.find(query)
                .sort("createdAt", -1)
                .skip(skip)
                .limit(page_size)
        )

        out = []
        for k in cursor:
            k = _ensure_kpi_has_zone_and_timezone(k)
            tz = _tz_from_name(k.get("timezone")) or emp_tz
            punches = k.get("punches", []) or []

            out.append({
                "kpiId": k.get("kpiId"),
                "zoneId": k.get("zoneId"),
                "employeeId": k.get("employeeId"),
                "employeeName": k.get("employeeName"),
                "projectName": k.get("project_name"),
                "timezone": _tz_key(tz),

                "startdate": _fmt_dt_in_tz(k.get("startdate"), tz),
                "deadline": _fmt_dt_in_tz(k.get("deadline"), tz),

                "Remark": k.get("remark"),
                "points": k.get("points"),
                "qualityPoints": k.get("qualityPoints"),
                "createdAt": _fmt_iso_in_tz(k.get("createdAt"), tz),
                "updatedAt": _fmt_iso_in_tz(k.get("updatedAt"), tz),

                "punches": [{
                    "punchDate": _fmt_dt_in_tz(p.get("punchDate"), tz),
                    "remark": p.get("remark"),
                    "status": p.get("status"),
                    "pointChange": p.get("pointChange"),
                } for p in punches]
            })

        return format_response(True, f"Found {len(out)} KPI(s) for employee {employee_id}", {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": (total + page_size - 1) // page_size if page_size else 0,
            "kpis": out,
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/setQualityPoint", methods=["POST"])
@jwt_required()
def add_quality_points():
    try:
        _require_manage_kpi()  # ✅ only admin/manage

        data = request.get_json(force=True) or {}
        kpi_id = (data.get("kpiId") or data.get("kpi_id") or "").strip()
        qp_raw = data.get("qualityPoint") or data.get("qualityPoints") or data.get("quality_point")

        if not kpi_id or qp_raw is None:
            return format_response(False, "Missing kpiId or qualityPoint", None, 400)

        qp = _coerce_quality_point(qp_raw)

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        # ✅ enforce manage timezone scope + zone scope
        if _kpi_mode() == "manage":
            if kpi.get("timezone") != _caller_timezone_key():
                raise PermissionError("Forbidden: Manage KPI allows same-timezone employees only")

        _ensure_zone_allowed(kpi.get("zoneId"))

        now_utc = _now_utc()
        db.kpi.update_one(
            {"kpiId": kpi_id},
            {"$set": {"qualityPoints": qp, "updatedAt": now_utc}}
        )

        tz = _tz_from_name(kpi.get("timezone"))
        return format_response(True, "Quality points saved", {
            "kpiId": kpi_id,
            "qualityPoints": qp,
            "timezone": _tz_key(tz),
            "updatedAt": _fmt_iso_in_tz(now_utc, tz),
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except ValueError as e:
        return format_response(False, str(e), None, 400)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/deleteKpi", methods=["POST"])
@jwt_required()
def deleteKpi():
    try:
        _require_manage_kpi()  # ✅ only admin/manage

        data = request.get_json(force=True) or {}
        kpi_id = (data.get("kpiId") or "").strip()
        if not kpi_id:
            return format_response(False, "Missing kpiId", None, 400)

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        # ✅ enforce manage timezone scope + zone scope
        if _kpi_mode() == "manage":
            if kpi.get("timezone") != _caller_timezone_key():
                raise PermissionError("Forbidden: Manage KPI allows same-timezone employees only")

        _ensure_zone_allowed(kpi.get("zoneId"))

        res = db.kpi.delete_one({"kpiId": kpi_id})
        if not res.deleted_count:
            return format_response(False, "KPI not found", None, 404)

        return format_response(True, "KPI deleted", None, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/exportCsv", methods=["POST"])
@jwt_required()
def export_csv():
    """
    Manager/Admin export.
    Manage KPI:
      - only same-timezone KPIs (within zone scope)
    Admin:
      - all KPIs in zone scope (or all zones if admin-all)
    """
    try:
        _require_manage_kpi()

        data = request.get_json(force=True) or {}

        search = (data.get("search") or "").strip()
        sd = (data.get("startDate") or "").strip()
        ed = (data.get("endDate") or "").strip()

        filter_tz = _tz_from_name(data.get("tz") or data.get("timezone"))

        sort_by = (data.get("sortBy") or "createdAt").strip()
        sort_order = (data.get("sortOrder") or "desc").lower()
        sort_dir = -1 if sort_order == "desc" else 1
        allowed_sort = {"startdate", "deadline", "createdAt", "updatedAt"}
        sort_field = sort_by if sort_by in allowed_sort else "createdAt"

        page = max(int(data.get("page", 1)), 1)
        page_size = max(int(data.get("pageSize", 10)), 1)
        export_all = bool(data.get("all") or data.get("exportAll"))

        query = {}
        query.update(_zone_query("zoneId"))

        # ✅ Manage KPI: same timezone only
        if _kpi_mode() == "manage":
            query["timezone"] = _caller_timezone_key()

        emp_single = (data.get("employeeId") or "").strip()
        emp_list = _normalize_employee_ids(data.get("employeeIds"))

        if emp_single:
            query["employeeId"] = emp_single
        elif emp_list:
            query["employeeId"] = {"$in": emp_list}

        if search:
            rx = {"$regex": re.escape(search), "$options": "i"}
            query["$or"] = [{"project_name": rx}, {"employeeName": rx}, {"employeeId": rx}]

        if sd and ed:
            try:
                start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, filter_tz)
            except ValueError as ve:
                return format_response(False, str(ve), None, 400)
            query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

        cursor = db.kpi.find(query).sort(sort_field, sort_dir)
        if not export_all:
            skip = (page - 1) * page_size
            cursor = cursor.skip(skip).limit(page_size)

        fieldnames = [
            "EmployeeName", "EmployeeId", "ZoneId",
            "ProjectName", "Timezone",
            "StartDate", "Deadline",
            "Remark", "DeadlinePoints", "QualityPoints",
            "LastPunchDate", "LastPunchStatus", "LastPunchRemark"
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for k in cursor:
            k = _ensure_kpi_has_zone_and_timezone(k)
            tz = _tz_from_name(k.get("timezone"))
            punches = k.get("punches", []) or []
            last = punches[-1] if punches else {}
            lp_date = last.get("punchDate")

            writer.writerow({
                "EmployeeName": k.get("employeeName", ""),
                "EmployeeId": k.get("employeeId", ""),
                "ZoneId": k.get("zoneId", ""),
                "ProjectName": k.get("project_name", ""),
                "Timezone": _tz_key(tz),

                "StartDate": _fmt_dt_in_tz(k.get("startdate"), tz) or "",
                "Deadline": _fmt_dt_in_tz(k.get("deadline"), tz) or "",

                "Remark": k.get("remark", ""),
                "DeadlinePoints": k.get("points", ""),
                "QualityPoints": k.get("qualityPoints", ""),

                "LastPunchDate": _fmt_dt_in_tz(lp_date, tz) or "",
                "LastPunchStatus": last.get("status") or "",
                "LastPunchRemark": last.get("remark") or "",
            })

        resp = make_response(output.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = 'attachment; filename="kpi_export.csv"'
        return resp

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)
