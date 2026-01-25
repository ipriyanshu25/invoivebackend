import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt

from db import db
from utils import format_response

zones_bp = Blueprint("zones", __name__, url_prefix="/zones")
UTC = ZoneInfo("UTC")

# -----------------------------
# Helpers
# -----------------------------
def _now_utc():
    return datetime.now(UTC)

def _scope():
    claims = get_jwt() or {}
    role = (claims.get("role") or "").lower()
    zone_ids = claims.get("zoneIds") or []
    is_admin_all = role == "admin" and (not zone_ids or "*" in zone_ids)
    return role, zone_ids, is_admin_all

def _require_admin():
    role, _z, _all = _scope()
    if role != "admin":
        raise PermissionError("Admin only")

def _zone_query(field="zoneId"):
    """
    Admin(all zones) => no filter
    Subadmin => restrict to their zoneIds
    """
    role, zone_ids, is_admin_all = _scope()
    if is_admin_all:
        return {}
    return {field: {"$in": zone_ids}}

def _ensure_zone_allowed(zone_id: str | None):
    role, zone_ids, is_admin_all = _scope()
    if is_admin_all:
        return
    if not zone_id or zone_id not in zone_ids:
        raise PermissionError("Forbidden (different zone)")

def _validate_tz(tz_name: str):
    try:
        ZoneInfo(tz_name)
        return True
    except Exception:
        return False

def _normalize_code(code: str):
    code = (code or "").upper().strip()
    code = re.sub(r"[^A-Z0-9]", "", code)[:6]
    return code

def _norm_name(name: str):
    return (name or "").strip()

def _count_zone_links(zone_id: str):
    """
    Used for safe delete checks.
    """
    emp_count = db.employees.count_documents({"zoneId": zone_id})
    kpi_count = db.kpi.count_documents({"zoneId": zone_id})
    sub_count = db.subadmin.count_documents({"zoneIds": zone_id})  # if stored as list
    # fallback if older data stored as single zoneId (optional)
    sub_count2 = db.subadmin.count_documents({"zoneId": zone_id})

    return {
        "employees": emp_count,
        "kpis": kpi_count,
        "subadmins": sub_count + sub_count2,
    }

# -----------------------------
# Routes
# -----------------------------

@zones_bp.route("/create", methods=["POST"])
@jwt_required()
def create_zone():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        name = _norm_name(data.get("name"))
        code = _normalize_code(data.get("code"))
        timezone = (data.get("timezone") or "Asia/Kolkata").strip()
        is_active = bool(data.get("isActive", True))

        if not name or not code:
            return format_response(False, "name and code are required", None, 400)

        if not _validate_tz(timezone):
            return format_response(False, "Invalid timezone", None, 400)

        # unique checks
        if db.zones.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
            return format_response(False, "Zone name already exists", None, 409)
        if db.zones.find_one({"code": code}):
            return format_response(False, "Zone code already exists", None, 409)

        zone_id = str(uuid.uuid4())
        now = _now_utc()

        db.zones.insert_one({
            "zoneId": zone_id,
            "name": name,
            "code": code,
            "timezone": timezone,
            "isActive": is_active,
            "createdAt": now,
            "updatedAt": now,
        })

        return format_response(True, "Zone created", {"zoneId": zone_id}, 201)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@zones_bp.route("/getrecord", methods=["GET"])
