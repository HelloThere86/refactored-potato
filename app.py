from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, BusinessUnit, Customer, Sale, Payment, Expense
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///farm.db'
app.config['SECRET_KEY'] = 'super-secret-key-change-in-production'
db.init_app(app)

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def get_customer_balance(customer_id):
    """Calculates exactly what a customer owes, ignoring voided transactions"""
    sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(customer_id=customer_id, is_voided=False).scalar() or 0
    payments = db.session.query(db.func.sum(Payment.amount)).filter_by(customer_id=customer_id, is_voided=False).scalar() or 0
    return sales - payments

# ==========================================
# CORE DASHBOARD
# ==========================================
@app.route('/')
def dashboard():
    # Calculate Core Dashboard Metrics (must filter out voided items!)
    total_sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(is_voided=False).scalar() or 0
    cash_received = db.session.query(db.func.sum(Payment.amount)).filter_by(is_voided=False).scalar() or 0
    total_expenses = db.session.query(db.func.sum(Expense.amount)).filter_by(is_voided=False).scalar() or 0
    
    outstanding_debt = total_sales - cash_received
    net_cash_flow = cash_received - total_expenses
    estimated_profit = total_sales - total_expenses

    return render_template('dashboard.html', 
                           sales=total_sales, 
                           cash=cash_received, 
                           debt=outstanding_debt, 
                           expenses=total_expenses, 
                           cash_flow=net_cash_flow, 
                           profit=estimated_profit)

# ==========================================
# RECORDING TRANSACTIONS
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
        
        # If paid immediately, create a linked payment record
        if float(request.form['amount_paid']) > 0:
            payment = Payment(
                customer_id=request.form['customer_id'],
                amount=float(request.form['amount_paid']),
                notes="Paid at time of sale"
            )
            db.session.add(payment)
            
        db.session.commit()
        flash('Sale recorded successfully!', 'success')
        return redirect(url_for('dashboard'))
        
    # Only show active customers and products in the dropdowns
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
        flash('Payment recorded successfully!', 'success')
        return redirect(url_for('dashboard'))
        
    customers = Customer.query.filter_by(is_active=True).all()
    # Attach calculated balances for the dropdown
    for c in customers:
        c.balance = get_customer_balance(c.id)
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
        flash('Expense recorded successfully!', 'success')
        return redirect(url_for('dashboard'))
        
    units = BusinessUnit.query.filter_by(is_active=True).all()
    categories = ["Fertilizer", "Seeds", "Feed", "Fuel", "Labour", "Transport", "Other"]
    return render_template('record_expense.html', units=units, categories=categories)

# ==========================================
# REPORTS & PROFITABILITY
# ==========================================
@app.route('/profitability')
def profitability():
    # ==========================================
    # 1. ENTIRE FARM CALCULATIONS
    # ==========================================
    farm_revenue = db.session.query(db.func.sum(Sale.total_amount)).filter_by(is_voided=False).scalar() or 0
    farm_expenses = db.session.query(db.func.sum(Expense.amount)).filter_by(is_voided=False).scalar() or 0
    farm_profit = farm_revenue - farm_expenses
    farm_margin = (farm_profit / farm_revenue * 100) if farm_revenue > 0 else 0
    
    farm_cash_received = db.session.query(db.func.sum(Payment.amount)).filter_by(is_voided=False).scalar() or 0
    farm_outstanding_credit = farm_revenue - farm_cash_received
    
    # Split expenses between Direct (assigned to a business) and Shared (Entire Farm)
    farm_shared_expenses = db.session.query(db.func.sum(Expense.amount)).filter_by(unit_id=None, is_voided=False).scalar() or 0
    farm_direct_expenses = db.session.query(db.func.sum(Expense.amount)).filter(Expense.unit_id != None, Expense.is_voided == False).scalar() or 0
    
    # Calculate Expenses by Category for the Entire Farm
    expenses_by_category = db.session.query(
        Expense.category, 
        db.func.sum(Expense.amount)
    ).filter_by(is_voided=False).group_by(Expense.category).all()

    # ==========================================
    # 2. INDIVIDUAL BUSINESS UNIT CALCULATIONS
    # ==========================================
    units = BusinessUnit.query.filter_by(is_active=True).all()
    performance = []
    
    for unit in units:
        revenue = db.session.query(db.func.sum(Sale.total_amount)).filter_by(unit_id=unit.id, is_voided=False).scalar() or 0
        # Notice we only sum expenses DIRECTLY tied to this unit. Shared expenses do not reduce this.
        direct_costs = db.session.query(db.func.sum(Expense.amount)).filter_by(unit_id=unit.id, is_voided=False).scalar() or 0
        profit = revenue - direct_costs
        margin = (profit / revenue * 100) if revenue > 0 else 0
        
        performance.append({
            'name': unit.name,
            'revenue': revenue,
            'costs': direct_costs,
            'profit': profit,
            'margin': margin
        })
        
    return render_template('profitability.html', 
                           performance=performance,
                           farm_revenue=farm_revenue,
                           farm_expenses=farm_expenses,
                           farm_profit=farm_profit,
                           farm_margin=farm_margin,
                           farm_cash=farm_cash_received,
                           farm_credit=farm_outstanding_credit,
                           farm_shared=farm_shared_expenses,
                           farm_direct=farm_direct_expenses,
                           expenses_by_category=expenses_by_category)

