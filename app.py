from flask import Flask, render_template, request, redirect, url_for, flash, send_file, after_this_request, Response
from models import db, BusinessUnit, Customer, Sale, Payment, Expense
from datetime import datetime, timedelta
import os
import sqlite3
import tempfile
import io
import csv
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///farm.db'
app.config['SECRET_KEY'] = 'super-secret-key-change-in-production'
db.init_app(app)

# ==========================================
# V1.3.1: BACKUP & RESTORE ENGINE
# ==========================================
def get_raw_connection():
    """Extracts the underlying Python DBAPI sqlite3 connection from SQLAlchemy."""
    raw_conn = db.engine.raw_connection()
    conn = raw_conn.driver_connection if hasattr(raw_conn, 'driver_connection') else raw_conn.connection
    return conn, raw_conn

def create_backup_to_file(target_path):
    """Safely streams the live database to a target file using SQLite's backup API."""
    source_conn, raw_conn_proxy = get_raw_connection()
    try:
        target_conn = sqlite3.connect(target_path)
        with target_conn:
            source_conn.backup(target_conn)
        target_conn.close()
    finally:
        raw_conn_proxy.close()

def restore_backup_from_file(source_path):
    """Replaces the live database with a backup file safely."""
    db.session.remove()
    db.engine.dispose()
    
    target_conn, raw_conn_proxy = get_raw_connection()
    try:
        source_conn = sqlite3.connect(source_path)
        with target_conn:
            source_conn.backup(target_conn)
        source_conn.close()
    finally:
        raw_conn_proxy.close()

