from flask import Blueprint, request, make_response
from db import db
from utils import format_response
import uuid
import csv, io

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

kpi_bp = Blueprint('kpi', __name__, url_prefix='/kpi')


# ---------- Helpers (timezone-safe) ----------

def _normalize_employee_ids(raw) -> list[str]:
    """Accept single or multiple IDs and return a clean list[str]."""
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
        # support comma/space separated: "E1,E2" or "E1 E2"
        parts = [p.strip() for p in s.replace(",", " ").split()]
        return [p for p in parts if p]
    return []


def _coerce_quality_point(raw):
    """
    Accept -1 or 1 (int or string). Also accept 'negative'/'positive' etc.
    """
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


def _parse_date_ist(s: str, field_name: str) -> datetime:
    """
    Parse a YYYY-MM-DD string and return an IST-aware datetime at 00:00:00.
    """
    try:
        d = datetime.strptime(s, '%Y-%m-%d')
        return d.replace(tzinfo=IST)
    except Exception:
        raise ValueError(f"Invalid {field_name}, must be YYYY-MM-DD")


def _as_ist(dt):
    """
    Convert any datetime to IST for display.
    - If naive: assume UTC for legacy data, then convert to IST.
    - If aware: convert to IST.
    """
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        # legacy stored values (previously used utcnow() / naive) -> treat as UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def _fmt_date(dt, f='%Y-%m-%d'):
    """
    Format a datetime in IST. Accepts naive/aware or str.
    """
    if hasattr(dt, 'strftime'):
        return _as_ist(dt).strftime(f)
    return dt if isinstance(dt, str) else None


def _fmt_iso(dt):
    """
    ISO format with timezone (+05:30). Accepts naive/aware or str.
    """
    if hasattr(dt, 'isoformat'):
        return _as_ist(dt).isoformat()
    return dt if isinstance(dt, str) else None


# ---------- Routes ----------

@kpi_bp.route('/addkpi', methods=['POST'])
def addKpi():
    data = request.get_json() or {}
    employee_id  = data.get('employeeId')
    project_name = data.get('projectName')
    start_str    = data.get('startdate')
    deadline_str = data.get('deadline')
    remark       = data.get('Remark/comment') or data.get('Remark') or data.get('comment')

    if not all([employee_id, project_name, start_str, deadline_str]):
        return format_response(False, "Missing required fields", None, 400)

    employee = db.employees.find_one({'employeeId': employee_id})
    if not employee:
        return format_response(False, "Employee not found", None, 404)

    try:
        startdate = _parse_date_ist(start_str, 'startdate')
        deadline  = _parse_date_ist(deadline_str, 'deadline')
    except ValueError as ve:
        return format_response(False, str(ve), None, 400)

    now = datetime.now(IST)
    kpi_id = str(uuid.uuid4())
    kpi_doc = {
        'kpiId'        : kpi_id,
        'employeeId'   : employee_id,
        'employeeName' : employee.get('name'),
        'project_name' : project_name,
        'startdate'    : startdate,
        'deadline'     : deadline,
        'remark'       : remark,
        'points'       : -1,
        'punches'      : [],
        'createdAt'    : now,
        'updatedAt'    : now
    }
    db.kpi.insert_one(kpi_doc)
    return format_response(True, "KPI added", {'kpiId': kpi_id}, 201)


@kpi_bp.route('/updateKPi', methods=['POST'])
def updateKpi():
    data   = request.get_json() or {}
    kpi_id = data.get('kpiId')
    if not kpi_id:
        return format_response(False, "Missing KPI ID", None, 400)

    updates = {}
    if 'projectName' in data:
        updates['project_name'] = data['projectName']
    remark = data.get('Remark') or data.get('comment')
    if remark is not None:
        updates['remark'] = remark

    if not updates:
        return format_response(False, "No fields to update", None, 400)

    updates['updatedAt'] = datetime.now(IST)
    result = db.kpi.update_one({'kpiId': kpi_id}, {'$set': updates})
    if result.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    kpi = db.kpi.find_one({'kpiId': kpi_id})
    payload = {
        'kpiId'       : kpi['kpiId'],
        'employeeId'  : kpi['employeeId'],
        'employeeName': kpi['employeeName'],
        'projectName' : kpi['project_name'],
        'startdate'   : _fmt_date(kpi['startdate']),
        'deadline'    : _fmt_date(kpi['deadline']),
        'Remark'      : kpi.get('remark'),
        'points'      : kpi.get('points'),
        'createdAt'   : _fmt_iso(kpi.get('createdAt')),
        'updatedAt'   : _fmt_iso(kpi.get('updatedAt')),
    }
    return format_response(True, "KPI updated", payload, 200)


