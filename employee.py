import math
import re
import uuid
import csv, io
import calendar
import random
import string
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List

from flask import Blueprint, make_response, request, send_file
from flask_jwt_extended import jwt_required, get_jwt

from db import db
from utils import format_response
from salaryslip import SalarySlipGenerator


employee_bp = Blueprint("employee", __name__, url_prefix="/employee")

UTC = ZoneInfo("UTC")
ALLOWED_TZS = {"Asia/Kolkata", "America/Los_Angeles"}

ALLOWANCE_NAMES = [
    "Basic Pay",
    "House Rent Allowance",
    "Performance Bonus",
    "Overtime Bonus",
    "Special Allowance",
]


# ----------------------------
# Time helpers
# ----------------------------

def _now_utc() -> datetime:
    return datetime.now(UTC)

def _safe_iso(dt):
    return dt.astimezone(UTC).isoformat() if isinstance(dt, datetime) else dt


# ----------------------------
# AuthZ helpers (Zone + Permissions)
# ----------------------------

def _normalize_zone_ids(raw) -> List[str]:
    """
    JWT sometimes stores zoneIds as:
      - ["z1","z2"]
      - "['z1','z2']"
      - "z1,z2"
      - "*"
    Normalize to List[str].
    """
    if raw is None:
        return []

    # already list
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]

    # string case
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        if s == "*":
            return ["*"]

        # try json list
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass

        # fallback: comma/space split
        parts = [p.strip() for p in s.replace(";", ",").split(",")]
        return [p for p in parts if p]

    # fallback
    return [str(raw).strip()] if str(raw).strip() else []


def _scope():
    """
    Expected JWT claims:
      role: "admin" | "subadmin"
      zoneIds: ["..."] or ["*"] (admin)
      employeeId: "EMPxxxx"
      permissions: { ... }
    """
    claims = get_jwt() or {}
    role = (claims.get("role") or "").lower()

    zone_ids = _normalize_zone_ids(claims.get("zoneIds"))
    perms = claims.get("permissions") or {}

    is_admin_all = (role == "admin") and (not zone_ids or "*" in zone_ids)
    return role, zone_ids, perms, is_admin_all

def _zone_query(field: str = "zoneId") -> dict:
    """Mongo filter enforcing zone scope."""
    role, zone_ids, _perms, is_admin_all = _scope()

    if is_admin_all:
        return {}

    if role != "admin" and not zone_ids:
        return {field: {"$in": ["__no_zone_access__"]}}

    return {field: {"$in": zone_ids}}

def _ensure_in_scope(doc_zone_id: Optional[str]):
    """Raise 403 if doc_zone_id not in caller zone scope (unless admin-all)."""
    _role, zone_ids, _perms, is_admin_all = _scope()
    if is_admin_all:
        return
    if not doc_zone_id or doc_zone_id not in zone_ids:
        # do not leak existence across zones
        raise PermissionError("Forbidden (different zone)")

def _require_permission(permission_key: str):
    """Simple permission check (subadmin). Admin bypass."""
    role, _zone_ids, perms, _is_admin_all = _scope()
    if role == "admin":
        return
    if int(perms.get(permission_key, 0)) != 1:
        raise PermissionError("Permission denied")

def _has_manage_kpi() -> bool:
    role, _zone_ids, perms, _all = _scope()
    return role == "admin" or int(perms.get("Manage KPI", 0)) == 1

def _has_kpi_or_manage() -> bool:
    role, _zone_ids, perms, _all = _scope()
    return (
        role == "admin"
        or int(perms.get("KPI", 0)) == 1
        or int(perms.get("Manage KPI", 0)) == 1
    )

def _caller_employee_id() -> str:
    claims = get_jwt() or {}
    return (claims.get("employeeId") or "").strip()

def _caller_timezone_key() -> str:
    """
    Caller timezone (from employees collection).
    Falls back to Asia/Kolkata if missing.
    """
    emp_id = _caller_employee_id()
    if not emp_id:
        return "Asia/Kolkata"

    emp = db.employees.find_one(
        {"employeeId": emp_id},
        {"timezone": 1, "tz": 1, "office": 1, "branch": 1, "location": 1},
    ) or {}

    tz = (emp.get("timezone") or emp.get("tz") or "").strip()
    if tz and tz in ALLOWED_TZS:
        return tz

    office = (emp.get("office") or emp.get("branch") or emp.get("location") or "").strip().lower()
    if any(x in office for x in ["las vegas", "vegas", "usa", "us", "america"]):
        return "America/Los_Angeles"
    return "Asia/Kolkata"


