from flask import Blueprint, request
from db import db
from utils import format_response
from datetime import datetime
import uuid

kpi_bp = Blueprint('kpi', __name__, url_prefix='/kpi')

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
    data    = request.get_json(force=True) or {}
    kpi_id  = data.get('kpiId')
    remark  = data.get('remark') or data.get('Remark/comment') or data.get('comment')
    if not kpi_id or remark is None:
        return format_response(False, "Missing kpiId or remark", None, 400)

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
        'remark'     : remark,
        'pointChange': change,
        'status'     : status
    }

    update_doc = {
        '$push': {'punches': punch_record},
        '$set' : {'updatedAt': now}
    }
    if change != 0:
        update_doc['$set']['points'] = new_pts

    db.kpi.update_one({'kpiId': kpi_id}, update_doc)

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
        query['project_name'] = {'$regex': s, '$options': 'i'}

    # Optional date-range filter on startdate
    sd = data.get('startDate')
    ed = data.get('endDate')
    if sd and ed:
        try:
            start_dt = datetime.strptime(sd, '%Y-%m-%d')
            end_dt   = datetime.strptime(ed, '%Y-%m-%d')
        except ValueError:
            return format_response(False, "startDate/endDate must be YYYY-MM-DD", None, 400)
        query['startdate'] = {'$gte': start_dt, '$lte': end_dt}

    # Count + pagination
    total = db.kpi.count_documents(query)
    skip  = (page - 1) * page_size

    # **Always sort by createdAt descending**
    cursor = (
        db.kpi
          .find(query)
          .sort('createdAt', -1)
          .skip(skip)
          .limit(page_size)
    )

    kpis = []
    for k in cursor:
        # Format punches
        punches = []
        for p in k.get('punches', []):
            pd = p.get('punchDate')
            punches.append({
                'punchDate'  : pd.strftime('%Y-%m-%d %H:%M:%S') if hasattr(pd, 'strftime') else None,
                'remark'     : p.get('remark'),
                'status'     : p.get('status')
            })

        # Safe date formatting helper
        def fmt(dt, f='%Y-%m-%d'):
            return dt.strftime(f) if hasattr(dt, 'strftime') else None

        kpis.append({
            'kpiId'       : k.get('kpiId'),
            'employeeId'  : k.get('employeeId'),
            'employeeName': k.get('employeeName'),
            'projectName' : k.get('project_name'),
            'startdate'   : fmt(k.get('startdate')),
            'deadline'    : fmt(k.get('deadline')),
            'Remark'      : k.get('remark'),
            'points'      : k.get('points'),
            'createdAt'   : k.get('createdAt').isoformat() if hasattr(k.get('createdAt'), 'isoformat') else None,
            'updatedAt'   : k.get('updatedAt').isoformat() if hasattr(k.get('updatedAt'), 'isoformat') else None,
            'punches'     : punches
        })

    return format_response(True, "KPIs retrieved", {
        'page'     : page,
        'pageSize' : page_size,
        'total'    : total,
        'kpis'     : kpis
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