@kpi_bp.route('/punch', methods=['POST'])
def punchKpi():
    data   = request.get_json(force=True) or {}
    kpi_id = data.get('kpiId')

    if not kpi_id:
        return format_response(False, "Missing kpiId", None, 400)

    kpi = db.kpi.find_one({'kpiId': kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    # --- Always use IST ---
    now = datetime.now(IST)

    deadline = kpi.get('deadline')
    if isinstance(deadline, datetime):
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=IST)
        on_time = now.date() <= deadline.astimezone(IST).date()
    else:
        on_time = False

    old_pts = kpi.get('points', -1)
    if on_time and old_pts == -1:
        new_pts = 1
        change  = new_pts - old_pts
    else:
        new_pts = old_pts
        change  = 0

    status = "On Time" if on_time else "Late Submission"

    punch_record = {
        'punchDate'  : now,  # stored in IST
        'remark'     : data.get('remark', ''),
        'pointChange': change,
        'status'     : status
    }

    update_doc = {
        '$push': {'punches': punch_record},
        '$set' : {'updatedAt': now, 'points': new_pts}
    }

    res = db.kpi.update_one({'kpiId': kpi_id}, update_doc)
    if res.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    # --- Force IST output ---
    return format_response(True, "Punch recorded", {
        'kpiId'      : kpi_id,
        'punchDate'  : now.isoformat(sep=' ', timespec='seconds'),
        'remark'     : data.get('remark', ''),
        'pointChange': change,
        'status'     : status,
        'points'     : new_pts,
        'updatedAt'  : now.isoformat()
    }, 200)


@kpi_bp.route('/getAll', methods=['POST'])
def getAll():
    data = request.get_json() or {}

    # Pagination
    try:
        page      = int(data.get('page', 1))
        page_size = int(data.get('pageSize', 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    # Build search filter
    query = {}
    if (s := (data.get('search') or '').strip()):
        rx = {'$regex': s, '$options': 'i'}
        query['$or'] = [
            {'project_name': rx},
            {'employeeName': rx},
        ]

    # Optional date-range filter on startdate (inclusive, interpreted in IST)
    sd = data.get('startDate')
    ed = data.get('endDate')
    if sd and ed:
        try:
            start_dt = _parse_date_ist(sd, 'startDate')
            # inclusive end -> set to 23:59:59 IST
            end_dt   = _parse_date_ist(ed, 'endDate') + timedelta(hours=23, minutes=59, seconds=59)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)
        query['startdate'] = {'$gte': start_dt, '$lte': end_dt}

    # Optional employeeIds filter (accept list OR single string)
    employee_ids_raw = data.get('employeeIds', data.get('employesids'))
    employee_ids: list[str] = []
    if isinstance(employee_ids_raw, str) and employee_ids_raw.strip():
        employee_ids = [employee_ids_raw.strip()]
    elif isinstance(employee_ids_raw, list):
        employee_ids = [str(e).strip() for e in employee_ids_raw if str(e).strip()]

    if employee_ids:
        query['employeeId'] = {'$in': employee_ids}

    # Count after full query is built
    total = db.kpi.count_documents(query)

    # Pagination window
    skip = (page - 1) * page_size
    if skip < 0:
        skip = 0

    # Sorting (keep original behavior)
    sort_field = 'createdAt'
    sort_dir = -1

    cursor = (
        db.kpi
          .find(query)
          .sort(sort_field, sort_dir)
          .skip(skip)
          .limit(page_size)
    )

    kpis = []
    for k in cursor:
        punches = []
        for p in k.get('punches', []):
            pd = p.get('punchDate')
            punches.append({
                'punchDate': (_as_ist(pd).strftime('%Y-%m-%d %H:%M:%S') if hasattr(pd, 'strftime') else (pd or None)),
                'remark'   : p.get('remark'),
                'status'   : p.get('status')
            })

        kpis.append({
            'kpiId'        : k.get('kpiId'),
            'employeeId'   : k.get('employeeId'),
            'employeeName' : k.get('employeeName'),
            'projectName'  : k.get('project_name'),
            'startdate'    : _fmt_date(k.get('startdate')),
            'deadline'     : _fmt_date(k.get('deadline')),
            'Remark'       : k.get('remark'),
            'points'       : k.get('points'),
            'qualityPoints': k.get('qualityPoints'),
            'createdAt'    : _fmt_iso(k.get('createdAt')),
            'updatedAt'    : _fmt_iso(k.get('updatedAt')),
            'punches'      : punches
        })

    return format_response(True, "KPIs retrieved", {
        'page'    : page,
        'pageSize': page_size,
        'total'   : total,
        'kpis'    : kpis
    }, 200)


@kpi_bp.route('/deleteKpi', methods=['POST'])
def deleteKpi():
    data   = request.get_json(force=True) or {}
    kpi_id = data.get('kpiId')
    if not kpi_id:
        return format_response(False, "Missing KPI ID", None, 400)

    result = db.kpi.delete_one({'kpiId': kpi_id})
    if result.deleted_count == 0:
        return format_response(False, "KPI not found", None, 404)

    return format_response(True, "KPI deleted", None, 200)


@kpi_bp.route('/getByKpiId/<kpi_id>', methods=['GET'])
def getByKpiId(kpi_id):
    kpi = db.kpi.find_one({'kpiId': kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    data = {
        'kpiId'       : kpi['kpiId'],
        'employeeId'  : kpi['employeeId'],
        'employeeName': kpi['employeeName'],
        'projectName' : kpi['project_name'],
        'startdate'   : _fmt_date(kpi['startdate']),
        'deadline'    : _fmt_date(kpi['deadline']),
        'Remark'      : kpi.get('remark'),
        'points'      : kpi.get('points')
    }
    return format_response(True, "KPI retrieved", data, 200)


@kpi_bp.route('/getByEmployeeId', methods=['POST'])
def getByEmployeeId():
    data = request.get_json() or {}
    employee_id = data.get('employeeId')
    if not employee_id:
        return format_response(False, "Missing employeeId", None, 400)

    # Build query
    query = {'employeeId': employee_id}
    if (s := (data.get('search') or '').strip()):
        query['project_name'] = {'$regex': s, '$options': 'i'}

    # Date‐range filter on startdate (inclusive, IST)
    sd = data.get('startDate')
    ed = data.get('endDate')
    if sd and ed:
        try:
            start_dt = _parse_date_ist(sd, 'startDate')
            end_dt   = _parse_date_ist(ed, 'endDate') + timedelta(hours=23, minutes=59, seconds=59)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)
        query['startdate'] = {'$gte': start_dt, '$lte': end_dt}

    # Pagination params
    try:
        page      = int(data.get('page', 1))
        page_size = int(data.get('pageSize', 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    total = db.kpi.count_documents(query)
    skip  = (page - 1) * page_size

    # Always sort by createdAt descending
    cursor = (
        db.kpi
          .find(query)
          .sort('createdAt', -1)
          .skip(skip)
          .limit(page_size)
    )

    kpis = []
    for kpi in cursor:
        # Format punches
        punches_list = []
        for p in kpi.get('punches', []):
            pd = p.get('punchDate')
            punches_list.append({
                'punchDate'  : (_as_ist(pd).strftime('%Y-%m-%d %H:%M:%S') if hasattr(pd, 'strftime') else None),
                'remark'     : p.get('remark'),
                'status'     : p.get('status')
            })

        created_str = _fmt_iso(kpi.get('createdAt'))
        updated_str = _fmt_iso(kpi.get('updatedAt'))

        kpis.append({
            'kpiId'        : kpi.get('kpiId'),
            'employeeId'   : kpi.get('employeeId'),
            'employeeName' : kpi.get('employeeName'),
            'projectName'  : kpi.get('project_name'),
            'startdate'    : _fmt_date(kpi.get('startdate')),
            'deadline'     : _fmt_date(kpi.get('deadline')),
            'Remark'       : kpi.get('remark'),
            'points'       : kpi.get('points'),
            'qualityPoints': kpi.get('qualityPoints'),
            'createdAt'    : created_str,
            'updatedAt'    : updated_str,
            'punches'      : punches_list
        })

    return format_response(
        True,
        f"Found {len(kpis)} KPI(s) for employee {employee_id}",
        {
            'page'     : page,
            'pageSize' : page_size,
            'total'    : total,
            'kpis'     : kpis
        },
        200
    )


@kpi_bp.route('/setQualityPoint', methods=['POST'])    # alias for UI usage
def add_quality_points():
    data = request.get_json(force=True) or {}
    kpi_id = data.get('kpiId') or data.get('kpi_id')
    qp_raw = data.get('qualityPoint') or data.get('qualityPoints') or data.get('quality_point')

    if not kpi_id or qp_raw is None:
        return format_response(False, "Missing kpiId or qualityPoint", None, 400)

    try:
        qp = _coerce_quality_point(qp_raw)
    except ValueError as e:
        return format_response(False, str(e), None, 400)

    now = datetime.now(IST)
    res = db.kpi.update_one(
        {'kpiId': kpi_id},
        {'$set': {'qualityPoints': qp, 'updatedAt': now}}
    )
    if res.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    return format_response(True, "Quality points saved", {
        'kpiId'        : kpi_id,
        'qualityPoints': qp,
        'updatedAt'    : _fmt_iso(now)
    }, 200)


@kpi_bp.route('/exportCsv', methods=['POST'])
def export_csv():
    """
    Export KPIs as CSV using the same filters as getAll/getByEmployeeId.
    - If 'employeeId' is provided, exports that employee's view.
    - Else, behaves like getAll (optionally filter by employeeIds).
    - Pass {"all": true} to export all filtered rows (ignores pagination).
    - CSV intentionally EXCLUDES any ID fields (kpiId, employeeId).
    - All dates in CSV are shown in IST.
    """
    data = request.get_json() or {}

    # Common filters
    search = (data.get('search') or '').strip()
    sd = data.get('startDate')
    ed = data.get('endDate')
    sort_by = (data.get('sortBy') or 'createdAt').strip()
    sort_order = (data.get('sortOrder') or 'desc').lower()
    sort_dir = -1 if sort_order == 'desc' else 1

    # Pagination (used unless all=True)
    try:
        page = int(data.get('page', 1))
        page_size = int(data.get('pageSize', 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    export_all = bool(data.get('all') or data.get('exportAll'))

    # Build query
    query = {}
    # Employee-specific or global list
    employee_ids = _normalize_employee_ids(data.get('employeeId'))

    if employee_ids:
        # If one ID -> equality; if many -> $in
        query['employeeId'] = employee_ids[0] if len(employee_ids) == 1 else {'$in': employee_ids}

    # Search filter (applies regardless of employee filter)
    if search:
        rx = {'$regex': search, '$options': 'i'}
        query['$or'] = [{'project_name': rx}, {'employeeName': rx}]

    # Date range on startdate (inclusive, IST)
    if sd and ed:
        try:
            start_dt = _parse_date_ist(sd, 'startDate')
            end_dt   = _parse_date_ist(ed, 'endDate') + timedelta(hours=23, minutes=59, seconds=59)
        except ValueError as ve:
            return format_response(False, str(ve), None, 400)
        query['startdate'] = {'$gte': start_dt, '$lte': end_dt}

    # Sorting: allow 'startdate'/'deadline'/'createdAt'/'updatedAt'
    allowed_sort = {'startdate', 'deadline', 'createdAt', 'updatedAt'}
    sort_field = sort_by if sort_by in allowed_sort else 'createdAt'

    cursor = db.kpi.find(query).sort(sort_field, sort_dir)

    # Pagination window (unless exporting all)
    if not export_all:
        skip = max(0, (page - 1) * page_size)
        cursor = cursor.skip(skip).limit(page_size)

    # --- Compose CSV (NO ID COLUMNS) ---
    def fmt_dt(dt, f='%Y-%m-%d'):
        return _fmt_date(dt, f) or ''

    fieldnames = [
        'EmployeeName','ProjectName','StartDate','Deadline',
        'Remark','DeadlinePoints','QualityPoints',
        'LastPunchDate','LastPunchStatus','LastPunchRemark'
    ]

    rows = []
    for k in cursor:
        punches = k.get('punches', [])
        last = punches[-1] if punches else {}
        lp_date = last.get('punchDate')

        rows.append({
            # NOTE: no IDs here (kpiId/employeeId excluded)
            'EmployeeName'   : k.get('employeeName', ''),
            'ProjectName'    : k.get('project_name', ''),
            'StartDate'      : fmt_dt(k.get('startdate')),
            'Deadline'       : fmt_dt(k.get('deadline')),
            'Remark'         : k.get('remark', ''),
            'DeadlinePoints' : k.get('points', ''),
            'QualityPoints'  : k.get('qualityPoints', ''),
            'LastPunchDate'  : (_as_ist(lp_date).strftime('%Y-%m-%d %H:%M:%S') if hasattr(lp_date, 'strftime') else (lp_date or '')),
            'LastPunchStatus': last.get('status') or '',
            'LastPunchRemark': last.get('remark') or ''
        })

    # Strictly keep only declared columns to avoid DictWriter errors
    filtered_rows = [{k: r.get(k, '') for k in fieldnames} for r in rows]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(filtered_rows)

    ts = datetime.now(IST).strftime('%Y%m%d_%H%M%S')
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="kpi_export_{ts}.csv"'
    return resp
