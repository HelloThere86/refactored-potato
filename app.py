from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, BusinessUnit, Customer, Sale, Payment, Expense
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///farm.db'
app.config['SECRET_KEY'] = 'super-secret-key-change-in-production'
db.init_app(app)

# Helper function to calculate customer debt
def get_customer_balance(customer_id):
    sales = db.session.query(db.func.sum(Sale.total_amount)).filter_by(customer_id=customer_id).scalar() or 0
    payments = db.session.query(db.func.sum(Payment.amount)).filter_by(customer_id=customer_id).scalar() or 0
    return sales - payments

@app.route('/')
def dashboard():
    # 1. Calculate Core Dashboard Metrics
    total_sales = db.session.query(db.func.sum(Sale.total_amount)).scalar() or 0
    cash_received = db.session.query(db.func.sum(Payment.amount)).scalar() or 0
    total_expenses = db.session.query(db.func.sum(Expense.amount)).scalar() or 0
    
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
        
    customers = Customer.query.all()
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
        
    customers = Customer.query.all()
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

@app.route('/profitability')
def profitability():
    units = BusinessUnit.query.filter_by(is_active=True).all()
    performance = []
    
    for unit in units:
        revenue = db.session.query(db.func.sum(Sale.total_amount)).filter_by(unit_id=unit.id).scalar() or 0
        direct_costs = db.session.query(db.func.sum(Expense.amount)).filter_by(unit_id=unit.id).scalar() or 0
        profit = revenue - direct_costs
        margin = (profit / revenue * 100) if revenue > 0 else 0
        
        performance.append({
            'name': unit.name,
            'revenue': revenue,
            'costs': direct_costs,
            'profit': profit,
            'margin': margin
        })
        
    return render_template('profitability.html', performance=performance)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Seed initial data for testing if DB is empty
        if not BusinessUnit.query.first():
            db.session.add_all([
                BusinessUnit(name="Fancy Lettuce"),
                BusinessUnit(name="Iceberg Lettuce"),
                BusinessUnit(name="Celery"),
                Customer(name="Restaurant ABC"),
                Customer(name="Local Market")
            ])
            db.session.commit()
    app.run(debug=True, port=5000)