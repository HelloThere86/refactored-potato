import sqlite3
import os

def migrate(db_path=None):
    if db_path is None:
        local_app_data = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        candidate = os.path.join(local_app_data, 'RefactoredPotato', 'farm.db')
        db_path = candidate if os.path.exists(candidate) else 'farm.db'

    if not os.path.exists(db_path):
        print(f"Database {db_path} not found. Clean first-run will auto-create schema.")
        return

    print(f"Migrating database at: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 1. Add batch_id to sale table if missing
    c.execute("PRAGMA table_info(sale);")
    columns = [col[1] for col in c.fetchall()]
    if 'batch_id' not in columns:
        print("Adding batch_id column to sale table...")
        c.execute("ALTER TABLE sale ADD COLUMN batch_id INTEGER REFERENCES production_batch(id);")
    else:
        print("batch_id column already exists in sale table.")

    # 2. Create production_batch table
    c.execute("""
    CREATE TABLE IF NOT EXISTS production_batch (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_code VARCHAR(50) UNIQUE NOT NULL,
        unit_id INTEGER NOT NULL REFERENCES business_unit(id),
        planting_date DATE NOT NULL,
        quantity_planted INTEGER NOT NULL,
        planted_unit VARCHAR(50) NOT NULL DEFAULT 'seedlings',
        estimated_remaining_quantity INTEGER NOT NULL,
        expected_harvest_date DATE,
        expected_yield INTEGER,
        status VARCHAR(20) NOT NULL DEFAULT 'growing',
        last_estimate_review_date DATE NOT NULL,
        notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Create harvest_lot table
    c.execute("""
    CREATE TABLE IF NOT EXISTS harvest_lot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        harvest_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        batch_id INTEGER NOT NULL REFERENCES production_batch(id),
        sale_id INTEGER REFERENCES sale(id),
        quantity_harvested INTEGER NOT NULL,
        quantity_sold INTEGER NOT NULL,
        quantity_surplus INTEGER NOT NULL DEFAULT 0,
        quantity_remaining INTEGER NOT NULL DEFAULT 0,
        notes VARCHAR(255),
        is_voided BOOLEAN DEFAULT 0
    );
    """)

    # 4. Create inventory_movement table
    c.execute("""
    CREATE TABLE IF NOT EXISTS inventory_movement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        harvest_lot_id INTEGER NOT NULL REFERENCES harvest_lot(id),
        movement_type VARCHAR(30) NOT NULL,
        quantity INTEGER NOT NULL,
        reason VARCHAR(255)
    );
    """)

    conn.commit()
    conn.close()
    print("V2.0 schema migration complete.")

if __name__ == '__main__':
    migrate()