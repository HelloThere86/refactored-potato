# Refactored Potato 🥔

A simple farm business management and profitability system for tracking sales, expenses, customer credit, payments, and business profitability.

## 🎯 Purpose

Refactored Potato was created to solve a simple problem:

> **Where is the money going, and which parts of the farm business are actually profitable?**

The system is designed for a small family farming operation where multiple businesses operate under the same household.

Current and planned business units include:

* 🥬 Fancy Lettuce
* 🥬 Iceberg Lettuce
* 🌿 Celery
* 🌳 Trees / Seedlings
* 🍄 Mushrooms
* 🐝 Honey
* 🐔 Chickens

The application records financial activity and uses that information to provide a clear picture of revenue, expenses, cash flow, customer debt, and profitability.

---

## ✨ Core Features

### Sales

* Record sales
* Record products and quantities
* Record customers
* Record selling location
* Track paid, partially paid, and credit sales

### Expenses

* Record every business expense
* Track expense categories
* Associate expenses with specific businesses
* Record shared/general expenses
* Track even small purchases

### Customer Credit

* Track customers who owe money
* Record partial payments
* Record full payments
* Automatically calculate outstanding balances
* Maintain a complete customer transaction history

### Profitability

* Calculate revenue
* Calculate expenses
* Calculate estimated profit
* Calculate profit margin
* Compare profitability between business units
* Filter profitability by date range

### Dashboard

Provide a simple overview of:

* Total sales
* Cash received
* Credit sales
* Outstanding customer debt
* Total expenses
* Net cash flow
* Estimated profit

---

## 🧑‍🌾 Designed for Real Users

One of the primary users is a farmer who is not highly comfortable with computers.

Therefore, usability is a core requirement.

The application should provide:

* Large, clear buttons
* Simple terminology
* Minimal data entry
* Logical navigation
* Clear feedback after actions
* Simple dashboards
* Mobile/tablet-friendly interfaces
* Minimal technical/accounting terminology

The goal is that a user can record a sale or expense without needing to understand how the underlying database works.

---

## 🏗️ Planned Technology Stack

### Backend

* Python
* Flask

### Database

* SQLite during development
* Designed for possible migration to PostgreSQL/MariaDB

### Frontend

* HTML
* CSS
* JavaScript

### Development Tools

* Git
* GitHub
* Docker (planned)
* Linux deployment (planned)

---

## 📁 Project Structure

The project is expected to follow a structure similar to:

```text
refactored-potato/
│
├── app/
│   ├── __init__.py
│   ├── routes/
│   ├── models/
│   ├── services/
│   ├── templates/
│   └── static/
│
├── tests/
│
├── instance/
│
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── run.py
```

The structure may evolve as development progresses.

---

## 🚀 Development Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd refactored-potato
```

### 2. Create a virtual environment

Windows:

```bash
python -m venv .venv
```

Activate it:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy:

```text
.env.example
```

to:

```text
.env
```

and configure the required values.

### 5. Run the application

```bash
python run.py
```

The application should then be available locally.

---

## 🗃️ Core Data Model

The initial database is expected to contain entities representing:

```text
Users
  │
  ├── Sales
  │     ├── Sale Items
  │     └── Payments
  │
  ├── Expenses
  │     └── Expense Allocations
  │
  └── Audit Log

Customers
  └── Sales / Payments

Businesses / Products
  ├── Sales
  ├── Expenses
  └── Production (future)
```

---

## 📊 Profitability

The system distinguishes between:

### Revenue

The value of products sold.

### Cash Received

Money actually received from customers.

### Expenses

Money spent by the business.

### Credit

Sales that have been made but have not yet been fully paid.

### Estimated Profit

```text
Revenue - Relevant Expenses
```

Profitability calculations must clearly indicate when insufficient information is available.

The system should never invent financial information.

---

## 🛣️ Roadmap

### Phase 1 — Financial Tracking

* [ ] User authentication
* [ ] Business/product management
* [ ] Customer management
* [ ] Sales
* [ ] Expenses
* [ ] Credit sales
* [ ] Customer payments
* [ ] Dashboard
* [ ] Basic profitability

### Phase 2 — Better Business Visibility

* [ ] Financial reports
* [ ] Expense analysis
* [ ] Sales reports
* [ ] Customer debt reports
* [ ] Charts
* [ ] CSV/PDF exports
* [ ] Audit history

### Phase 3 — Production

* [ ] Production cycles
* [ ] Planting records
* [ ] Harvest records
* [ ] Production losses
* [ ] Stock tracking
* [ ] Cost per unit

### Phase 4 — Business Intelligence

* [ ] Break-even analysis
* [ ] Profit projections
* [ ] Historical trends
* [ ] Production forecasting
* [ ] Business performance comparisons

### Phase 5 — Infrastructure

* [ ] Docker
* [ ] Automated testing
* [ ] CI/CD
* [ ] Linux server deployment
* [ ] Automated backups
* [ ] Monitoring

---

## 🔐 Security

Financial information is sensitive.

The application should:

* Hash passwords securely
* Never store passwords in plaintext
* Validate user input
* Protect authenticated routes
* Use environment variables for secrets
* Maintain an audit trail for important financial changes
* Avoid committing secrets or databases containing sensitive information to Git

---

## 🤝 Development Philosophy

Refactored Potato is being developed as both a practical business application and a learning project.

Development should prioritize:

1. Correctness
2. Simplicity
3. Usability
4. Maintainability
5. Security
6. Extensibility

Features should be implemented incrementally rather than building an unnecessarily complex system from the beginning.

---

## 📜 License

License to be determined.