@jwt_required()
def get_record():
    try:
        zone_id = (request.args.get("zoneId") or "").strip()
        if not zone_id:
            return format_response(False, "zoneId required", None, 400)

        query = {"zoneId": zone_id}
        query.update(_zone_query("zoneId"))  # ✅ restrict subadmin

        z = db.zones.find_one(query, {"_id": 0})
        if not z:
            return format_response(False, "Zone not found", None, 404)

        return format_response(True, "Zone fetched", {"zone": z}, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


@zones_bp.route("/list", methods=["POST"])
@jwt_required()
def list_zones():
    try:
        data = request.get_json(force=True) or {}
        search = (data.get("search") or "").strip()
        include_inactive = bool(data.get("includeInactive"))

        page = max(int(data.get("page", 1)), 1)
        size = max(int(data.get("pageSize", 20)), 1)

        query = {}
        query.update(_zone_query("zoneId"))

        role, _z, _all = _scope()

        # Only admins can request inactive results
        if role != "admin":
            include_inactive = False

        if not include_inactive:
            query["isActive"] = True

        if search:
            rx = {"$regex": re.escape(search), "$options": "i"}
            query["$or"] = [{"name": rx}, {"code": rx}]

        total = db.zones.count_documents(query)
        cursor = (
            db.zones.find(query, {"_id": 0})
            .sort("createdAt", -1)
            .skip((page - 1) * size)
            .limit(size)
        )

        return format_response(True, "Zones fetched", {
            "zones": list(cursor),
            "total": total,
            "page": page,
            "pageSize": size
        }, 200)

    except Exception:
        return format_response(False, "Internal server error", None, 500)


@zones_bp.route("/update", methods=["POST"])
@jwt_required()
def update_zone():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        zone_id = (data.get("zoneId") or "").strip()
        if not zone_id:
            return format_response(False, "zoneId is required", None, 400)

        # allow BOTH formats:
        # 1) { zoneId, updates: {...} }
        # 2) { zoneId, name, code, timezone, isActive }
        updates = data.get("updates") or {}
        if not updates:
            updates = {k: data.get(k) for k in ["name", "code", "timezone", "isActive"] if k in data}

        if not updates:
            return format_response(False, "updates required", None, 400)

        existing = db.zones.find_one({"zoneId": zone_id})
        if not existing:
            return format_response(False, "Zone not found", None, 404)

        set_doc = {}

        if "name" in updates:
            nm = _norm_name(updates.get("name"))
            if not nm:
                return format_response(False, "name cannot be empty", None, 400)
            clash = db.zones.find_one({
                "zoneId": {"$ne": zone_id},
                "name": {"$regex": f"^{re.escape(nm)}$", "$options": "i"}
            })
            if clash:
                return format_response(False, "Zone name already exists", None, 409)
            set_doc["name"] = nm

        if "code" in updates:
            cd = _normalize_code(updates.get("code"))
            if not cd:
                return format_response(False, "code cannot be empty", None, 400)
            clash = db.zones.find_one({"zoneId": {"$ne": zone_id}, "code": cd})
            if clash:
                return format_response(False, "Zone code already exists", None, 409)
            set_doc["code"] = cd

        if "timezone" in updates:
            tz = (updates.get("timezone") or "").strip()
            if not tz:
                return format_response(False, "timezone cannot be empty", None, 400)
            if not _validate_tz(tz):
                return format_response(False, "Invalid timezone", None, 400)
            set_doc["timezone"] = tz

        if "isActive" in updates:
            set_doc["isActive"] = bool(updates["isActive"])

        if not set_doc:
            return format_response(False, "No valid fields in updates", None, 400)

        set_doc["updatedAt"] = _now_utc()
        db.zones.update_one({"zoneId": zone_id}, {"$set": set_doc})

        z = db.zones.find_one({"zoneId": zone_id}, {"_id": 0})
        return format_response(True, "Zone updated", {"zone": z}, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


# ✅ Soft Deactivate (safe)
@zones_bp.route("/deactivate", methods=["POST"])
@jwt_required()
def deactivate_zone():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        zone_id = (data.get("zoneId") or "").strip()
        if not zone_id:
            return format_response(False, "zoneId required", None, 400)

        res = db.zones.update_one(
            {"zoneId": zone_id},
            {"$set": {"isActive": False, "updatedAt": _now_utc()}}
        )
        if not res.matched_count:
            return format_response(False, "Zone not found", None, 404)

        return format_response(True, "Zone deactivated", None, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


# ✅ Reactivate (optional but useful)
@zones_bp.route("/activate", methods=["POST"])
@jwt_required()
def activate_zone():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        zone_id = (data.get("zoneId") or "").strip()
        if not zone_id:
            return format_response(False, "zoneId required", None, 400)

        res = db.zones.update_one(
            {"zoneId": zone_id},
            {"$set": {"isActive": True, "updatedAt": _now_utc()}}
        )
        if not res.matched_count:
            return format_response(False, "Zone not found", None, 404)

        return format_response(True, "Zone activated", None, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)


# ✅ Hard Delete (permanent)
@zones_bp.route("/harddelete", methods=["POST"])
@jwt_required()
def hard_delete_zone():
    """
    Permanently deletes zone.

    Safety:
    - By default: blocks delete if employees/kpis/subadmins linked.
    - Pass force=true to override.
    """
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        zone_id = (data.get("zoneId") or "").strip()
        force = bool(data.get("force", False))

        if not zone_id:
            return format_response(False, "zoneId required", None, 400)

        # check exists
        existing = db.zones.find_one({"zoneId": zone_id})
        if not existing:
            return format_response(False, "Zone not found", None, 404)

        links = _count_zone_links(zone_id)
        has_links = (links["employees"] > 0 or links["kpis"] > 0 or links["subadmins"] > 0)

        if has_links and not force:
            return format_response(
                False,
                "Cannot hard delete zone because it has linked records. Deactivate instead or pass force=true.",
                {"links": links},
                409
            )

        # If force=true, optionally cleanup subadmins zoneIds arrays
        if force:
            # remove from subadmin.zoneIds arrays
            db.subadmin.update_many(
                {"zoneIds": zone_id},
                {"$pull": {"zoneIds": zone_id}, "$set": {"updatedAt": _now_utc()}}
            )

        res = db.zones.delete_one({"zoneId": zone_id})
        if not res.deleted_count:
            return format_response(False, "Zone not found", None, 404)

        return format_response(True, "Zone permanently deleted", {"deletedZoneId": zone_id, "links": links}, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)
