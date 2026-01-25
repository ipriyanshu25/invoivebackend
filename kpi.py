import re
import uuid
import csv
import io
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from zoneinfo import ZoneInfo

from flask import Blueprint, request, make_response
from flask_jwt_extended import jwt_required, get_jwt

from db import db
from utils import format_response

kpi_bp = Blueprint("kpi", __name__, url_prefix="/kpi")

UTC = ZoneInfo("UTC")
DEFAULT_TZ = ZoneInfo("Asia/Kolkata")

# If you have legacy timezone names in DB, map them to canonical ones
TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "US/Pacific": "America/Los_Angeles",
    "PST8PDT": "America/Los_Angeles",
}

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

ALLOWED_SORT_FIELDS = {"startdate", "deadline", "createdAt", "updatedAt"}


# ======================================================
# JWT / Permission / Zone helpers
# ======================================================

def _claims() -> Dict[str, Any]:
    return get_jwt() or {}


def _normalize_zone_ids(raw) -> List[str]:
    """zoneIds can be list, stringified JSON list, comma string, or '*'."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        if s == "*":
            return ["*"]

        # try JSON list
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass

        # fallback: comma/space split
        parts = [p.strip() for p in s.replace(";", ",").replace("|", ",").split(",")]
        return [p for p in parts if p]

    s = str(raw).strip()
    return [s] if s else []


def _is_multi_zone(zone_ids: List[str]) -> bool:
    return ("*" in zone_ids) or (len(zone_ids) > 1)


def _scope() -> Tuple[str, List[str], Dict[str, Any], bool]:
    """
    JWT expected:
      role: admin/subadmin/employee...
      zoneIds: ["..."] or ["*"] or [] for admin-all
      employeeId: caller employeeId
      permissions: {"KPI":1, "Manage KPI":1, ...}
    """
    c = _claims()
    role = (c.get("role") or "").lower()
    zone_ids = _normalize_zone_ids(c.get("zoneIds"))
    perms = c.get("permissions") or {}
    is_admin_all = (role == "admin") and (not zone_ids or "*" in zone_ids)
    return role, zone_ids, perms, is_admin_all


def _caller_employee_id() -> str:
    return (_claims().get("employeeId") or "").strip()


def _kpi_mode() -> str:
    """
    Returns:
      - admin  : role == admin
      - manage : permissions["Manage KPI"] == 1
      - self   : permissions["KPI"] == 1
    """
    role, _zone_ids, perms, _admin_all = _scope()
    if role == "admin":
        return "admin"
    if int(perms.get("Manage KPI", 0)) == 1:
        return "manage"
    if int(perms.get("KPI", 0)) == 1:
        return "self"
    raise PermissionError("Permission denied (KPI)")


def _require_manage_kpi():
    if _kpi_mode() not in ("admin", "manage"):
        raise PermissionError("Permission denied (Manage KPI required)")


def _ensure_zone_allowed(zone_id: Optional[str]):
    """Raise 403 if zone_id not in caller zone scope (unless admin-all)."""
    _role, zone_ids, _perms, is_admin_all = _scope()
    if is_admin_all:
        return
    if not zone_ids:
        raise PermissionError("Forbidden (no zone scope)")
    if not zone_id or zone_id not in zone_ids:
        raise PermissionError("Forbidden (different zone)")


# ======================================================
# Timezone / Date helpers (store UTC)
# ======================================================

def _now_utc() -> datetime:
    return datetime.now(UTC)


def _tz_from_name(name: Optional[str]) -> ZoneInfo:
    if not name:
        return DEFAULT_TZ
    name = TZ_ALIASES.get(name, name)
    try:
        return ZoneInfo(name)
    except Exception:
        return DEFAULT_TZ


def _tz_key(tz: ZoneInfo) -> str:
    key = getattr(tz, "key", str(tz))
    return TZ_ALIASES.get(key, key)


def _employee_zone_id(emp: Dict[str, Any]) -> Optional[str]:
    zid = (emp.get("zoneId") or emp.get("zone_id") or "").strip()
    return zid or None


def _employee_timezone(emp: Dict[str, Any]) -> ZoneInfo:
    tz_name = (emp.get("timezone") or emp.get("tz") or "").strip()
    if tz_name:
        return _tz_from_name(tz_name)

    office = (emp.get("office") or emp.get("branch") or emp.get("location") or "").strip().lower()
    for key, tz in OFFICE_TZ_MAP.items():
        if key in office:
            return ZoneInfo(tz)
    return DEFAULT_TZ


def _as_utc(dt):
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _as_tz(dt, tz: ZoneInfo):
    return _as_utc(dt).astimezone(tz) if isinstance(dt, datetime) else dt


def _fmt_date_in_tz(dt, tz: ZoneInfo, f="%Y-%m-%d"):
    return _as_tz(dt, tz).strftime(f) if isinstance(dt, datetime) else (dt if isinstance(dt, str) else None)


def _fmt_dt_in_tz(dt, tz: ZoneInfo, f="%Y-%m-%d %H:%M:%S"):
    return _as_tz(dt, tz).strftime(f) if isinstance(dt, datetime) else (dt if isinstance(dt, str) else None)


def _fmt_iso_in_tz(dt, tz: ZoneInfo):
    return _as_tz(dt, tz).isoformat() if isinstance(dt, datetime) else (dt if isinstance(dt, str) else None)


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


def _parse_filter_range_to_utc(sd: str, ed: str, tz: ZoneInfo) -> Tuple[datetime, datetime]:
    start_local = _parse_date_in_tz(sd, "startDate", tz)
    end_local = _parse_eod_in_tz(ed, "endDate", tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


# ======================================================
# ID + validation helpers
# ======================================================

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


def _coerce_quality_point(raw) -> int:
    try:
        val = int(raw)
    except Exception:
        raise ValueError("qualityPoint must be -1 or 1")
    if val not in (-1, 1):
        raise ValueError("qualityPoint must be -1 or 1")
    return val


# ======================================================
# IMPORTANT: robust scoping (zoneIds + multi-zone manage KPI)
# ======================================================

def _caller_timezone_key() -> str:
    emp_id = _caller_employee_id()
    if not emp_id:
        return _tz_key(DEFAULT_TZ)
    emp = db.employees.find_one(
        {"employeeId": emp_id},
        {"timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1}
    ) or {}
    return _tz_key(_employee_timezone(emp))


def _ensure_employee_scope(employee_doc: Dict[str, Any]):
    """
    Enforces:
      - Zone scope (employee.zoneId / employee.zone_id)
      - self: only caller
      - manage: (OPTIONAL) same-timezone employees only *when subadmin has SINGLE zone*
      - admin: bypass timezone rule (still zone-scoped unless admin-all)
    """
    mode = _kpi_mode()
    role, zone_ids, _perms, is_admin_all = _scope()

    zid = _employee_zone_id(employee_doc)
    _ensure_zone_allowed(zid)

    if mode == "admin":
        return

    if mode == "self":
        if (employee_doc.get("employeeId") or "") != _caller_employee_id():
            raise PermissionError("Forbidden: KPI permission allows self-only")
        return

    if mode == "manage":
        # ✅ If subadmin has MULTI-zone, allow KPI across zones even if timezone differs
        # ✅ If SINGLE-zone, keep the old restriction (same timezone only)
        if (not is_admin_all) and (not _is_multi_zone(zone_ids)):
            caller_tz = _caller_timezone_key()
            target_tz = _tz_key(_employee_timezone(employee_doc))
            if target_tz != caller_tz:
                raise PermissionError("Forbidden: Manage KPI allows same-timezone employees only")
        return


def _resolve_employee_id_from_request(data: Dict[str, Any]) -> str:
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


def _allowed_employee_ids(selected_zone_id: Optional[str] = None) -> List[str]:
    """
    For getAll/export:
      - Compute allowed employeeIds from employees collection using zone scope.
      - For manage mode: apply timezone filter ONLY when subadmin has SINGLE zone.
      - This avoids relying on KPI.zoneId (legacy docs can be missing it).
    """
    mode = _kpi_mode()
    role, zone_ids, _perms, is_admin_all = _scope()

    if mode == "self":
        eid = _caller_employee_id()
        return [eid] if eid else []

    if selected_zone_id:
        selected_zone_id = selected_zone_id.strip()
        _ensure_zone_allowed(selected_zone_id)

    emp_query: Dict[str, Any] = {}

    if selected_zone_id:
        emp_query["$or"] = [{"zoneId": selected_zone_id}, {"zone_id": selected_zone_id}]
    elif not is_admin_all:
        if not zone_ids:
            return []
        emp_query["$or"] = [{"zoneId": {"$in": zone_ids}}, {"zone_id": {"$in": zone_ids}}]

    cursor = db.employees.find(
        emp_query,
        {"employeeId": 1, "timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1, "zoneId": 1, "zone_id": 1}
    )

    apply_tz_filter = (mode == "manage") and (not is_admin_all) and (not _is_multi_zone(zone_ids))
    caller_tz = _caller_timezone_key() if apply_tz_filter else None

    out: List[str] = []
    for emp in cursor:
        emp_id = (emp.get("employeeId") or "").strip()
        if not emp_id:
            continue
        if apply_tz_filter:
            if _tz_key(_employee_timezone(emp)) != caller_tz:
                continue
        out.append(emp_id)

    return out


# ======================================================
# Legacy auto-fix (update docs once on read)
# ======================================================

def _ensure_kpi_has_zone_and_timezone(kpi: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}

    # normalize project field
    if not kpi.get("project_name") and kpi.get("projectName"):
        updates["project_name"] = kpi.get("projectName")

    # normalize remark field
    if kpi.get("remark") is None and kpi.get("Remark") is not None:
        updates["remark"] = kpi.get("Remark")

    # canonicalize timezone name
    if kpi.get("timezone"):
        canon = TZ_ALIASES.get(kpi["timezone"], kpi["timezone"])
        if canon != kpi["timezone"]:
            updates["timezone"] = canon

    # fill missing zoneId/timezone/employeeName from employee
    if (not kpi.get("zoneId")) or (not kpi.get("timezone")) or (not kpi.get("employeeName")):
        emp = db.employees.find_one(
            {"employeeId": kpi.get("employeeId")},
            {"zoneId": 1, "zone_id": 1, "timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1, "name": 1}
        )
        if emp:
            if not kpi.get("zoneId"):
                zid = _employee_zone_id(emp)
                if zid:
                    updates["zoneId"] = zid
            if not kpi.get("timezone"):
                updates["timezone"] = _tz_key(_employee_timezone(emp))
            if not kpi.get("employeeName") and emp.get("name"):
                updates["employeeName"] = emp.get("name")

    if updates:
        db.kpi.update_one({"kpiId": kpi.get("kpiId")}, {"$set": updates})
        kpi = {**kpi, **updates}

    return kpi


# ======================================================
# Output mapper
# ======================================================

def _map_kpi_row(k: Dict[str, Any], include_punches: bool, include_last_punch: bool) -> Dict[str, Any]:
    k = _ensure_kpi_has_zone_and_timezone(k)
    tz = _tz_from_name(k.get("timezone"))

    punches = k.get("punches", []) or []
    last = punches[-1] if punches else {}

    proj = k.get("project_name") or k.get("projectName") or ""
    rem = k.get("remark") if k.get("remark") is not None else (k.get("Remark") or "")

    row = {
        "kpiId": k.get("kpiId"),
        "zoneId": k.get("zoneId"),
        "employeeId": k.get("employeeId"),
        "employeeName": k.get("employeeName"),
        "projectName": proj,
        "timezone": _tz_key(tz),

        "startdate": _fmt_date_in_tz(k.get("startdate"), tz),
        "deadline": _fmt_date_in_tz(k.get("deadline"), tz),

        # keep both keys so old frontend mapping never breaks
        "remark": rem,
        "Remark": rem,

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

    return row


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
        start_str = (data.get("startdate") or data.get("startDate") or "").strip()
        deadline_str = (data.get("deadline") or "").strip()

        remark = (
            data.get("Remark/comment")
            or data.get("Remark")
            or data.get("comment")
            or data.get("remark")
            or ""
        )

        if not project_name or not deadline_str:
            return format_response(False, "Missing required fields: projectName, deadline", None, 400)

        employee = db.employees.find_one({"employeeId": employee_id})
        if not employee:
            return format_response(False, "Employee not found", None, 404)

        _ensure_employee_scope(employee)

        tz = _employee_timezone(employee)
        now_utc = _now_utc()

        # start date: if not provided, use "today" (local midnight)
        if start_str:
            start_local = _parse_date_in_tz(start_str, "startdate", tz)
        else:
            start_local = _parse_date_in_tz(_as_tz(now_utc, tz).strftime("%Y-%m-%d"), "startdate", tz)
        start_utc = start_local.astimezone(UTC)

        deadline_local = _parse_eod_in_tz(deadline_str, "deadline", tz)
        deadline_utc = deadline_local.astimezone(UTC)

        kpi_id = str(uuid.uuid4())
        kpi_doc = {
            "kpiId": kpi_id,
            "zoneId": _employee_zone_id(employee),
            "employeeId": employee_id,
            "employeeName": employee.get("name"),
            "project_name": project_name,

            "startdate": start_utc,     # UTC datetime
            "deadline": deadline_utc,   # UTC datetime

            "timezone": _tz_key(tz),    # canonical tz key used for display only

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

        # enforce permission against KPI's employee
        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")})
        if emp:
            _ensure_employee_scope(emp)
        else:
            # fallback to KPI zone (if present)
            if kpi.get("zoneId"):
                _ensure_zone_allowed(kpi.get("zoneId"))
            else:
                _role, _zones, _perms, is_admin_all = _scope()
                if not is_admin_all:
                    raise PermissionError("Forbidden")

        updates: Dict[str, Any] = {}

        if (pn := (data.get("projectName") or "").strip()):
            updates["project_name"] = pn

        # start date update
        raw_sd = (data.get("startdate") or data.get("startDate") or "").strip()
        if raw_sd:
            tz = _tz_from_name(kpi.get("timezone"))
            sd_local = _parse_date_in_tz(raw_sd, "startdate", tz)
            updates["startdate"] = sd_local.astimezone(UTC)

        # deadline update
        raw_dl = (data.get("deadline") or "").strip()
        if raw_dl:
            tz = _tz_from_name(kpi.get("timezone"))
            dl_local = _parse_eod_in_tz(raw_dl, "deadline", tz)
            updates["deadline"] = dl_local.astimezone(UTC)

        # remark update
        remark = (
            data.get("Remark/comment")
            or data.get("Remark")
            or data.get("comment")
            or data.get("remark")
        )
        if remark is not None:
            updates["remark"] = remark

        if not updates:
            return format_response(False, "No fields to update", None, 400)

        updates["updatedAt"] = _now_utc()
        db.kpi.update_one({"kpiId": kpi_id}, {"$set": updates})

        return format_response(True, "KPI updated", {"kpiId": kpi_id}, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except ValueError as e:
        return format_response(False, str(e), None, 400)
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

        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")})
        if emp:
            _ensure_employee_scope(emp)
        else:
            if kpi.get("zoneId"):
                _ensure_zone_allowed(kpi.get("zoneId"))
            else:
                _role, _zones, _perms, is_admin_all = _scope()
                if not is_admin_all:
                    raise PermissionError("Forbidden")

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
            "punchDate": now_utc,  # stored UTC
            "remark": (data.get("remark") or "").strip(),
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
    ✅ Stable zone behavior:
      - Compute allowed employeeIds from employees collection (zone scope + manage rule)
      - Fetch KPIs by employeeId in allowed list (works even if KPI docs are missing zoneId)
    Supports:
      - zoneId
      - employeeIds / employeeId
      - search
      - startDate/endDate (+ tz/timezone for filtering)
      - sortBy/sortOrder
      - pagination (backend)
    """
    try:
        _require_manage_kpi()
        data = request.get_json(force=True) or {}

        selected_zone_id = (data.get("zoneId") or "").strip() or None

        page = max(int(data.get("page", 1)), 1)
        page_size = max(int(data.get("pageSize", 10)), 1)

        allowed_ids = _allowed_employee_ids(selected_zone_id)
        if not allowed_ids:
            return format_response(True, "KPIs retrieved", {
                "page": page,
                "pageSize": page_size,
                "total": 0,
                "totalPages": 0,
                "kpis": []
            }, 200)

        allowed_set = set(allowed_ids)

        # Accept both employeeId (single) and employeeIds (list)
        requested_ids = []
        if (single := (data.get("employeeId") or "").strip()):
            requested_ids = [single]
        else:
            requested_ids = _normalize_employee_ids(data.get("employeeIds", data.get("employesids")))

        if requested_ids:
            requested_ids = [eid for eid in requested_ids if eid in allowed_set]
            if not requested_ids:
                return format_response(True, "KPIs retrieved", {
                    "page": page,
                    "pageSize": page_size,
                    "total": 0,
                    "totalPages": 0,
                    "kpis": []
                }, 200)

        query: Dict[str, Any] = {"employeeId": {"$in": requested_ids or allowed_ids}}

        # search
        if (s := (data.get("search") or "").strip()):
            rx = {"$regex": re.escape(s), "$options": "i"}
            query["$or"] = [
                {"project_name": rx},
                {"projectName": rx},    # legacy
                {"employeeName": rx},
                {"employeeId": rx},
            ]

        # date filter (on startdate)
        sd = (data.get("startDate") or "").strip()
        ed = (data.get("endDate") or "").strip()
        if sd and ed:
            filter_tz = _tz_from_name(data.get("tz") or data.get("timezone"))
            start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, filter_tz)
            query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

        # sort
        sort_by = (data.get("sortBy") or "createdAt").strip()
        sort_order = (data.get("sortOrder") or "desc").lower()
        sort_dir = -1 if sort_order == "desc" else 1
        sort_field = sort_by if sort_by in ALLOWED_SORT_FIELDS else "createdAt"

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

        out = [_map_kpi_row(k, include_punches, include_last_punch) for k in cursor]

        return format_response(True, "KPIs retrieved", {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": (total + page_size - 1) // page_size if page_size else 0,
            "kpis": out
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except ValueError as e:
        return format_response(False, str(e), None, 400)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/getByKpiId/<kpi_id>", methods=["GET"])
@jwt_required()
def getByKpiId(kpi_id):
    try:
        _kpi_mode()  # must have KPI access (self/manage/admin)

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")})
        if emp:
            _ensure_employee_scope(emp)
        else:
            # fallback: enforce KPI.zoneId if present
            if kpi.get("zoneId"):
                _ensure_zone_allowed(kpi.get("zoneId"))
            else:
                _role, _zones, _perms, is_admin_all = _scope()
                if not is_admin_all:
                    raise PermissionError("Forbidden")

        payload = _map_kpi_row(kpi, include_punches=True, include_last_punch=True)
        return format_response(True, "KPI retrieved", payload, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@kpi_bp.route("/getByEmployeeId", methods=["POST"])
@jwt_required()
def getByEmployeeId():
    """
    self:
      - employeeId forced from JWT
    manage/admin:
      - can query employeeId, but must pass _ensure_employee_scope(employee)
    Pagination is backend.
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

        _ensure_employee_scope(employee)

        query: Dict[str, Any] = {"employeeId": employee_id}

        if (s := (data.get("search") or "").strip()):
            rx = {"$regex": re.escape(s), "$options": "i"}
            query["$or"] = [{"project_name": rx}, {"projectName": rx}]

        sd = (data.get("startDate") or "").strip()
        ed = (data.get("endDate") or "").strip()
        if sd and ed:
            emp_tz = _employee_timezone(employee)
            start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, emp_tz)
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

        include_punches = bool(data.get("includePunches"))
        include_last_punch = bool(data.get("includeLastPunch", True))

        out = [_map_kpi_row(k, include_punches, include_last_punch) for k in cursor]

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
        _require_manage_kpi()

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

        # enforce scope using employee (NOT KPI.zoneId alone)
        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")})
        if emp:
            _ensure_employee_scope(emp)
        else:
            if kpi.get("zoneId"):
                _ensure_zone_allowed(kpi.get("zoneId"))
            else:
                _role, _zones, _perms, is_admin_all = _scope()
                if not is_admin_all:
                    raise PermissionError("Forbidden")

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
        _require_manage_kpi()

        data = request.get_json(force=True) or {}
        kpi_id = (data.get("kpiId") or "").strip()
        if not kpi_id:
            return format_response(False, "Missing kpiId", None, 400)

        kpi = db.kpi.find_one({"kpiId": kpi_id})
        if not kpi:
            return format_response(False, "KPI not found", None, 404)

        kpi = _ensure_kpi_has_zone_and_timezone(kpi)

        emp = db.employees.find_one({"employeeId": kpi.get("employeeId")})
        if emp:
            _ensure_employee_scope(emp)
        else:
            if kpi.get("zoneId"):
                _ensure_zone_allowed(kpi.get("zoneId"))
            else:
                _role, _zones, _perms, is_admin_all = _scope()
                if not is_admin_all:
                    raise PermissionError("Forbidden")

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
    ✅ Stable:
      - Allowed employees computed from employees collection (zone + manage rule)
      - KPI fetched by employeeId in allowed list (works even if KPI docs miss zoneId)
    Supports:
      - zoneId, employeeIds/employeeId
      - search, startDate/endDate (+ tz/timezone)
      - sortBy/sortOrder
      - all/exportAll to export everything
      - pagination params (if not exporting all)
    """
    try:
        _require_manage_kpi()

        data = request.get_json(force=True) or {}

        selected_zone_id = (data.get("zoneId") or "").strip() or None
        allowed_ids = _allowed_employee_ids(selected_zone_id)
        if not allowed_ids:
            # return empty csv (still a valid download)
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "EmployeeName", "EmployeeId", "ZoneId",
                "ProjectName", "Timezone",
                "StartDate", "Deadline",
                "Remark", "DeadlinePoints", "QualityPoints",
                "LastPunchDate", "LastPunchStatus", "LastPunchRemark"
            ])
            resp = make_response(output.getvalue())
            resp.headers["Content-Type"] = "text/csv; charset=utf-8"
            resp.headers["Content-Disposition"] = 'attachment; filename="kpi_export.csv"'
            return resp

        allowed_set = set(allowed_ids)

        # accept employeeId (single) and employeeIds (list)
        emp_single = (data.get("employeeId") or "").strip()
        emp_list = _normalize_employee_ids(data.get("employeeIds"))

        filtered_emp_ids: List[str]
        if emp_single:
            filtered_emp_ids = [emp_single] if emp_single in allowed_set else []
        elif emp_list:
            filtered_emp_ids = [x for x in emp_list if x in allowed_set]
        else:
            filtered_emp_ids = allowed_ids

        if not filtered_emp_ids:
            return format_response(False, "No employees allowed for export", None, 403)

        query: Dict[str, Any] = {"employeeId": {"$in": filtered_emp_ids}}

        search = (data.get("search") or "").strip()
        if search:
            rx = {"$regex": re.escape(search), "$options": "i"}
            query["$or"] = [
                {"project_name": rx},
                {"projectName": rx},
                {"employeeName": rx},
                {"employeeId": rx}
            ]

        sd = (data.get("startDate") or "").strip()
        ed = (data.get("endDate") or "").strip()
        if sd and ed:
            filter_tz = _tz_from_name(data.get("tz") or data.get("timezone"))
            start_utc, end_utc = _parse_filter_range_to_utc(sd, ed, filter_tz)
            query["startdate"] = {"$gte": start_utc, "$lte": end_utc}

        sort_by = (data.get("sortBy") or "createdAt").strip()
        sort_order = (data.get("sortOrder") or "desc").lower()
        sort_dir = -1 if sort_order == "desc" else 1
        sort_field = sort_by if sort_by in ALLOWED_SORT_FIELDS else "createdAt"

        export_all = bool(data.get("all") or data.get("exportAll"))
        page = max(int(data.get("page", 1)), 1)
        page_size = max(int(data.get("pageSize", 10)), 1)

        cursor = db.kpi.find(query).sort(sort_field, sort_dir)
        if not export_all:
            cursor = cursor.skip((page - 1) * page_size).limit(page_size)

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

            proj = k.get("project_name") or k.get("projectName") or ""
            rem = k.get("remark") if k.get("remark") is not None else (k.get("Remark") or "")

            writer.writerow({
                "EmployeeName": k.get("employeeName", "") or "",
                "EmployeeId": k.get("employeeId", "") or "",
                "ZoneId": k.get("zoneId", "") or "",
                "ProjectName": proj,
                "Timezone": _tz_key(tz),

                "StartDate": _fmt_dt_in_tz(k.get("startdate"), tz) or "",
                "Deadline": _fmt_dt_in_tz(k.get("deadline"), tz) or "",

                "Remark": rem,
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