def validate_backup(db_path):
    """Validates that a file is a healthy SQLite database matching our schema."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        if not result or result[0].lower() != "ok":
            return False, "Database integrity check failed. File may be corrupted."
        
        required_tables = {'business_unit', 'customer', 'sale', 'payment', 'expense', 'expense_allocations'}
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0].lower() for row in cursor.fetchall()}
        missing = required_tables - tables
        if missing:
            return False, f"Missing required tables: {', '.join(missing)}. Is this an old or incorrect database?"
            
        return True, "Valid"
    except Exception as e:
        return False, f"Not a valid SQLite database file. Error: {str(e)}"
    finally:
        if conn:
            conn.close()

@app.route('/backup/download', methods=['POST'])
def download_backup():
    fd, temp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    try:
        create_backup_to_file(temp_path)
        
        @after_this_request
        def remove_file(response):
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return response
            
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"refactored_potato_backup_{timestamp}.db"
        return send_file(temp_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        flash(f"Failed to create backup: {str(e)}", "danger")
        return redirect(url_for('settings'))

@app.route('/backup/restore', methods=['POST'])
def restore_backup():
    if 'backup_file' not in request.files:
        flash('No file uploaded.', 'danger')
        return redirect(url_for('settings'))
        
    file = request.files['backup_file']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('settings'))
        
    fd, temp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    file.save(temp_path)
    
    is_valid, msg = validate_backup(temp_path)
    if not is_valid:
        os.remove(temp_path)
        flash(f'Restore aborted. {msg}', 'danger')
        return redirect(url_for('settings'))
        
    safety_filename = f"farm_safety_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    safety_path = os.path.join(app.root_path, safety_filename)
    try:
        create_backup_to_file(safety_path)
    except Exception as e:
        os.remove(temp_path)
        flash(f'Failed to create local safety backup. Restore aborted to protect data. Error: {str(e)}', 'danger')
        return redirect(url_for('settings'))
        
    try:
        restore_backup_from_file(temp_path)
        flash('Database restored successfully! All records have been updated.', 'success')
    except Exception as e:
        try:
            restore_backup_from_file(safety_path)
            flash(f'Restore failed, but your database was safely recovered from the safety backup. Error: {str(e)}', 'warning')
        except Exception as recovery_error:
            flash(f'CRITICAL: Restore AND recovery failed! A safety backup file exists at: {safety_path}', 'danger')
    finally:
        os.remove(temp_path)
        
    return redirect(url_for('settings'))

# ==========================================
# UTILITY: DATE FILTERING
# ==========================================
def parse_date_filter(request):
    filter_type = request.args.get('date_filter', 'this_month')
    start_date = None
    end_date = None
    today = datetime.utcnow().date()
    
    if filter_type == 'today':
        start_date = today
        end_date = today
    elif filter_type == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif filter_type == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif filter_type == 'last_month':
        first_day_this_month = today.replace(day=1)
        end_date = first_day_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    elif filter_type == 'this_year':
        start_date = today.replace(month=1, day=1)
        end_date = today
    elif filter_type == 'custom':
        try:
            start_date = datetime.strptime(request.args.get('start_date'), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.args.get('end_date'), '%Y-%m-%d').date()
        except:
            pass
    return filter_type, start_date, end_date

def apply_date_filter(query, model, start_date, end_date):
    if start_date:
        query = query.filter(model.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(model.date <= datetime.combine(end_date, datetime.max.time()))
    return query

# ==========================================
# HELPER: ALL-TIME BALANCES
# ==========================================
def get_customer_balance(customer_id):
    sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(customer_id=customer_id, is_voided=False).scalar() or 0
    payments = db.session.query(db.func.sum(Payment.amount)).filter_by(customer_id=customer_id, is_voided=False).scalar() or 0
    return sales - payments

def get_total_outstanding_credit():
    total_sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(is_voided=False).scalar() or 0
    total_payments = db.session.query(db.func.sum(Payment.amount)).filter_by(is_voided=False).scalar() or 0
    return total_sales - total_payments

# ==========================================
# V1.3.2: EXPORT ENGINE & SANITIZATION
# ==========================================
def sanitize_for_spreadsheet(value):
    """Prevents CSV and Excel formula injection (starting with =, +, -, @, tab, CR)."""
    if value is None:
        return ""
    str_val = str(value)
    if str_val and str_val[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{str_val}"
    return str_val

def get_export_queries(start_date, end_date, unit_id_filter=None):
    """Fetches core datasets respecting date filters and unit filters."""
    sales_q = apply_date_filter(Sale.query, Sale, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query, Expense, start_date, end_date)
    payments_q = apply_date_filter(Payment.query, Payment, start_date, end_date)

    if unit_id_filter:
        sales_q = sales_q.filter_by(unit_id=unit_id_filter)
        expenses_q = expenses_q.filter(Expense.allocated_units.any(id=unit_id_filter))
        # Note: Payments belong to customers and are not tied to business units

    return sales_q, expenses_q, payments_q

@app.route('/export')
def export_hub():
    filter_type, start_date, end_date = parse_date_filter(request)
    unit_id_filter = request.args.get('unit_id')
    units = BusinessUnit.query.filter_by(is_active=True).all()
    
    return render_template('export.html',
                           filter_type=filter_type,
                           start_date=start_date,
                           end_date=end_date,
                           unit_id_filter=unit_id_filter,
                           units=units)

@app.route('/export/csv/<dataset>')
def export_csv(dataset):
    filter_type, start_date, end_date = parse_date_filter(request)
    unit_id_filter = request.args.get('unit_id')
    sales_q, expenses_q, payments_q = get_export_queries(start_date, end_date, unit_id_filter)

    output = io.StringIO()
    writer = csv.writer(output)
    timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H%M')

    if dataset == 'sales':
        writer.writerow(['Sale ID', 'Date', 'Customer', 'Product / Business Unit', 'Quantity', 'Unit Price ($)', 'Total Amount ($)', 'Status', 'Notes'])
        for s in sales_q.order_by(Sale.date.desc()).all():
            writer.writerow([
                s.id,
                s.date.strftime('%Y-%m-%d %H:%M'),
                sanitize_for_spreadsheet(s.customer.name if s.customer else 'Unknown'),
                sanitize_for_spreadsheet(s.business_unit.name if s.business_unit else 'Unknown'),
                f"{s.quantity:.2f}",
                f"{s.unit_price:.2f}",
                f"{s.total_amount:.2f}",
                'VOIDED' if s.is_voided else 'Active',
                sanitize_for_spreadsheet(s.notes or '')
            ])
        filename = f"sales_export_{timestamp}.csv"

    elif dataset == 'expenses':
        writer.writerow(['Expense ID', 'Date', 'Category', 'Description', 'Scope', 'Allocated Business Units', 'Amount ($)', 'Status'])
        for e in expenses_q.order_by(Expense.date.desc()).all():
            if e.scope == 'specific':
                units_str = e.allocated_units[0].name if e.allocated_units else 'Unassigned'
            elif e.scope == 'shared':
                units_str = ", ".join([u.name for u in e.allocated_units])
            elif e.scope == 'farm':
                units_str = "Entire Farm"
            else:
                units_str = "Unallocated"

            writer.writerow([
                e.id,
                e.date.strftime('%Y-%m-%d %H:%M'),
                sanitize_for_spreadsheet(e.category),
                sanitize_for_spreadsheet(e.description or ''),
                e.scope.capitalize(),
                sanitize_for_spreadsheet(units_str),
                f"{e.amount:.2f}",
                'VOIDED' if e.is_voided else 'Active'
            ])
        filename = f"expenses_export_{timestamp}.csv"

    elif dataset == 'payments':
        writer.writerow(['Payment ID', 'Date', 'Customer', 'Amount ($)', 'Status', 'Notes'])
        for p in payments_q.order_by(Payment.date.desc()).all():
            writer.writerow([
                p.id,
                p.date.strftime('%Y-%m-%d %H:%M'),
                sanitize_for_spreadsheet(p.customer.name if p.customer else 'Unknown'),
                f"{p.amount:.2f}",
                'VOIDED' if p.is_voided else 'Active',
                sanitize_for_spreadsheet(p.notes or '')
            ])
        filename = f"payments_export_{timestamp}.csv"

    elif dataset == 'customer_balances':
        # Customer balances are strictly ALL-TIME
        writer.writerow(['Customer ID', 'Customer Name', 'Phone', 'Location', 'Status', 'All-Time Sales ($)', 'All-Time Payments ($)', 'Current Outstanding Balance ($)'])
        customers = Customer.query.order_by(Customer.name).all()
        for c in customers:
            all_sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(customer_id=c.id, is_voided=False).scalar() or 0.0
            all_pmts = db.session.query(db.func.sum(Payment.amount)).filter_by(customer_id=c.id, is_voided=False).scalar() or 0.0
            balance = all_sales - all_pmts
            writer.writerow([
                c.id,
                sanitize_for_spreadsheet(c.name),
                sanitize_for_spreadsheet(c.phone or ''),
                sanitize_for_spreadsheet(c.location or ''),
                'Active' if c.is_active else 'Archived',
                f"{all_sales:.2f}",
                f"{all_pmts:.2f}",
                f"{balance:.2f}"
            ])
        filename = f"customer_balances_all_time_{timestamp}.csv"

    elif dataset == 'business_summaries':
        writer.writerow(['Business Unit', 'Sales Count', 'Revenue ($)', 'Direct Expenses ($)', 'Estimated Direct Profit ($)', 'Direct Margin (%)', 'Shared Expenses Memo ($)'])
        active_units = BusinessUnit.query.filter_by(is_active=True).all()
        for unit in active_units:
            u_sales_q = apply_date_filter(Sale.query.filter_by(unit_id=unit.id, is_voided=False), Sale, start_date, end_date)
            u_direct_exp_q = apply_date_filter(Expense.query.filter(Expense.allocated_units.any(id=unit.id), Expense.scope == 'specific', Expense.is_voided == False), Expense, start_date, end_date)
            u_shared_exp_q = apply_date_filter(Expense.query.filter(Expense.allocated_units.any(id=unit.id), Expense.scope == 'shared', Expense.is_voided == False), Expense, start_date, end_date)

            rev = u_sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0.0
            direct_costs = u_direct_exp_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0.0
            shared_memo = u_shared_exp_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0.0
            profit = rev - direct_costs
            margin_str = f"{(profit / rev * 100):.1f}" if rev > 0 else 'N/A'
            count = u_sales_q.count()

            writer.writerow([
                sanitize_for_spreadsheet(unit.name),
                count,
                f"{rev:.2f}",
                f"{direct_costs:.2f}",
                f"{profit:.2f}",
                margin_str,
                f"{shared_memo:.2f}"
            ])
        filename = f"business_unit_summary_{timestamp}.csv"

    else:
        flash("Invalid export dataset selected.", "danger")
        return redirect(url_for('export_hub'))

   # Deliver with UTF-8 BOM so spreadsheet engines recognize accents and currency symbols
    bytes_data = output.getvalue().encode('utf-8-sig')
    return Response(
        bytes_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.route('/export/excel')
def export_excel():
    filter_type, start_date, end_date = parse_date_filter(request)
    unit_id_filter = request.args.get('unit_id')
    sales_q, expenses_q, payments_q = get_export_queries(start_date, end_date, unit_id_filter)

    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2C523D", end_color="2C523D", fill_type="solid")
    meta_font = Font(name="Calibri", size=10, italic=True, color="555555")
    thin_border = Border(
        left=Side(style='thin', color='E0E0E0'),
        right=Side(style='thin', color='E0E0E0'),
        top=Side(style='thin', color='E0E0E0'),
        bottom=Side(style='thin', color='E0E0E0')
    )

    def style_sheet(ws, title, meta_text, headers, rows):
        ws.title = title
        ws.append([f"Refactored Potato — {title}"])
        ws.cell(1, 1).font = Font(name="Calibri", size=14, bold=True, color="1E392A")
        ws.append([meta_text])
        ws.cell(2, 1).font = meta_font
        ws.append([]) # Blank spacer

        ws.append(headers)
        header_row_idx = 4
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_data in rows:
            ws.append(r_data)
            current_row = ws.max_row
            for c_idx in range(1, len(r_data) + 1):
                c = ws.cell(row=current_row, column=c_idx)
                c.border = thin_border
                # Right align numbers
                if isinstance(r_data[c_idx - 1], (int, float)):
                    c.number_format = '#,##0.00'
                    c.alignment = Alignment(horizontal="right")

        ws.freeze_panes = f"A{header_row_idx + 1}"

        # Adjust column widths dynamically
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or '')
                if cell.row < 3:
                    continue # Do not size by metadata headers
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # 1. Sales Sheet
    sales_headers = ['Sale ID', 'Date', 'Customer', 'Product / Business Unit', 'Quantity', 'Unit Price ($)', 'Total Amount ($)', 'Status', 'Notes']
    sales_rows = []
    for s in sales_q.order_by(Sale.date.desc()).all():
        sales_rows.append([
            s.id,
            s.date.strftime('%Y-%m-%d %H:%M'),
            sanitize_for_spreadsheet(s.customer.name if s.customer else 'Unknown'),
            sanitize_for_spreadsheet(s.business_unit.name if s.business_unit else 'Unknown'),
            s.quantity,
            s.unit_price,
            s.total_amount,
            'VOIDED' if s.is_voided else 'Active',
            sanitize_for_spreadsheet(s.notes or '')
        ])
    date_label = f"Period: {filter_type.replace('_', ' ').capitalize()} ({start_date or 'Beginning'} to {end_date or 'Present'})"
    style_sheet(wb.create_sheet(), "Sales", f"{date_label} | Note: Voided sales remain visible for auditability but are excluded from summaries.", sales_headers, sales_rows)

    # 2. Expenses Sheet
    exp_headers = ['Expense ID', 'Date', 'Category', 'Description', 'Scope', 'Allocated Business Units', 'Amount ($)', 'Status']
    exp_rows = []
    for e in expenses_q.order_by(Expense.date.desc()).all():
        if e.scope == 'specific':
            units_str = e.allocated_units[0].name if e.allocated_units else 'Unassigned'
        elif e.scope == 'shared':
            units_str = ", ".join([u.name for u in e.allocated_units])
        elif e.scope == 'farm':
            units_str = "Entire Farm"
        else:
            units_str = "Unallocated"
        exp_rows.append([
            e.id,
            e.date.strftime('%Y-%m-%d %H:%M'),
            sanitize_for_spreadsheet(e.category),
            sanitize_for_spreadsheet(e.description or ''),
            e.scope.capitalize(),
            sanitize_for_spreadsheet(units_str),
            e.amount,
            'VOIDED' if e.is_voided else 'Active'
        ])
    style_sheet(wb.create_sheet(), "Expenses", f"{date_label} | Note: Voided expenses are excluded from summaries.", exp_headers, exp_rows)

    # 3. Payments Sheet
    pmt_headers = ['Payment ID', 'Date', 'Customer', 'Amount ($)', 'Status', 'Notes']
    pmt_rows = []
    for p in payments_q.order_by(Payment.date.desc()).all():
        pmt_rows.append([
            p.id,
            p.date.strftime('%Y-%m-%d %H:%M'),
            sanitize_for_spreadsheet(p.customer.name if p.customer else 'Unknown'),
            p.amount,
            'VOIDED' if p.is_voided else 'Active',
            sanitize_for_spreadsheet(p.notes or '')
        ])
    style_sheet(wb.create_sheet(), "Payments", f"{date_label} | Note: Customer payments represent cash received, not additional revenue.", pmt_headers, pmt_rows)

    # 4. Customer Balances Sheet (ALL-TIME)
    cust_headers = ['Customer ID', 'Customer Name', 'Phone', 'Location', 'Status', 'All-Time Sales ($)', 'All-Time Payments ($)', 'Current Balance ($)']
    cust_rows = []
    customers = Customer.query.order_by(Customer.name).all()
    for c in customers:
        all_sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(customer_id=c.id, is_voided=False).scalar() or 0.0
        all_pmts = db.session.query(db.func.sum(Payment.amount)).filter_by(customer_id=c.id, is_voided=False).scalar() or 0.0
        balance = all_sales - all_pmts
        cust_rows.append([
            c.id,
            sanitize_for_spreadsheet(c.name),
            sanitize_for_spreadsheet(c.phone or ''),
            sanitize_for_spreadsheet(c.location or ''),
            'Active' if c.is_active else 'Archived',
            all_sales,
            all_pmts,
            balance
        ])
    style_sheet(wb.create_sheet(), "Customer Balances", "All-Time Balances | Outstanding balances reflect complete customer ledger history regardless of date filter.", cust_headers, cust_rows)

    # 5. Business Unit Summary Sheet
    bu_headers = ['Business Unit', 'Sales Count', 'Revenue ($)', 'Direct Expenses ($)', 'Estimated Direct Profit ($)', 'Direct Margin (%)', 'Shared Expenses Memo ($)']
    bu_rows = []
    active_units = BusinessUnit.query.filter_by(is_active=True).all()
    for unit in active_units:
        u_sales_q = apply_date_filter(Sale.query.filter_by(unit_id=unit.id, is_voided=False), Sale, start_date, end_date)
        u_direct_exp_q = apply_date_filter(Expense.query.filter(Expense.allocated_units.any(id=unit.id), Expense.scope == 'specific', Expense.is_voided == False), Expense, start_date, end_date)
        u_shared_exp_q = apply_date_filter(Expense.query.filter(Expense.allocated_units.any(id=unit.id), Expense.scope == 'shared', Expense.is_voided == False), Expense, start_date, end_date)

        rev = u_sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0.0
        direct_costs = u_direct_exp_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0.0
        shared_memo = u_shared_exp_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0.0
        profit = rev - direct_costs
        margin_str = f"{(profit / rev * 100):.1f}%" if rev > 0 else 'N/A'
        count = u_sales_q.count()

        bu_rows.append([
            sanitize_for_spreadsheet(unit.name),
            count,
            rev,
            direct_costs,
            profit,
            margin_str,
            shared_memo
        ])
    style_sheet(wb.create_sheet(), "Business Unit Summary", f"{date_label} | Direct profit excludes shared, farm-wide and unallocated costs to prevent double-counting.", bu_headers, bu_rows)

    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)

    timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H%M')
    return send_file(
        excel_buffer,
        as_attachment=True,
        download_name=f"refactored_potato_financials_{timestamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==========================================
# DASHBOARD
# ==========================================
@app.route('/')
def dashboard():
    filter_type, start_date, end_date = parse_date_filter(request)
    
    sales_q = apply_date_filter(Sale.query.filter_by(is_voided=False), Sale, start_date, end_date)
    payments_q = apply_date_filter(Payment.query.filter_by(is_voided=False), Payment, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query.filter_by(is_voided=False), Expense, start_date, end_date)
    
    period_revenue = sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0
    period_cash = payments_q.with_entities(db.func.sum(Payment.amount)).scalar() or 0
    period_expenses = expenses_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0
    
    period_profit = period_revenue - period_expenses
    period_margin = (period_profit / period_revenue * 100) if period_revenue > 0 else 'N/A'
    outstanding_debt = get_total_outstanding_credit()

    sales_data = sales_q.all()
    expenses_data = expenses_q.all()
    
    trends = {}
    for s in sales_data:
        d = s.date.strftime('%Y-%m-%d')
        if d not in trends: trends[d] = {'rev': 0, 'exp': 0}
        trends[d]['rev'] += s.total_amount
        
    for e in expenses_data:
        d = e.date.strftime('%Y-%m-%d')
        if d not in trends: trends[d] = {'rev': 0, 'exp': 0}
        trends[d]['exp'] += e.amount
        
    chart_labels = sorted(trends.keys())
    chart_rev = [trends[d]['rev'] for d in chart_labels]
    chart_exp = [trends[d]['exp'] for d in chart_labels]
    chart_profit = [trends[d]['rev'] - trends[d]['exp'] for d in chart_labels]

    return render_template('dashboard.html', 
                           filter_type=filter_type, start_date=start_date, end_date=end_date,
                           revenue=period_revenue, cash=period_cash, debt=outstanding_debt, 
                           expenses=period_expenses, profit=period_profit, margin=period_margin,
                           chart_labels=chart_labels, chart_rev=chart_rev, chart_exp=chart_exp, chart_profit=chart_profit)

# ==========================================
# ANALYTICS & REPORTING
# ==========================================
@app.route('/analytics')
@app.route('/profitability')
def analytics():
    filter_type, start_date, end_date = parse_date_filter(request)
    
    sales_q = apply_date_filter(Sale.query.filter_by(is_voided=False), Sale, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query.filter_by(is_voided=False), Expense, start_date, end_date)
    
    farm_revenue = sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0
    farm_expenses = expenses_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0
    farm_profit = farm_revenue - farm_expenses
    farm_margin = (farm_profit / farm_revenue * 100) if farm_revenue > 0 else 'N/A'
    
    farm_direct = expenses_q.filter(Expense.scope == 'specific').with_entities(db.func.sum(Expense.amount)).scalar() or 0
    farm_shared = expenses_q.filter(Expense.scope == 'shared').with_entities(db.func.sum(Expense.amount)).scalar() or 0
    farm_wide = expenses_q.filter(Expense.scope == 'farm').with_entities(db.func.sum(Expense.amount)).scalar() or 0
    farm_unallocated = expenses_q.filter(Expense.scope == 'unallocated').with_entities(db.func.sum(Expense.amount)).scalar() or 0
    
    expenses_data = expenses_q.all()
    categories_dict = {}
    for e in expenses_data:
        categories_dict[e.category] = categories_dict.get(e.category, 0) + e.amount
    expenses_by_category = sorted(categories_dict.items(), key=lambda x: x[1], reverse=True)

    units = BusinessUnit.query.filter_by(is_active=True).all()
    performance = []
    
    for unit in units:
        unit_sales_q = sales_q.filter_by(unit_id=unit.id)
        direct_costs = expenses_q.filter(Expense.allocated_units.any(id=unit.id), Expense.scope == 'specific').with_entities(db.func.sum(Expense.amount)).scalar() or 0
        shared_costs_memo = expenses_q.filter(Expense.allocated_units.any(id=unit.id), Expense.scope == 'shared').with_entities(db.func.sum(Expense.amount)).scalar() or 0
        
        rev = unit_sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0
        count = unit_sales_q.count()
        profit = rev - direct_costs
        margin = (profit / rev * 100) if rev > 0 else 'N/A'
        
        performance.append({
            'name': unit.name, 'revenue': rev, 'direct_costs': direct_costs,
            'shared_costs_memo': shared_costs_memo, 'profit': profit,
            'margin': margin, 'count': count
        })
        
    customers = Customer.query.filter_by(is_active=True).all()
    customer_analytics = []
    for c in customers:
        balance = get_customer_balance(c.id)
        if balance > 0:
            recent_sale = Sale.query.filter_by(customer_id=c.id, is_voided=False).order_by(Sale.date.desc()).first()
            recent_payment = Payment.query.filter_by(customer_id=c.id, is_voided=False).order_by(Payment.date.desc()).first()
            customer_analytics.append({
                'name': c.name, 'balance': balance,
                'recent_sale': recent_sale.date if recent_sale else None,
                'recent_payment': recent_payment.date if recent_payment else None
            })
    customer_analytics.sort(key=lambda x: x['balance'], reverse=True)
        
    return render_template('analytics.html', 
                           filter_type=filter_type, start_date=start_date, end_date=end_date,
                           performance=performance, farm_revenue=farm_revenue, farm_expenses=farm_expenses,
                           farm_profit=farm_profit, farm_margin=farm_margin, farm_direct=farm_direct, 
                           farm_shared=farm_shared, farm_wide=farm_wide, farm_unallocated=farm_unallocated,
                           expenses_by_category=expenses_by_category, customer_analytics=customer_analytics)

# ==========================================
# LEDGER
# ==========================================
@app.route('/ledger')
def ledger():
    filter_type, start_date, end_date = parse_date_filter(request)
    unit_id_filter = request.args.get('unit_id')
    customer_id_filter = request.args.get('customer_id')
    type_filter = request.args.get('type')

    sales_q = apply_date_filter(Sale.query, Sale, start_date, end_date)
    payments_q = apply_date_filter(Payment.query, Payment, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query, Expense, start_date, end_date)
    
    if unit_id_filter:
        sales_q = sales_q.filter_by(unit_id=unit_id_filter)
        expenses_q = expenses_q.filter(Expense.allocated_units.any(id=unit_id_filter))
        payments_q = payments_q.filter(False)
        
    if customer_id_filter:
        sales_q = sales_q.filter_by(customer_id=customer_id_filter)
        payments_q = payments_q.filter_by(customer_id=customer_id_filter)
        expenses_q = expenses_q.filter(False)

    transactions = []
    
    if not type_filter or type_filter == 'Sale':
        for s in sales_q.all():
            transactions.append({
                'id': s.id, 'type': 'Sale', 'date': s.date, 
                'desc': f"Customer: {s.customer.name}", 
                'business': s.business_unit.name, 
                'amount': s.total_amount, 'is_voided': s.is_voided
            })
            
    if not type_filter or type_filter == 'Payment':
        for p in payments_q.all():
            transactions.append({
                'id': p.id, 'type': 'Payment', 'date': p.date, 
                'desc': f"From: {p.customer.name}", 
                'business': '—', 
                'amount': p.amount, 'is_voided': p.is_voided
            })
            
    if not type_filter or type_filter == 'Expense':
        for e in expenses_q.all():
            if e.scope == 'specific': biz_label = e.allocated_units[0].name if e.allocated_units else 'Unknown'
            elif e.scope == 'shared': biz_label = f"Shared ({len(e.allocated_units)} units)"
            elif e.scope == 'farm': biz_label = "Entire Farm"
            else: biz_label = "Unallocated"
                
            transactions.append({
                'id': e.id, 'type': 'Expense', 'date': e.date, 
                'desc': e.description, 'business': biz_label, 
                'amount': e.amount, 'is_voided': e.is_voided
            })
            
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    units = BusinessUnit.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).all()
    
    return render_template('ledger.html', 
                           transactions=transactions, units=units, customers=customers,
                           filter_type=filter_type, start_date=start_date, end_date=end_date,
                           unit_id_filter=unit_id_filter, customer_id_filter=customer_id_filter, type_filter=type_filter)

# ==========================================
# DATA ENTRY ROUTES
# ==========================================
@app.route('/sales/new', methods=['GET', 'POST'])
def record_sale():
    if request.method == 'POST':
        total = float(request.form['quantity']) * float(request.form['unit_price'])
        new_sale = Sale(
            customer_id=request.form['customer_id'],
            unit_id=request.form['unit_id'],
            quantity=float(request.form['quantity']),
            unit_price=float(request.form['unit_price']),
            total_amount=total,
            notes=request.form['notes']
        )
        db.session.add(new_sale)
        if float(request.form['amount_paid']) > 0:
            payment = Payment(
                customer_id=request.form['customer_id'],
                amount=float(request.form['amount_paid']),
                notes="Paid at time of sale"
            )
            db.session.add(payment)
        db.session.commit()
        flash('Sale recorded successfully.', 'success')
        return redirect(url_for('dashboard'))
    customers = Customer.query.filter_by(is_active=True).all()
    units = BusinessUnit.query.filter_by(is_active=True).all()
    return render_template('record_sale.html', customers=customers, units=units)

@app.route('/payments/new', methods=['GET', 'POST'])
def record_payment():
    if request.method == 'POST':
        payment = Payment(
            customer_id=request.form['customer_id'],
            amount=float(request.form['amount']),
            notes=request.form['notes']
        )
        db.session.add(payment)
        db.session.commit()
        flash('Payment recorded successfully.', 'success')
        return redirect(url_for('dashboard'))
    customers = Customer.query.filter_by(is_active=True).all()
    for c in customers: c.balance = get_customer_balance(c.id)
    return render_template('record_payment.html', customers=customers)

@app.route('/expenses/new', methods=['GET', 'POST'])
def record_expense():
    if request.method == 'POST':
        scope = request.form.get('scope', 'unallocated')
        expense = Expense(
            amount=float(request.form['amount']),
            category=request.form['category'],
            description=request.form['description'],
            scope=scope
        )
        
        if scope == 'specific':
            unit = BusinessUnit.query.get(request.form.get('single_unit_id'))
            if unit: expense.allocated_units.append(unit)
        elif scope == 'shared':
            shared_ids = request.form.getlist('shared_unit_ids')
            for uid in shared_ids:
                unit = BusinessUnit.query.get(uid)
                if unit: expense.allocated_units.append(unit)
                
        db.session.add(expense)
        db.session.commit()
        flash('Expense recorded successfully.', 'success')
        return redirect(url_for('dashboard'))
        
    units = BusinessUnit.query.filter_by(is_active=True).all()
    categories = ["Fertilizer", "Seeds", "Feed", "Fuel", "Labour", "Transport", "Packaging", "Electricity", "Water", "Repairs", "Maintenance", "Small Purchases", "Other"]
    return render_template('record_expense.html', units=units, categories=categories)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_customer':
            new_cust = Customer(name=request.form['name'], phone=request.form.get('phone'), location=request.form.get('location'), notes=request.form.get('notes'))
            db.session.add(new_cust)
            flash('Customer added.', 'success')
        elif action == 'add_unit':
            new_unit = BusinessUnit(name=request.form['name'])
            db.session.add(new_unit)
            flash('Business Unit added.', 'success')
        db.session.commit()
        return redirect(url_for('settings'))
    customers = Customer.query.all()
    for c in customers: c.balance = get_customer_balance(c.id)
    units = BusinessUnit.query.all()
    return render_template('settings.html', customers=customers, units=units)

@app.route('/settings/edit_customer/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.phone = request.form.get('phone')
        customer.location = request.form.get('location')
        customer.notes = request.form.get('notes')
        db.session.commit()
        flash('Customer updated.', 'success')
        return redirect(url_for('settings'))
    return render_template('edit_customer.html', customer=customer)

@app.route('/settings/toggle/<type>/<int:id>')
def toggle_active(type, id):
    obj = Customer.query.get_or_404(id) if type == 'customer' else BusinessUnit.query.get_or_404(id)
    obj.is_active = not obj.is_active
    db.session.commit()
    flash('Status updated.', 'info')
    return redirect(url_for('settings'))

@app.route('/ledger/void/<type>/<int:id>')
def void_transaction(type, id):
    if type == 'Sale': obj = Sale.query.get_or_404(id)
    elif type == 'Payment': obj = Payment.query.get_or_404(id)
    elif type == 'Expense': obj = Expense.query.get_or_404(id)
    obj.is_voided = True
    db.session.commit()
    flash('Transaction voided.', 'warning')
    return redirect(url_for('ledger'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)