import sqlite3
import os

DB_PATH = 'instance/farm.db'

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database farm.db not found! Please run this in your project root.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        print("1. Adding 'scope' column to Expense table...")
        c.execute("ALTER TABLE expense ADD COLUMN scope VARCHAR(20) DEFAULT 'unallocated'")
    except sqlite3.OperationalError:
        print("   -> 'scope' column already exists. Skipping.")

    print("2. Creating expense_allocations association table...")
    c.execute("""
        CREATE TABLE IF NOT EXISTS expense_allocations (
            expense_id INTEGER,
            business_unit_id INTEGER,
            PRIMARY KEY (expense_id, business_unit_id),
            FOREIGN KEY(expense_id) REFERENCES expense(id),
            FOREIGN KEY(business_unit_id) REFERENCES business_unit(id)
        )
    """)

    print("3. Migrating existing V1.1 data to V1.2 schema...")
    # Migrate specific expenses
    c.execute("UPDATE expense SET scope = 'specific' WHERE unit_id IS NOT NULL")
    c.execute("""
        INSERT OR IGNORE INTO expense_allocations (expense_id, business_unit_id)
        SELECT id, unit_id FROM expense WHERE unit_id IS NOT NULL
    """)
    
    # Migrate farm-wide expenses (Null unit_ids from V1.1 were treated as Farm-Wide)
    c.execute("UPDATE expense SET scope = 'farm' WHERE unit_id IS NULL AND scope = 'unallocated'")

    conn.commit()
    conn.close()
    print("Migration successful! Your database is now ready for V1.2.")

if __name__ == '__main__':
    migrate()