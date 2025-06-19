import uuid
from flask import Blueprint, request
from db import db
from utils import format_response
from datetime import datetime

# Blueprint for KPI routes
kpi_bp = Blueprint('kpi', __name__, url_prefix='/kpi')

@kpi_bp.route('/addkpi', methods=['POST'])
def addKpi():
    data = request.get_json() or {}
    employee_id = data.get('employeeId')
    project_name = data.get('projectName')
    due_date_str = data.get('duedate')
    submitted_date_str = data.get('submittedDate')
    remark = data.get('Remark/comment') or data.get('Remark') or data.get('comment')
    points = data.get('points')

    # Validate required fields
    if not all([employee_id, project_name, due_date_str, submitted_date_str, points]):
        return format_response(False, "Missing required fields", None, 400)

    # Verify employee exists
    employee = db.employees.find_one({'employeeId': employee_id})
    if not employee:
        return format_response(False, "Employee not found", None, 404)
    employee_name = employee.get('name')

    # Parse dates
    try:
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        submitted_date = datetime.strptime(submitted_date_str, '%Y-%m-%d')
    except ValueError:
        return format_response(False, "Incorrect date format, should be YYYY-MM-DD", None, 400)

    # Generate unique KPI ID
    kpi_id = str(uuid.uuid4())

    # Create document including employee name
    kpi_doc = {
        'kpiId': kpi_id,
        'employeeId': employee_id,
        'employeeName': employee_name,
        'project_name': project_name,
        'due_date': due_date,
        'submitted_date': submitted_date,
        'remark': remark,
        'points': int(points)
    }
    db.kpi.insert_one(kpi_doc)
    return format_response(True, "KPI added", {'kpiId': kpi_id}, 201)

@kpi_bp.route('/updateKPi', methods=['POST'])
def updateKpi():
    data = request.get_json() or {}
    kpi_id = data.get('kpiId')
    if not kpi_id:
        return format_response(False, "Missing KPI ID", None, 400)

    # Prepare update fields
    updates = {}
    if 'projectName' in data:
        updates['project_name'] = data['projectName']
    remark = data.get('Remark/comment') or data.get('Remark') or data.get('comment')
    if remark is not None:
        updates['remark'] = remark

    if not updates:
        return format_response(False, "No fields to update", None, 400)

    result = db.kpi.update_one({'kpiId': kpi_id}, {'$set': updates})
    if result.matched_count == 0:
        return format_response(False, "KPI not found", None, 404)

    return format_response(True, "KPI updated", None, 200)

@kpi_bp.route('/getByKpiId/<kpi_id>', methods=['GET'])
def getByKpiId(kpi_id):
    kpi = db.kpi.find_one({'kpiId': kpi_id})
    if not kpi:
        return format_response(False, "KPI not found", None, 404)

    data = {
        'kpiId': kpi.get('kpiId'),
        'employeeId': kpi.get('employeeId'),
        'employeeName': kpi.get('employeeName'),
        'projectName': kpi.get('project_name'),
        'duedate': kpi.get('due_date').strftime('%Y-%m-%d'),
        'submittedDate': kpi.get('submitted_date').strftime('%Y-%m-%d'),
        'Remark/comment': kpi.get('remark'),
        'points': kpi.get('points')
    }
    return format_response(True, "KPI retrieved", data, 200)

@kpi_bp.route('/getAll', methods=['POST'])
def getAll():
    data = request.get_json() or {}
    # Pagination parameters
    try:
        page = int(data.get('page', 1))
        page_size = int(data.get('pageSize', 10))
    except (TypeError, ValueError):
        return format_response(False, "Invalid pagination parameters", None, 400)

    # Search filter on project name
    search = data.get('search', '').strip()
    query = {}
    if search:
        query['project_name'] = {'$regex': search, '$options': 'i'}

    # Total count
    total = db.kpi.count_documents(query)

    # Retrieve paginated results
    skip = (page - 1) * page_size
    cursor = db.kpi.find(query).skip(skip).limit(page_size)

    kpis = []
    for kpi in cursor:
        kpis.append({
            'kpiId': kpi.get('kpiId'),
            'employeeId': kpi.get('employeeId'),
            'employeeName': kpi.get('employeeName'),
            'projectName': kpi.get('project_name'),
            'duedate': kpi.get('due_date').strftime('%Y-%m-%d'),
            'submittedDate': kpi.get('submitted_date').strftime('%Y-%m-%d'),
            'Remark/comment': kpi.get('remark'),
            'points': kpi.get('points')
        })

    response_data = {
        'page': page,
        'pageSize': page_size,
        'total': total,
        'kpis': kpis
    }
    return format_response(True, "KPIs retrieved", response_data, 200)

# Register this blueprint in your app.py:
# from kpi import kpi_bp
# app.register_blueprint(kpi_bp)