# ==========================================
# SETTINGS (Master Data Management)
# ==========================================
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_customer':
            new_cust = Customer(
                name=request.form['name'],
                phone=request.form.get('phone'),
                location=request.form.get('location'),
                notes=request.form.get('notes')
            )
            db.session.add(new_cust)
            flash('Customer added!', 'success')
            
        elif action == 'add_unit':
            new_unit = BusinessUnit(name=request.form['name'])
            db.session.add(new_unit)
            flash('Business Unit added!', 'success')
            
        db.session.commit()
        return redirect(url_for('settings'))

    customers = Customer.query.all()
    # Attach balance dynamically
    for c in customers:
        c.balance = get_customer_balance(c.id)
    units = BusinessUnit.query.all()
    
    return render_template('settings.html', customers=customers, units=units)

@app.route('/settings/edit_customer/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    """Allows the user to edit an existing customer's details"""
    customer = Customer.query.get_or_404(id)
    
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.phone = request.form.get('phone')
        customer.location = request.form.get('location')
        customer.notes = request.form.get('notes')
        
        db.session.commit()
        flash(f'Customer {customer.name} updated successfully!', 'success')
        return redirect(url_for('settings'))
        
    return render_template('edit_customer.html', customer=customer)

@app.route('/settings/toggle/<type>/<int:id>')
def toggle_active(type, id):
    """Archives or un-archives a customer or business unit"""
    if type == 'customer':
        obj = Customer.query.get_or_404(id)
    else:
        obj = BusinessUnit.query.get_or_404(id)
        
    obj.is_active = not obj.is_active
    db.session.commit()
    flash(f'{obj.name} status updated.', 'info')
    return redirect(url_for('settings'))

# ==========================================
# LEDGER (Transaction History & Corrections)
# ==========================================
@app.route('/ledger')
def ledger():
    sales = Sale.query.all()
    payments = Payment.query.all()
    expenses = Expense.query.all()
    
    transactions = []
    
    for s in sales:
        transactions.append({
            'id': s.id, 'type': 'Sale', 'date': s.date, 
            'desc': f"Customer: {s.customer.name}", 
            'business': s.business_unit.name, 
            'amount': s.total_amount, 'is_voided': s.is_voided
        })
        
    for p in payments:
        transactions.append({
            'id': p.id, 'type': 'Payment', 'date': p.date, 
            'desc': f"From: {p.customer.name}", 
            'business': '—', 
            'amount': p.amount, 'is_voided': p.is_voided
        })
        
    for e in expenses:
        transactions.append({
            'id': e.id, 'type': 'Expense', 'date': e.date, 
            'desc': e.description, 
            'business': e.business_unit.name if e.business_unit else 'Shared / General', 
            'amount': e.amount, 'is_voided': e.is_voided
        })
        
    # Sort by date descending (newest first)
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('ledger.html', transactions=transactions)


@app.route('/ledger/void/<type>/<int:id>')
def void_transaction(type, id):
    """Soft-deletes a transaction from the math, but leaves it in the ledger"""
    if type == 'Sale':
        obj = Sale.query.get_or_404(id)
    elif type == 'Payment':
        obj = Payment.query.get_or_404(id)
    elif type == 'Expense':
        obj = Expense.query.get_or_404(id)
        
    obj.is_voided = True
    db.session.commit()
    flash(f'{type} successfully voided.', 'warning')
    return redirect(url_for('ledger'))

# ==========================================
# APP INITIALIZATION
# ==========================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Seed initial data for testing if DB is empty
        if not BusinessUnit.query.first():
            db.session.add_all([
                BusinessUnit(name="Fancy Lettuce"),
                BusinessUnit(name="Iceberg Lettuce"),
                BusinessUnit(name="Celery"),
                # Notice we are now seeding with phone and location fields!
                Customer(name="Restaurant ABC", location="Harare", phone="0772123456"),
                Customer(name="Local Market", location="Bulawayo", phone="0712987654")
            ])
            db.session.commit()
            
    app.run(debug=True, port=5000)