# ----------------------------
# Mongo cleaning
# ----------------------------

def _clean_mongo_doc(doc: dict) -> dict:
    """Remove Mongo _id + convert datetimes to ISO strings (UTC)."""
    if not doc:
        return doc
    doc = dict(doc)
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = _safe_iso(v)
        elif isinstance(v, dict):
            doc[k] = _clean_mongo_doc(v)
        elif isinstance(v, list):
            new_list = []
            for item in v:
                if isinstance(item, dict):
                    new_list.append(_clean_mongo_doc(item))
                elif isinstance(item, datetime):
                    new_list.append(_safe_iso(item))
                else:
                    new_list.append(item)
            doc[k] = new_list
    return doc


# ----------------------------
# Validation helpers
# ----------------------------

def generate_unique_employee_id():
    while True:
        emp_id = "EMP" + "".join(random.choices(string.digits, k=4))
        if not db.employees.find_one({"employeeId": emp_id}):
            return emp_id

def resolve_timezone(payload: dict) -> str:
    """
    Store employee.timezone explicitly as:
      - Asia/Kolkata
      - America/Los_Angeles
    """
    tz = (payload.get("timezone") or payload.get("tz") or "").strip()
    if tz:
        if tz not in ALLOWED_TZS:
            raise ValueError("timezone must be 'Asia/Kolkata' or 'America/Los_Angeles'")
        ZoneInfo(tz)  # validate
        return tz

    # fallback mapping by office/branch/location
    office = (payload.get("office") or payload.get("branch") or payload.get("location") or "").strip().lower()
    if any(x in office for x in ["las vegas", "vegas", "usa", "us", "america"]):
        return "America/Los_Angeles"
    return "Asia/Kolkata"

def resolve_zone_id(payload: dict) -> str:
    """
    Resolve zoneId from:
      1) zoneId directly
      2) zone / zoneName (by zones.name)
      3) office/branch/location text (mapped to zones.code)
    """
    zid = (payload.get("zoneId") or "").strip()
    if zid:
        if not db.zones.find_one({"zoneId": zid, "isActive": True}):
            raise ValueError("Invalid zoneId")
        return zid

    zname = (payload.get("zone") or payload.get("zoneName") or "").strip()
    if zname:
        z = db.zones.find_one({
            "name": {"$regex": f"^{re.escape(zname)}$", "$options": "i"},
            "isActive": True
        })
        if not z:
            raise ValueError("Zone not found by name")
        return z["zoneId"]

    office = (payload.get("office") or payload.get("branch") or payload.get("location") or "").lower()
    office_map = {
        "vrindavan": "VRD",
        "nagpur": "NGP",
        "gurgaon": "GGN",
        "las vegas": "LAS",
        "vegas": "LAS",
    }
    for key, code in office_map.items():
        if key in office:
            z = db.zones.find_one({"code": code, "isActive": True})
            if z:
                return z["zoneId"]

    raise ValueError("zoneId/zoneName required (or office must match a configured zone)")

