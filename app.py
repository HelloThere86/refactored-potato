from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, BusinessUnit, Customer, Sale, Payment, Expense
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///farm.db'
app.config['SECRET_KEY'] = 'super-secret-key-change-in-production'
db.init_app(app)

# ==========================================
# UTILITY: DATE FILTERING
# ==========================================
def parse_date_filter(request):
    """Parses date filters from the URL parameters."""
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
            pass # Fallback to all time if custom dates are missing/invalid
            
    return filter_type, start_date, end_date

def apply_date_filter(query, model, start_date, end_date):
    """Applies start and end dates to a SQLAlchemy query."""
    if start_date:
        query = query.filter(model.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(model.date <= datetime.combine(end_date, datetime.max.time()))
    return query

# ==========================================
# HELPER: ALL-TIME BALANCES
# ==========================================
def get_customer_balance(customer_id):
    """All-time outstanding balance calculation."""
    sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(customer_id=customer_id, is_voided=False).scalar() or 0
    payments = db.session.query(db.func.sum(Payment.amount)).filter_by(customer_id=customer_id, is_voided=False).scalar() or 0
    return sales - payments

def get_total_outstanding_credit():
    """Calculates farm-wide all-time outstanding debt."""
    total_sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(is_voided=False).scalar() or 0
    total_payments = db.session.query(db.func.sum(Payment.amount)).filter_by(is_voided=False).scalar() or 0
    return total_sales - total_payments

# ==========================================
# DASHBOARD
# ==========================================
@app.route('/')
def dashboard():
    filter_type, start_date, end_date = parse_date_filter(request)
    
    # 1. Base Queries
    sales_q = apply_date_filter(Sale.query.filter_by(is_voided=False), Sale, start_date, end_date)
    payments_q = apply_date_filter(Payment.query.filter_by(is_voided=False), Payment, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query.filter_by(is_voided=False), Expense, start_date, end_date)
    
    # 2. Period Summary Math
    period_revenue = sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0
    period_cash = payments_q.with_entities(db.func.sum(Payment.amount)).scalar() or 0
    period_expenses = expenses_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0
    
    period_profit = period_revenue - period_expenses
    period_margin = (period_profit / period_revenue * 100) if period_revenue > 0 else 'N/A'
    
    # All-time Debt
    outstanding_debt = get_total_outstanding_credit()

    # 3. Chart Data Generation
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
@app.route('/profitability') # Catch legacy link
def analytics():
    filter_type, start_date, end_date = parse_date_filter(request)
    
    # --- A. ENTIRE FARM SUMMARY ---
    sales_q = apply_date_filter(Sale.query.filter_by(is_voided=False), Sale, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query.filter_by(is_voided=False), Expense, start_date, end_date)
    
    farm_revenue = sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0
    farm_expenses = expenses_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0
    farm_profit = farm_revenue - farm_expenses
    farm_margin = (farm_profit / farm_revenue * 100) if farm_revenue > 0 else 'N/A'
    
    # --- B. EXPENSE ANALYSIS ---
    farm_shared_expenses = expenses_q.filter(Expense.unit_id == None).with_entities(db.func.sum(Expense.amount)).scalar() or 0
    
    # Group expenses by category safely
    expenses_data = expenses_q.all()
    categories_dict = {}
    for e in expenses_data:
        categories_dict[e.category] = categories_dict.get(e.category, 0) + e.amount
    expenses_by_category = sorted(categories_dict.items(), key=lambda x: x[1], reverse=True)

    # --- C. BUSINESS UNIT PERFORMANCE ---
    units = BusinessUnit.query.filter_by(is_active=True).all()
    performance = []
    
    for unit in units:
        unit_sales_q = sales_q.filter_by(unit_id=unit.id)
        unit_exp_q = expenses_q.filter_by(unit_id=unit.id)
        
        rev = unit_sales_q.with_entities(db.func.sum(Sale.total_amount)).scalar() or 0
        costs = unit_exp_q.with_entities(db.func.sum(Expense.amount)).scalar() or 0
        count = unit_sales_q.count()
        
        profit = rev - costs
        margin = (profit / rev * 100) if rev > 0 else 'N/A'
        
        performance.append({
            'name': unit.name,
            'revenue': rev,
            'costs': costs,
            'profit': profit,
            'margin': margin,
            'count': count
        })
        
    # --- D. CREDIT & CUSTOMER ANALYTICS ---
    # Customer balances are fundamentally ALL-TIME, but we show period activity.
    customers = Customer.query.filter_by(is_active=True).all()
    customer_analytics = []
    for c in customers:
        balance = get_customer_balance(c.id)
        if balance > 0: # Only list customers who owe money
            # Fetch their most recent non-voided sale
            recent_sale = Sale.query.filter_by(customer_id=c.id, is_voided=False).order_by(Sale.date.desc()).first()
            recent_payment = Payment.query.filter_by(customer_id=c.id, is_voided=False).order_by(Payment.date.desc()).first()
            
            customer_analytics.append({
                'name': c.name,
                'balance': balance,
                'recent_sale': recent_sale.date if recent_sale else None,
                'recent_payment': recent_payment.date if recent_payment else None
            })
            
    customer_analytics.sort(key=lambda x: x['balance'], reverse=True)
        
    return render_template('analytics.html', 
                           filter_type=filter_type, start_date=start_date, end_date=end_date,
                           performance=performance,
                           farm_revenue=farm_revenue, farm_expenses=farm_expenses,
                           farm_profit=farm_profit, farm_margin=farm_margin,
                           farm_shared=farm_shared_expenses,
                           expenses_by_category=expenses_by_category,
                           customer_analytics=customer_analytics)

# ==========================================
# LEDGER (With V1.1 Filtering)
# ==========================================
@app.route('/ledger')
def ledger():
    filter_type, start_date, end_date = parse_date_filter(request)
    unit_id_filter = request.args.get('unit_id')
    customer_id_filter = request.args.get('customer_id')
    type_filter = request.args.get('type')

    # Base Queries
    sales_q = apply_date_filter(Sale.query, Sale, start_date, end_date)
    payments_q = apply_date_filter(Payment.query, Payment, start_date, end_date)
    expenses_q = apply_date_filter(Expense.query, Expense, start_date, end_date)
    
    # Apply Specific Filters
    if unit_id_filter:
        sales_q = sales_q.filter_by(unit_id=unit_id_filter)
        expenses_q = expenses_q.filter_by(unit_id=unit_id_filter)
        payments_q = payments_q.filter(False) # Payments don't have unit_ids in V1
        
    if customer_id_filter:
        sales_q = sales_q.filter_by(customer_id=customer_id_filter)
        payments_q = payments_q.filter_by(customer_id=customer_id_filter)
        expenses_q = expenses_q.filter(False) # Expenses don't have customers

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
            transactions.append({
                'id': e.id, 'type': 'Expense', 'date': e.date, 
                'desc': e.description, 
                'business': e.business_unit.name if e.business_unit else 'Shared / Farm-Wide', 
                'amount': e.amount, 'is_voided': e.is_voided
            })
            
    # Sort newest first
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    units = BusinessUnit.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).all()
    
    return render_template('ledger.html', 
                           transactions=transactions, units=units, customers=customers,
                           filter_type=filter_type, start_date=start_date, end_date=end_date,
                           unit_id_filter=unit_id_filter, customer_id_filter=customer_id_filter, type_filter=type_filter)

# ==========================================
# EXISTING DATA ENTRY ROUTES (Preserved exactly as V1.0)
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
        unit_id = request.form.get('unit_id')
        expense = Expense(
            amount=float(request.form['amount']),
            category=request.form['category'],
            description=request.form['description'],
            unit_id=unit_id if unit_id != 'shared' else None
        )
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
        flash(f'Customer updated.', 'success')
        return redirect(url_for('settings'))
    return render_template('edit_customer.html', customer=customer)

@app.route('/settings/toggle/<type>/<int:id>')
def toggle_active(type, id):
    obj = Customer.query.get_or_404(id) if type == 'customer' else BusinessUnit.query.get_or_404(id)
    obj.is_active = not obj.is_active
    db.session.commit()
    flash(f'Status updated.', 'info')
    return redirect(url_for('settings'))

@app.route('/ledger/void/<type>/<int:id>')
def void_transaction(type, id):
    if type == 'Sale': obj = Sale.query.get_or_404(id)
    elif type == 'Payment': obj = Payment.query.get_or_404(id)
    elif type == 'Expense': obj = Expense.query.get_or_404(id)
    obj.is_voided = True
    db.session.commit()
    flash(f'Transaction voided.', 'warning')
    return redirect(url_for('ledger'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)