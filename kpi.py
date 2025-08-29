from flask import Blueprint, request,make_response
from db import db
from utils import format_response
from datetime import datetime
import uuid
import csv, io

kpi_bp = Blueprint('kpi', __name__, url_prefix='/kpi')


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

def _parse_date(s, field_name):
    try:
        return datetime.strptime(s, '%Y-%m-%d')
    except Exception:
        raise ValueError(f"Invalid {field_name}, must be YYYY-MM-DD")

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
        startdate = datetime.strptime(start_str, '%Y-%m-%d')
        deadline  = datetime.strptime(deadline_str, '%Y-%m-%d')
    except ValueError:
        return format_response(False, "Incorrect date format, should be YYYY-MM-DD", None, 400)

    now = datetime.utcnow()
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

    updates['updatedAt'] = datetime.utcnow()
    result = db.kpi.update_one({'kpiId': kpi_id}, {'$set': updates})
    if result.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    kpi = db.kpi.find_one({'kpiId': kpi_id})
    payload = {
        'kpiId'       : kpi['kpiId'],
        'employeeId'  : kpi['employeeId'],
        'employeeName': kpi['employeeName'],
        'projectName' : kpi['project_name'],
        'startdate'   : kpi['startdate'].strftime('%Y-%m-%d'),
        'deadline'    : kpi['deadline'].strftime('%Y-%m-%d'),
        'Remark'      : kpi['remark'],
        'points'      : kpi['points'],
        'createdAt'   : kpi['createdAt'].isoformat(),
        'updatedAt'   : kpi['updatedAt'].isoformat()
    }
    return format_response(True, "KPI updated", payload, 200)


