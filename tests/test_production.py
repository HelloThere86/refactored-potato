import pytest
from datetime import datetime, timedelta
from models import db, BusinessUnit, Customer, Sale, Payment, ProductionBatch, HarvestLot, InventoryMovement

@pytest.fixture
def production_data(app):
    with app.app_context():
        lettuce = BusinessUnit(name="Fancy Lettuce")
        honey = BusinessUnit(name="Honey")
        customer = Customer(name="Hotel Safari", phone="077999888")
        db.session.add_all([lettuce, honey, customer])
        db.session.commit()

        lettuce_id = lettuce.id
        honey_id = honey.id
        customer_id = customer.id

        batch = ProductionBatch(
            batch_code="FL-2026-B01",
            unit_id=lettuce_id,
            planting_date=datetime.utcnow().date(),
            quantity_planted=1000,
            planted_unit="seedlings",
            estimated_remaining_quantity=800,
            status="growing",
            last_estimate_review_date=datetime.utcnow().date()
        )
        db.session.add(batch)
        db.session.commit()

        batch_id = batch.id

        return {
            "lettuce_id": lettuce_id,
            "honey_id": honey_id,
            "customer_id": customer_id,
            "batch_id": batch_id
        }

def test_production_batch_creation(app, production_data):
    """Verifies batch tracks planted units vs saleable heads."""
    with app.app_context():
        b = ProductionBatch.query.get(production_data["batch_id"])
        assert b.quantity_planted == 1000
        assert b.planted_unit == "seedlings"
        assert b.estimated_remaining_quantity == 800
        assert b.status == "growing"

def test_update_field_estimate(app, client, production_data):
    """Verifies farmer can update field estimates directly without inventory movements."""
    batch_id = production_data["batch_id"]
    res = client.post(f"/batches/{batch_id}/update-estimate", data={
        "estimated_remaining_quantity": "750",
        "status": "harvesting"
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        refreshed = ProductionBatch.query.get(batch_id)
        assert refreshed.estimated_remaining_quantity == 750
        assert refreshed.status == "harvesting"
        assert InventoryMovement.query.count() == 0

def test_combined_sale_exact_quantity(app, client, production_data):
    """Verifies cut-to-order sale where harvested == sold."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    res = client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "80",
        "quantity_harvested": "80",
        "unit_price": "1.50",
        "amount_paid": "0"
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        sale = Sale.query.filter_by(batch_id=batch_id).first()
        assert sale.quantity == 80
        assert sale.total_amount == 120.0

        refreshed_batch = ProductionBatch.query.get(batch_id)
        assert refreshed_batch.estimated_remaining_quantity == 720  # 800 - 80

        lot = HarvestLot.query.filter_by(sale_id=sale.id).first()
        assert lot.quantity_harvested == 80
        assert lot.quantity_sold == 80
        assert lot.quantity_surplus == 0
        assert lot.quantity_remaining == 0

def test_combined_sale_with_occasional_extra(app, client, production_data):
    """Verifies customer buys 80 heads, but farmer cuts 81 (extra logged as surplus)."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "80",
        "quantity_harvested": "81",
        "unit_price": "1.00",
        "amount_paid": "0"
    }, follow_redirects=True)

    with app.app_context():
        sale = Sale.query.filter_by(batch_id=batch_id).first()
        assert sale.total_amount == 80.0  # Revenue strictly on 80 sold

        refreshed_batch = ProductionBatch.query.get(batch_id)
        assert refreshed_batch.estimated_remaining_quantity == 719  # 800 - 81

        lot = HarvestLot.query.filter_by(sale_id=sale.id).first()
        assert lot.quantity_harvested == 81
        assert lot.quantity_sold == 80
        assert lot.quantity_surplus == 1
        assert lot.quantity_remaining == 1

        mov = InventoryMovement.query.filter_by(harvest_lot_id=lot.id).first()
        assert mov.movement_type == "surplus_created"
        assert mov.quantity == 1

def test_reject_sale_exceeding_field_availability(app, client, production_data):
    """Blocks transactions when harvest quantity exceeds field availability."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    res = client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "900",
        "quantity_harvested": "900",
        "unit_price": "1.00",
        "amount_paid": "0"
    }, follow_redirects=True)

    assert b"Insufficient field availability" in res.data
    with app.app_context():
        assert Sale.query.count() == 0
        assert ProductionBatch.query.get(batch_id).estimated_remaining_quantity == 800

def test_unsupported_business_unit_unaffected(app, client, production_data):
    """Verifies Honey does not require a batch and uses standard V1 sales path."""
    customer_id = production_data["customer_id"]
    honey_id = production_data["honey_id"]

    res = client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": honey_id,
        "quantity": "5",
        "unit_price": "6.00",
        "amount_paid": "30.0"
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        sale = Sale.query.filter_by(unit_id=honey_id).first()
        assert sale.total_amount == 30.0
        assert sale.batch_id is None
        assert HarvestLot.query.count() == 0

def test_void_sale_preserves_physical_harvest_and_retains_surplus(app, client, production_data):
    """Corrected Rule: Voiding a financial sale does NOT restore field availability.
    Physically cut produce is retained in surplus cut inventory."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    # Sell 50, cut 52 (2 surplus). Field drops from 800 to 748.
    client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "50",
        "quantity_harvested": "52",
        "unit_price": "1.00",
        "amount_paid": "0"
    })

    with app.app_context():
        sale = Sale.query.filter_by(batch_id=batch_id).first()
        sale_id = sale.id
        lot_id = sale.harvest_lot.id
        assert ProductionBatch.query.get(batch_id).estimated_remaining_quantity == 748

    # Void the financial sale
    client.get(f"/ledger/void/Sale/{sale_id}")

    with app.app_context():
        # Field availability must NOT increase (produce was physically cut)
        refreshed_batch = ProductionBatch.query.get(batch_id)
        assert refreshed_batch.estimated_remaining_quantity == 748

        # Harvest lot is preserved: all 52 cut heads are now surplus inventory
        refreshed_lot = HarvestLot.query.get(lot_id)
        assert refreshed_lot.is_voided is False
        assert refreshed_lot.quantity_sold == 0
        assert refreshed_lot.quantity_remaining == 52

        # Movement audit trail
        mov = InventoryMovement.query.filter_by(movement_type="sale_voided_surplus").first()
        assert mov.quantity == 50

