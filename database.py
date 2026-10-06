import csv
import sqlite3
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "stock_revive.db"


def to_pence(value):
    """Store money as whole pence to avoid floating-point errors."""
    amount = Decimal(str(value))

    if not amount.is_finite() or amount < 0:
        raise ValueError("Price must be a finite, non-negative amount.")

    return int(
        (amount * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise_database():
    DATA_DIR.mkdir(exist_ok=True)

    with connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS inventory (
                sku TEXT PRIMARY KEY,
                style_id TEXT NOT NULL,
                category TEXT NOT NULL,
                size INTEGER NOT NULL,
                received_date TEXT NOT NULL,
                initial_quantity INTEGER NOT NULL
                    CHECK(initial_quantity >= 0),
                quantity_remaining INTEGER NOT NULL
                    CHECK(quantity_remaining >= 0),
                unit_cost_pence INTEGER NOT NULL
                    CHECK(unit_cost_pence >= 0),
                selling_price_pence INTEGER NOT NULL
                    CHECK(selling_price_pence >= 0),
                simulation_scenario TEXT,
                UNIQUE(style_id, size)
            );

            CREATE TABLE IF NOT EXISTS sales (
                sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                sku TEXT NOT NULL REFERENCES inventory(sku),
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_sale_price_pence INTEGER NOT NULL
                    CHECK(unit_sale_price_pence >= 0),
                unit_cost_pence INTEGER NOT NULL
                    CHECK(unit_cost_pence >= 0)
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS sales_sku_date
                ON sales(sku, date);
        """)

        # Lock during initialisation to prevent duplicate imports.
        connection.execute("BEGIN IMMEDIATE")

        imported = connection.execute(
            "SELECT value FROM metadata WHERE key = 'import_complete'"
        ).fetchone()

        if imported:
            return

        with (DATA_DIR / "inventory.csv").open(
            encoding="utf-8-sig", newline=""
        ) as file:
            inventory_rows = list(csv.DictReader(file))

        with (DATA_DIR / "sales.csv").open(
            encoding="utf-8-sig", newline=""
        ) as file:
            sales_rows = list(csv.DictReader(file))

        if not inventory_rows:
            raise ValueError("The inventory CSV is empty.")

        snapshots = {
            date.fromisoformat(row["snapshot_date"])
            for row in inventory_rows
        }
        if len(snapshots) != 1:
            raise ValueError("Inventory must have one snapshot date.")

        snapshot_date = snapshots.pop()
        cost_by_sku = {}
        initial_by_sku = {}
        remaining_by_sku = {}

        for row in inventory_rows:
            sku = row["sku"]
            cost = to_pence(row["unit_cost_gbp"])
            initial = int(row["initial_quantity"])
            remaining = int(row["quantity_remaining"])
            received = date.fromisoformat(row["received_date"])

            if received > snapshot_date:
                raise ValueError(f"Arrival date is invalid for {sku}.")

            connection.execute("""
                INSERT INTO inventory VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                sku,
                row["style_id"],
                row["category"],
                int(row["size"]),
                received.isoformat(),
                initial,
                remaining,
                cost,
                to_pence(row["selling_price_gbp"]),
                row.get("simulation_scenario", ""),
            ))

            cost_by_sku[sku] = cost
            initial_by_sku[sku] = initial
            remaining_by_sku[sku] = remaining

        sold_by_sku = {}

        for row in sales_rows:
            sku = row["sku"]
            sale_date = date.fromisoformat(row["date"])
            quantity = int(row["quantity"])

            if sale_date > snapshot_date:
                raise ValueError("Sales cannot follow the snapshot date.")

            connection.execute("""
                INSERT INTO sales (
                    date, sku, quantity,
                    unit_sale_price_pence, unit_cost_pence
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                sale_date.isoformat(),
                sku,
                quantity,
                to_pence(row["unit_sale_price_gbp"]),
                cost_by_sku[sku],
            ))

            sold_by_sku[sku] = sold_by_sku.get(sku, 0) + quantity

        for sku, initial in initial_by_sku.items():
            if initial != (
                remaining_by_sku[sku] + sold_by_sku.get(sku, 0)
            ):
                raise ValueError(f"Stock totals do not match for {sku}.")

        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [
                ("import_complete", "yes"),
                ("snapshot_date", snapshot_date.isoformat()),
            ],
        )


def record_sale(sku, quantity, unit_price, sale_date):
    """Save a sale and reduce stock together, or change nothing."""
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
    ):
        raise ValueError("Quantity must be a positive whole number.")

    parsed_date = date.fromisoformat(str(sale_date))
    price_pence = to_pence(unit_price)

    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")

        item = connection.execute(
            "SELECT * FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()

        if item is None:
            raise ValueError("That style-size combination does not exist.")

        snapshot = connection.execute(
            "SELECT value FROM metadata WHERE key = 'snapshot_date'"
        ).fetchone()

        if snapshot is None:
            raise ValueError("Initialise the database first.")

        current_snapshot = date.fromisoformat(snapshot["value"])

        # The imported CSV is already a completed stock snapshot.
        # New transactions must not be backdated before it.
        if parsed_date < current_snapshot:
            raise ValueError(
                f"Sale date must be on or after {current_snapshot}."
            )

        if parsed_date > date.today():
            raise ValueError("Sale date cannot be in the future.")

        if parsed_date < date.fromisoformat(item["received_date"]):
            raise ValueError("Sale date cannot precede stock arrival.")

        updated = connection.execute("""
            UPDATE inventory
            SET quantity_remaining = quantity_remaining - ?
            WHERE sku = ? AND quantity_remaining >= ?
        """, (quantity, sku, quantity))

        if updated.rowcount != 1:
            raise ValueError(
                f"Only {item['quantity_remaining']} pairs are available."
            )

        cursor = connection.execute("""
            INSERT INTO sales (
                date, sku, quantity,
                unit_sale_price_pence, unit_cost_pence
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            parsed_date.isoformat(),
            sku,
            quantity,
            price_pence,
            item["unit_cost_pence"],
        ))

        connection.execute("""
            UPDATE metadata SET value = ?
            WHERE key = 'snapshot_date'
        """, (parsed_date.isoformat(),))

        return cursor.lastrowid


if __name__ == "__main__":
    initialise_database()

    with connect() as connection:
        inventory_count = connection.execute(
            "SELECT COUNT(*) FROM inventory"
        ).fetchone()[0]

        sale_count = connection.execute(
            "SELECT COUNT(*) FROM sales"
        ).fetchone()[0]

    print(f"Database ready: {DB_PATH}")
    print(f"Inventory rows: {inventory_count}")
    print(f"Sales transactions: {sale_count}")