@kpi_bp.route('/punch', methods=['POST'])
def punchKpi():
    data   = request.get_json(force=True) or {}
    kpi_id = data.get('kpiId')

    # remark is OPTIONAL
    remark_raw = data.get('remark') or data.get('Remark/comment') or data.get('comment')
    remark = "" if remark_raw is None else str(remark_raw).strip()

    if not kpi_id:
        return format_response(False, "Missing kpiId", None, 400)

    kpi = db.kpi.find_one({'kpiId': kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    now      = datetime.utcnow()
    deadline = kpi.get('deadline')
    old_pts  = kpi.get('points', -1)

    on_time = isinstance(deadline, datetime) and now.date() <= deadline.date()
    if on_time and old_pts == -1:
        new_pts = 1
        change  = new_pts - old_pts
    else:
        new_pts = old_pts
        change  = 0

    status = "On Time" if on_time else "Late Submission"

    punch_record = {
        'punchDate'  : now,
        'remark'     : remark,   # may be ""
        'pointChange': change,
        'status'     : status
    }

    update_doc = {
        '$push': {'punches': punch_record},
        '$set' : {'updatedAt': now}
    }
    if change != 0:
        update_doc['$set']['points'] = new_pts

    # --- Save + error handling ---
    try:
        res = db.kpi.update_one({'kpiId': kpi_id}, update_doc)
    except Exception as e:
        return format_response(False, f"Punch failed to save: {e}", 500)

    if not getattr(res, 'acknowledged', True) or res.matched_count == 0:
        return format_response(False, "Punch not saved. Please try again.",500)

    # Success response
    return format_response(True, "Punch recorded", {
        'kpiId'      : kpi_id,
        'punchDate'  : now.strftime('%Y-%m-%d %H:%M:%S'),
        'remark'     : remark,
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

    # Optional date-range filter on startdate (inclusive)
    sd = data.get('startDate')
    ed = data.get('endDate')
    if sd and ed:
        try:
            start_dt = datetime.strptime(sd, '%Y-%m-%d')
            end_dt   = datetime.strptime(ed, '%Y-%m-%d')
        except ValueError:
            return format_response(False, "startDate/endDate must be YYYY-MM-DD", None, 400)
        query['startdate'] = {'$gte': start_dt, '$lte': end_dt}

    # Optional employeeIds filter (accept list OR single string)
    # also accept legacy/misspelled key 'employesids'
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
                'punchDate': pd.strftime('%Y-%m-%d %H:%M:%S') if hasattr(pd, 'strftime') else (pd or None),
                'remark'   : p.get('remark'),
                'status'   : p.get('status')
            })

        def fmt(dt, f='%Y-%m-%d'):
            return dt.strftime(f) if hasattr(dt, 'strftime') else (dt if isinstance(dt, str) else None)

        kpis.append({
            'kpiId'       : k.get('kpiId'),
            'employeeId'  : k.get('employeeId'),
            'employeeName': k.get('employeeName'),
            'projectName' : k.get('project_name'),
            'startdate'   : fmt(k.get('startdate')),
            'deadline'    : fmt(k.get('deadline')),
            'Remark'      : k.get('remark'),
            'points'      : k.get('points'),
            'qualityPoints': k.get('qualityPoints'),   # <— ADD THIS
            'createdAt'   : k.get('createdAt').isoformat() if hasattr(k.get('createdAt'), 'isoformat') else (k.get('createdAt') or None),
            'updatedAt'   : k.get('updatedAt').isoformat() if hasattr(k.get('updatedAt'), 'isoformat') else (k.get('updatedAt') or None),
            'punches'     : punches
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
        'startdate'   : kpi['startdate'].strftime('%Y-%m-%d'),
        'deadline'    : kpi['deadline'].strftime('%Y-%m-%d'),
        'Remark'      : kpi['remark'],
        'points'      : kpi['points']
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

    # Date‐range filter on startdate
    sd = data.get('startDate')
    ed = data.get('endDate')
    if sd and ed:
        try:
            start_dt = datetime.strptime(sd, '%Y-%m-%d')
            end_dt   = datetime.strptime(ed, '%Y-%m-%d')
        except ValueError:
            return format_response(False, "startDate/endDate must be YYYY-MM-DD", None, 400)
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
                'punchDate'  : pd.strftime('%Y-%m-%d %H:%M:%S') if hasattr(pd, 'strftime') else None,
                'remark'     : p.get('remark'),
                'status'     : p.get('status')
            })

        # Safe date formatting
        def fmt(dt, f='%Y-%m-%d'):
            return dt.strftime(f) if hasattr(dt, 'strftime') else None

        created_str = kpi.get('createdAt').isoformat() if hasattr(kpi.get('createdAt'), 'isoformat') else None
        updated_str = kpi.get('updatedAt').isoformat() if hasattr(kpi.get('updatedAt'), 'isoformat') else None

        kpis.append({
            'kpiId'       : kpi.get('kpiId'),
            'employeeId'  : kpi.get('employeeId'),
            'employeeName': kpi.get('employeeName'),
            'projectName' : kpi.get('project_name'),
            'startdate'   : fmt(kpi.get('startdate')),
            'deadline'    : fmt(kpi.get('deadline')),
            'Remark'      : kpi.get('remark'),
            'points'      : kpi.get('points'),
            'qualityPoints': kpi.get('qualityPoints'),  # <— ADD THIS
            'createdAt'   : created_str,
            'updatedAt'   : updated_str,
            'punches'     : punches_list
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

    now = datetime.utcnow()
    res = db.kpi.update_one(
        {'kpiId': kpi_id},
        {'$set': {'qualityPoints': qp, 'updatedAt': now}}
    )
    if res.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    return format_response(True, "Quality points saved", {
        'kpiId'        : kpi_id,
        'qualityPoints': qp,
        'updatedAt'    : now.isoformat()
    }, 200)








@kpi_bp.route('/exportCsv', methods=['POST'])
def export_csv():
    """
    Export KPIs as CSV using the same filters as getAll/getByEmployeeId.
    - If 'employeeId' is provided, exports that employee's view.
    - Else, behaves like getAll (optionally filter by employeeIds).
    - Pass {"all": true} to export all filtered rows (ignores pagination).
    - CSV intentionally EXCLUDES any ID fields (kpiId, employeeId).
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

    # Date range on startdate
    if sd and ed:
        try:
            start_dt = datetime.strptime(sd, '%Y-%m-%d')
            end_dt = datetime.strptime(ed, '%Y-%m-%d')
        except ValueError:
            return format_response(False, "startDate/endDate must be YYYY-MM-DD", None, 400)
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
        return dt.strftime(f) if hasattr(dt, 'strftime') else (dt if isinstance(dt, str) else '')

    def fmt_iso(dt):
        return dt.isoformat() if hasattr(dt, 'isoformat') else (dt if isinstance(dt, str) else '')

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
            'LastPunchDate'  : (lp_date.strftime('%Y-%m-%d %H:%M:%S') if hasattr(lp_date, 'strftime') else (lp_date or '')),
            'LastPunchStatus': last.get('status') or '',
            'LastPunchRemark': last.get('remark') or ''
        })

    # Strictly keep only declared columns to avoid DictWriter errors
    filtered_rows = [{k: r.get(k, '') for k in fieldnames} for r in rows]

    output = io.StringIO()
    # Optional Excel-friendly BOM:
    # output.write('\ufeff')

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(filtered_rows)

    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="kpi_export_{ts}.csv"'
    return resp