from flask import Flask
from employee import employee_bp
from salaryslip import salary_bp

app = Flask(__name__)
app.register_blueprint(employee_bp)
app.register_blueprint(salary_bp)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