def test_cancel_erroneous_harvest_uncut(app, client, production_data):
    """Verifies separate auditable path when crop was entered in error and NEVER cut."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    # Sale of 20 cut heads
    client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "20",
        "quantity_harvested": "20",
        "unit_price": "1.00",
        "amount_paid": "0"
    })

    with app.app_context():
        sale = Sale.query.filter_by(batch_id=batch_id).first()
        sale_id = sale.id
        lot_id = sale.harvest_lot.id

    # 1. Guard check: Cannot cancel harvest while sale is active
    res_guard = client.post(f"/harvests/{lot_id}/cancel-uncut", follow_redirects=True)
    assert b"Cannot cancel harvest lot" in res_guard.data

    # 2. Void financial sale first
    client.get(f"/ledger/void/Sale/{sale_id}")

    # 3. Now cancel harvest as uncut (crop was not actually cut)
    res_cancel = client.post(f"/harvests/{lot_id}/cancel-uncut", follow_redirects=True)
    assert res_cancel.status_code == 200

    with app.app_context():
        # Field availability is now restored
        assert ProductionBatch.query.get(batch_id).estimated_remaining_quantity == 800
        lot = HarvestLot.query.get(lot_id)
        assert lot.is_voided is True
        assert lot.quantity_remaining == 0

def test_cancel_erroneous_harvest_handles_consumed_surplus(app, client, production_data):
    """Verifies cancelling uncut harvest only restores unconsumed stock, preventing phantom inventory."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    # Harvest 10 (10 sold, 0 extra initially)
    client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "10",
        "quantity_harvested": "10",
        "unit_price": "1.00",
        "amount_paid": "0"
    })
    with app.app_context():
        sale = Sale.query.filter_by(batch_id=batch_id).first()
        sale_id = sale.id
        lot_id = sale.harvest_lot.id

    # Void sale: 10 heads become surplus
    client.get(f"/ledger/void/Sale/{sale_id}")

    # Log 3 heads as waste
    client.post("/inventory/waste", data={
        "lot_id": lot_id,
        "quantity": "3",
        "movement_type": "waste",
        "reason": "Damaged"
    })

    # Now cancel uncut: only the 7 unconsumed heads can be restored to the field
    client.post(f"/harvests/{lot_id}/cancel-uncut")

    with app.app_context():
        batch = ProductionBatch.query.get(batch_id)
        # Originally 800 -> 790 -> +7 restored = 797 (NOT 800, because 3 were wasted!)
        assert batch.estimated_remaining_quantity == 797

def test_atomic_rollback_on_midway_failure(app, monkeypatch, client, production_data):
    """Verifies that an unhandled failure midway through transaction rolls back ALL changes."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    with app.app_context():
        initial_sales = Sale.query.count()
        initial_lots = HarvestLot.query.count()
        initial_est = ProductionBatch.query.get(batch_id).estimated_remaining_quantity

    # Inject failure into db.session.commit
    def broken_commit():
        raise RuntimeError("Simulated database failure midway through transaction!")

    monkeypatch.setattr(db.session, "commit", broken_commit)

    res = client.post("/sales/new", data={
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "50",
        "quantity_harvested": "50",
        "unit_price": "2.00",
        "amount_paid": "50.0"
    }, follow_redirects=True)

    assert b"Transaction failed and was completely rolled back" in res.data

    with app.app_context():
        # Confirm complete rollback: no sale, no harvest lot, no payment, no field deduction
        assert Sale.query.count() == initial_sales
        assert HarvestLot.query.count() == initial_lots
        assert Payment.query.count() == 0
        assert ProductionBatch.query.get(batch_id).estimated_remaining_quantity == initial_est

def test_duplicate_submission_blocked(app, client, production_data):
    """Verifies rapid duplicate submissions are blocked to prevent double-cutting or double-billing."""
    batch_id = production_data["batch_id"]
    customer_id = production_data["customer_id"]
    lettuce_id = production_data["lettuce_id"]

    payload = {
        "customer_id": customer_id,
        "unit_id": lettuce_id,
        "batch_id": batch_id,
        "quantity": "10",
        "quantity_harvested": "10",
        "unit_price": "1.00",
        "amount_paid": "0"
    }

    # Request 1: succeeds
    res1 = client.post("/sales/new", data=payload, follow_redirects=True)
    assert b"Sale recorded" in res1.data

    # Request 2 (Immediate duplicate): blocked
    res2 = client.post("/sales/new", data=payload, follow_redirects=True)
    assert b"Duplicate transaction detected" in res2.data

    with app.app_context():
        assert Sale.query.count() == 1
        assert ProductionBatch.query.get(batch_id).estimated_remaining_quantity == 790