def _parse_yyyy_mm_dd(date_str: str, field_name: str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{field_name} must be YYYY-MM-DD")

def _parse_float(val, field_name: str):
    try:
        return float(val)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a number")

def _get_manual_tds_from_request_or_employee(req_data: dict, emp: dict):
    if "Tax Deduction at Source (TDS)" in req_data:
        return _parse_float(req_data.get("Tax Deduction at Source (TDS)"), "Tax Deduction at Source (TDS)")
    if "manual_tds" in req_data and req_data.get("manual_tds") is not None:
        return _parse_float(req_data.get("manual_tds"), "manual_tds")
    stored = emp.get("manual_tds")
    return _parse_float(stored, "manual_tds") if stored is not None else None

def _normalize_salary_structure(incoming):
    incoming = incoming or []
    final_struct = []
    for name in ALLOWANCE_NAMES:
        amt = 0.0
        for item in incoming:
            if item.get("name") == name:
                amt = _parse_float(item.get("amount", 0), f"salary_structure amount for {name}")
                break
        final_struct.append({"name": name, "amount": amt})
    return final_struct


# ----------------------------
# KPI-safe Employee endpoints
# ----------------------------

@employee_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    """
    KPI-only users cannot call /getrecord because it requires 'View Employee Details'.
    This endpoint returns ONLY the logged-in employee basic info and is allowed for KPI/Manage KPI.
    """
    try:
        if not _has_kpi_or_manage():
            raise PermissionError("Permission denied")

        emp_id = _caller_employee_id()
        if not emp_id:
            return format_response(False, "Missing employeeId in token", None, 403)

        emp = db.employees.find_one(
            {"employeeId": emp_id},
            {"_id": 0, "employeeId": 1, "name": 1, "zoneId": 1, "timezone": 1}
        )
        if not emp:
            return format_response(False, "Employee not found", None, 404)

        _ensure_in_scope(emp.get("zoneId"))

        return format_response(True, "Me fetched", {"employee": emp}, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@employee_bp.route("/kpi-employee-list", methods=["POST"])
@jwt_required()
def kpi_employee_list():
    """
    Employees list for KPI screen ONLY.
    - Only Admin or Manage KPI can access.
    - Subadmin Manage KPI can see employees within their zones.
    - Timezone filter is applied ONLY if subadmin has SINGLE zone scope.
      (If multi-zone access, show employees from all allowed zones.)
    """
    try:
        if not _has_manage_kpi():
            raise PermissionError("Permission denied (Manage KPI required)")

        params = request.get_json(force=True) or {}
        search = (params.get("search") or "").strip()
        page = max(int(params.get("page", 1)), 1)
        size = max(int(params.get("pageSize", 500)), 1)

        role, zone_ids, _perms, is_admin_all = _scope()

        query: Dict[str, Any] = {}
        query.update(_zone_query("zoneId"))

        # ✅ Apply SAME timezone restriction ONLY for single-zone subadmin
        # (multi-zone subadmin should see employees across their allowed zones)
        is_multi_zone = ("*" in zone_ids) or (len(zone_ids) > 1)
        if role != "admin" and not is_multi_zone:
            query["timezone"] = _caller_timezone_key()

        if search:
            regex = re.compile(re.escape(search), re.IGNORECASE)
            query["$or"] = [{"name": regex}, {"employeeId": regex}]

        total = db.employees.count_documents(query)
        skip = (page - 1) * size

        cursor = (
            db.employees.find(
                query,
                {"_id": 0, "employeeId": 1, "name": 1, "zoneId": 1, "timezone": 1}
            )
            .sort("name", 1)
            .skip(skip)
            .limit(size)
        )

        return format_response(True, "KPI employee list", {
            "employees": list(cursor),
            "total": total,
            "page": page,
            "pageSize": size,
            "totalPages": (total + size - 1) // size
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)

# ----------------------------
# Employee CRUD (unchanged permissions)
# ----------------------------

@employee_bp.route("/SaveRecord", methods=["POST"])
@jwt_required()
def add_employee():
    try:
        _require_permission("Add Employee Details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    data = request.get_json(force=True) or {}

    required = [
        "name", "email", "phone", "dob",
        "adharnumber", "pan_number", "date_of_joining",
        "base_salary", "department", "designation"
    ]
    if not all(data.get(f) for f in required):
        return format_response(False, "Missing required employee details", status=400)

    try:
        _parse_yyyy_mm_dd(data["dob"], "dob")
        _parse_yyyy_mm_dd(data["date_of_joining"], "date_of_joining")
    except ValueError as e:
        return format_response(False, str(e), status=400)

    try:
        employee_tz = resolve_timezone(data)
    except ValueError as e:
        return format_response(False, str(e), status=400)

    try:
        zone_id = resolve_zone_id(data)
    except ValueError as e:
        return format_response(False, str(e), status=400)

    try:
        _ensure_in_scope(zone_id)
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    try:
        base_salary = _parse_float(data["base_salary"], "base_salary")
        annual_salary = base_salary * 12
    except ValueError as e:
        return format_response(False, str(e), status=400)

    manual = data.get("manual_tds")
    if manual is not None:
        try:
            manual = _parse_float(manual, "manual_tds")
        except ValueError as e:
            return format_response(False, str(e), status=400)

    employee_id = (data.get("employeeId") or "").strip() or generate_unique_employee_id()

    if db.employees.find_one({"$or": [
        {"employeeId": employee_id},
        {"email": data["email"]},
        {"phone": data["phone"]}
    ]}):
        return format_response(False, "Employee already exists with this ID, email, or phone number", status=409)

    record = {
        "employeeId": employee_id,
        "zoneId": zone_id,
        "name": data["name"],
        "email": data["email"],
        "phone": data["phone"],
        "dob": data["dob"],
        "adharnumber": data["adharnumber"],
        "pan_number": data["pan_number"],
        "date_of_joining": data["date_of_joining"],
        "base_salary": base_salary,
        "annual_salary": annual_salary,
        "manual_tds": manual,
        "bank_details": data.get("bank_details", {}),
        "address": data.get("address", {}),
        "department": data["department"],
        "designation": data["designation"],
        "timezone": employee_tz,
        "created_at": _now_utc(),
        "updated_at": _now_utc()
    }

    for opt in ("office", "branch", "location"):
        if data.get(opt) is not None:
            record[opt] = data.get(opt)

    db.employees.insert_one(record)
    return format_response(True, "Employee added successfully", {"employeeId": employee_id}, status=201)


@employee_bp.route("/update", methods=["POST"])
@jwt_required()
def update_employee():
    try:
        _require_permission("Add Employee Details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    data = request.get_json(force=True) or {}
    emp_id = data.pop("employeeId", None)
    if not emp_id:
        return format_response(False, "employeeId is required", status=400)
    if not data:
        return format_response(False, "No fields provided for update", status=400)

    current = db.employees.find_one({"employeeId": emp_id})
    if not current:
        return format_response(False, "Employee not found", status=404)

    try:
        _ensure_in_scope(current.get("zoneId"))
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    try:
        if "dob" in data:
            _parse_yyyy_mm_dd(data["dob"], "dob")
        if "date_of_joining" in data:
            _parse_yyyy_mm_dd(data["date_of_joining"], "date_of_joining")
    except ValueError as e:
        return format_response(False, str(e), status=400)

    for num in ("base_salary", "annual_salary", "manual_tds"):
        if num in data:
            try:
                data[num] = _parse_float(data[num], num)
            except ValueError as e:
                return format_response(False, str(e), status=400)

    if any(k in data for k in ("timezone", "tz", "office", "branch", "location")):
        try:
            merged = {**current, **data}
            data["timezone"] = resolve_timezone(merged)
            data.pop("tz", None)
        except ValueError as e:
            return format_response(False, str(e), status=400)

    if any(k in data for k in ("zoneId", "zone", "zoneName", "office", "branch", "location")):
        try:
            merged = {**current, **data}
            new_zone = resolve_zone_id(merged)
            _ensure_in_scope(new_zone)
            data["zoneId"] = new_zone
        except (ValueError, PermissionError) as e:
            return format_response(False, str(e), None, 400 if isinstance(e, ValueError) else 403)

    data["updated_at"] = _now_utc()

    res = db.employees.update_one({"employeeId": emp_id}, {"$set": data})
    if not res.matched_count:
        return format_response(False, "Employee not found", status=404)

    return format_response(True, "Employee updated successfully", {"employeeId": emp_id}, status=200)


@employee_bp.route("/delete", methods=["POST"])
@jwt_required()
def delete_employee():
    try:
        _require_permission("Add Employee Details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    emp_id = (request.get_json(force=True) or {}).get("employeeId")
    if not emp_id:
        return format_response(False, "employeeId is required", status=400)

    emp = db.employees.find_one({"employeeId": emp_id})
    if not emp:
        return format_response(False, "Employee not found", status=404)

    try:
        _ensure_in_scope(emp.get("zoneId"))
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    res = db.employees.delete_one({"employeeId": emp_id})
    if not res.deleted_count:
        return format_response(False, "Employee not found", status=404)

    return format_response(True, "Employee deleted successfully", status=200)


@employee_bp.route("/getrecord", methods=["GET"])
@jwt_required()
def get_record():
    """
    Full employee record: still protected by 'View Employee Details'
    (KPI-only users should use /employee/me instead)
    """
    try:
        _require_permission("View Employee Details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    emp_id = request.args.get("employeeId")
    if not emp_id:
        return format_response(False, "Query parameter 'employeeId' is required", status=400)

    emp = db.employees.find_one({"employeeId": emp_id})
    if not emp:
        return format_response(False, "Employee not found", status=404)

    try:
        _ensure_in_scope(emp.get("zoneId"))
    except PermissionError:
        return format_response(False, "Employee not found", status=404)

    return format_response(True, "Employee retrieved successfully", {"employee": _clean_mongo_doc(emp)}, status=200)


@employee_bp.route("/getlist", methods=["POST"])
@jwt_required()
def get_all_employees():
    """
    Full employee listing: still protected by 'View Employee Details'
    (KPI Manage screen should use /employee/kpi-employee-list instead)
    """
    try:
        _require_permission("View Employee Details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    params = request.get_json(force=True) or {}
    search = (params.get("search") or "").strip()
    page = max(int(params.get("page", 1)), 1)
    size = max(int(params.get("pageSize", 10)), 1)

    query = {}
    query.update(_zone_query("zoneId"))

    if search:
        regex = re.compile(re.escape(search), re.IGNORECASE)
        query["$or"] = [{"name": regex}, {"email": regex}, {"phone": regex}, {"employeeId": regex}]

    total = db.employees.count_documents(query)
    skip = (page - 1) * size

    cursor = (
        db.employees.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(size)
    )

    results = [_clean_mongo_doc(e) for e in cursor]
    total_pages = math.ceil(total / size) if size else 0

    return format_response(True, "Employees retrieved successfully", {
        "employees": results,
        "total": total,
        "page": page,
        "pageSize": size,
        "totalPages": total_pages
    }, status=200)


# ----------------------------
# Salary Slip
# ----------------------------

@employee_bp.route("/salaryslip", methods=["POST"])
@jwt_required()
def get_salary_slip():
    try:
        _require_permission("Generate payslip")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    data = request.get_json(force=True) or {}
    emp_id = data.get("employeeId") or data.get("employee_id")
    payslip_month = data.get("month")

    if not emp_id or not payslip_month:
        return format_response(False, "Missing required fields: employeeId or month", status=400)

    try:
        mdate = datetime.strptime(payslip_month, "%m-%Y")
    except ValueError:
        return format_response(False, "Invalid month format. Use MM-YYYY", status=400)

    emp = db.employees.find_one({"employeeId": emp_id})
    if not emp:
        return format_response(False, "Employee not found", status=404)

    try:
        _ensure_in_scope(emp.get("zoneId"))
    except PermissionError:
        return format_response(False, "Employee not found", status=404)

    year, month = mdate.year, mdate.month
    last_day = calendar.monthrange(year, month)[1]
    date_str = f"{last_day:02d}-{month:02d}-{year}"

    try:
        manual_tds = _get_manual_tds_from_request_or_employee(data, emp)
    except ValueError as e:
        return format_response(False, str(e), status=400)

    try:
        final_struct = _normalize_salary_structure(data.get("salary_structure", []))
    except ValueError as e:
        return format_response(False, str(e), status=400)

    try:
        doj_str = datetime.strptime(emp["date_of_joining"], "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        doj_str = emp.get("date_of_joining", "")

    emp_snapshot = {
        "full_name": emp.get("name", ""),
        "emp_no": emp.get("employeeId", ""),
        "designation": emp.get("designation", ""),
        "department": emp.get("department", ""),
        "doj": doj_str,
        "bank_account": (emp.get("bank_details") or {}).get("account_number", ""),
        "bank_name": (emp.get("bank_details") or {}).get("bank_name", ""),
        "pan": emp.get("pan_number", ""),
        "lop": float(data.get("lop", 0) or 0),
        "salary_structure": final_struct,
        "Tax Deduction at Source (TDS)": manual_tds,
    }

    pdf_buf = SalarySlipGenerator(emp_snapshot, current_date=date_str).generate_pdf()

    payslip_id = str(uuid.uuid4())
    month_name = calendar.month_name[month]
    now = _now_utc()

    db.payslips.insert_one({
        "payslipId": payslip_id,
        "zoneId": emp.get("zoneId"),
        "employeeId": emp_id,
        "employeeName": emp.get("name"),
        "timezone": emp.get("timezone"),
        "month": month_name,
        "year": year,
        "generated_on": now,
        "lop_days": emp_snapshot["lop"],
        "salary_structure": final_struct,
        "emp_snapshot": emp_snapshot,
        "filename": f"salary_slip_{emp_id}_{month:02d}_{year}.pdf"
    })

    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"salary_slip_{emp_id}_{month:02d}_{year}.pdf"
    )


@employee_bp.route("/getpayslips", methods=["POST"])
@jwt_required()
def get_payslips():
    try:
        _require_permission("View payslip details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    params = request.get_json(force=True) or {}
    query = {}
    query.update(_zone_query("zoneId"))

    if params.get("month"):
        month_pattern = re.escape(params["month"])
        query["month"] = {"$regex": f"^{month_pattern}", "$options": "i"}

    page = max(int(params.get("page", 1)), 1)
    size = max(int(params.get("pageSize", 10)), 1)

    total = db.payslips.count_documents(query)

    cursor = (
        db.payslips
        .find(query, {"_id": 0})
        .sort("generated_on", -1)
        .skip((page - 1) * size)
        .limit(size)
    )

    payslips = []
    for p in cursor:
        p = _clean_mongo_doc(p)
        pid = p.get("payslipId")
        p["view_link"] = f"/employee/viewpdf/{pid}"
        p["download_link"] = f"/employee/download/{pid}"
        payslips.append(p)

    return format_response(True, "Payslips retrieved successfully", {
        "payslips": payslips,
        "pagination": {
            "totalRecords": total,
            "currentPage": page,
            "totalPages": math.ceil(total / size) if size else 0
        }
    }, status=200)


@employee_bp.route("/viewpdf/<payslip_id>", methods=["GET"])
@jwt_required()
def view_payslip_pdf(payslip_id):
    try:
        _require_permission("View payslip details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    payslip = db.payslips.find_one({"payslipId": payslip_id})
    if not payslip:
        return format_response(False, "Payslip not found", status=404)

    try:
        _ensure_in_scope(payslip.get("zoneId"))
    except PermissionError:
        return format_response(False, "Payslip not found", status=404)

    emp_snapshot = payslip.get("emp_snapshot")
    if not emp_snapshot:
        return format_response(False, "Payslip does not contain employee snapshot", status=400)

    generated_on = payslip.get("generated_on")
    if not isinstance(generated_on, datetime):
        generated_on = _now_utc()
    generated_on_str = generated_on.strftime("%d-%m-%Y")

    pdf_buf = SalarySlipGenerator(emp_snapshot, current_date=generated_on_str).generate_pdf()

    response = make_response(send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=False
    ))
    response.headers["Content-Disposition"] = f"inline; filename='{payslip.get('filename', 'salary_slip.pdf')}'"
    return response


@employee_bp.route("/download/<payslip_id>", methods=["GET"])
@jwt_required()
def download_payslip_pdf(payslip_id):
    try:
        _require_permission("View payslip details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    payslip = db.payslips.find_one({"payslipId": payslip_id})
    if not payslip:
        return format_response(False, "Payslip not found", status=404)

    try:
        _ensure_in_scope(payslip.get("zoneId"))
    except PermissionError:
        return format_response(False, "Payslip not found", status=404)

    emp_snapshot = payslip.get("emp_snapshot")
    if not emp_snapshot:
        return format_response(False, "Payslip does not contain employee snapshot", status=400)

    generated_on = payslip.get("generated_on")
    if not isinstance(generated_on, datetime):
        generated_on = _now_utc()
    generated_on_str = generated_on.strftime("%d-%m-%Y")

    pdf_buf = SalarySlipGenerator(emp_snapshot, current_date=generated_on_str).generate_pdf()

    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=payslip.get("filename", "salary_slip.pdf")
    )


@employee_bp.route("/getpayslip", methods=["GET"])
@jwt_required()
def get_payslip_details():
    try:
        _require_permission("View payslip details")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    payslip_id = request.args.get("payslipId")
    if not payslip_id:
        return format_response(False, "Query parameter 'payslipId' is required", status=400)

    payslip = db.payslips.find_one({"payslipId": payslip_id}, {"_id": 0})
    if not payslip:
        return format_response(False, "Payslip not found", status=404)

    try:
        _ensure_in_scope(payslip.get("zoneId"))
    except PermissionError:
        return format_response(False, "Payslip not found", status=404)

    return format_response(True, "Payslip details retrieved successfully", {"payslip": _clean_mongo_doc(payslip)}, status=200)


@employee_bp.route("/deletepayslip", methods=["POST"])
@jwt_required()
def delete_payslip():
    try:
        _require_permission("Generate payslip")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    payslip_id = (request.get_json(force=True) or {}).get("payslipId")
    if not payslip_id:
        return format_response(False, "payslipId is required", status=400)

    payslip = db.payslips.find_one({"payslipId": payslip_id})
    if not payslip:
        return format_response(False, "Payslip not found", status=404)

    try:
        _ensure_in_scope(payslip.get("zoneId"))
    except PermissionError:
        return format_response(False, "Payslip not found", status=404)

    res = db.payslips.delete_one({"payslipId": payslip_id})
    if not res.deleted_count:
        return format_response(False, "Payslip not found", status=404)

    return format_response(True, "Payslip deleted successfully", status=200)


@employee_bp.route("/updateSalarySlip", methods=["POST"])
@jwt_required()
def update_salary_slip():
    try:
        _require_permission("Generate payslip")
    except PermissionError as e:
        return format_response(False, str(e), None, 403)

    data = request.get_json(force=True) or {}
    payslip_id = data.get("payslipId")
    if not payslip_id:
        return format_response(False, "payslipId is required", status=400)

    payslip = db.payslips.find_one({"payslipId": payslip_id})
    if not payslip:
        return format_response(False, "Payslip not found", status=404)

    try:
        _ensure_in_scope(payslip.get("zoneId"))
    except PermissionError:
        return format_response(False, "Payslip not found", status=404)

    updates = {}
    now = _now_utc()

    if "salary_structure" in data:
        try:
            incoming = data["salary_structure"] or []
            final_struct = []
            for item in incoming:
                name = item.get("name")
                amt = _parse_float(item.get("amount", 0), f"amount for {name or 'item'}")
                final_struct.append({"name": name, "amount": amt})
        except ValueError as e:
            return format_response(False, str(e), status=400)

        updates["salary_structure"] = final_struct
        updates["emp_snapshot.salary_structure"] = final_struct

    if "lop_days" in data:
        try:
            lop = _parse_float(data["lop_days"], "lop_days")
        except ValueError as e:
            return format_response(False, str(e), status=400)
        updates["lop_days"] = lop
        updates["emp_snapshot.lop"] = lop

    if "Tax Deduction at Source (TDS)" in data or "manual_tds" in data:
        try:
            tds_val = data.get("Tax Deduction at Source (TDS)")
            if tds_val is None:
                tds_val = data.get("manual_tds")
            tds_val = _parse_float(tds_val, "TDS")
        except ValueError as e:
            return format_response(False, str(e), status=400)

        updates["emp_snapshot.Tax Deduction at Source (TDS)"] = tds_val

    if not updates:
        return format_response(False, "No fields provided for update", status=400)

    updates["updated_on"] = now
    db.payslips.update_one({"payslipId": payslip_id}, {"$set": updates})

    payslip = db.payslips.find_one({"payslipId": payslip_id})
    emp_snapshot = payslip.get("emp_snapshot", {})

    generated_on = payslip.get("generated_on") or now
    if not isinstance(generated_on, datetime):
        generated_on = now
    date_str = generated_on.strftime("%d-%m-%Y")

    pdf_buf = SalarySlipGenerator(emp_snapshot, current_date=date_str).generate_pdf()

    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=payslip.get("filename", f"salary_slip_{payslip.get('employeeId','')}.pdf")
    )
