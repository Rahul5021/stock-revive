import csv
import random
from datetime import date, timedelta
from pathlib import Path

# Reproducible fictional shop
random.seed(42)

AS_OF_DATE = date(2026, 10, 6)
START_DATE = AS_OF_DATE - timedelta(days=365)
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SIZES = range(5, 11)
SIZE_POPULARITY = {
    5: 0.45,
    6: 0.80,
    7: 1.20,
    8: 1.30,
    9: 0.85,
    10: 0.40,
}

# These labels describe the simulated behaviour.
# Later, keep them out of the dashboard's scoring logic.
SCENARIOS = [
    "new_selling_well",
    "old_fragmented",
    "old_steady",
    "recent_slow",
]

inventory = []
sales = []

for style_number in range(1, 51):
    style_id = f"SH{style_number:03d}"
    scenario = SCENARIOS[(style_number - 1) % len(SCENARIOS)]
    category = random.choice(["Trainers", "Casual", "Formal", "Boots"])

    if scenario == "new_selling_well":
        age_days = random.randint(20, 60)
        opening_quantity = random.randint(10, 16)
    elif scenario == "old_fragmented":
        age_days = random.randint(180, 360)
        opening_quantity = random.randint(5, 9)
    elif scenario == "old_steady":
        age_days = random.randint(180, 360)
        opening_quantity = random.randint(22, 30)
    else:
        age_days = random.randint(20, 75)
        opening_quantity = random.randint(8, 14)

    received_date = AS_OF_DATE - timedelta(days=age_days)
    unit_cost = round(random.uniform(15, 45), 2)
    selling_price = round(unit_cost * random.uniform(1.6, 2.1), 2)

    for size in SIZES:
        sku = f"{style_id}-{size}"
        remaining = opening_quantity
        last_sale_date = None
        units_sold = 0

        for day_offset in range(age_days + 1):
            sale_date = received_date + timedelta(days=day_offset)

            if scenario == "new_selling_well":
                probability = 0.18 * SIZE_POPULARITY[size]

            elif scenario == "old_fragmented":
                # Popular sizes sell early; sales then fade.
                if day_offset < 90:
                    probability = 0.12 * SIZE_POPULARITY[size]
                else:
                    probability = 0.002 * SIZE_POPULARITY[size]

            elif scenario == "old_steady":
                probability = 0.035 * SIZE_POPULARITY[size]

            else:
                probability = 0.008 * SIZE_POPULARITY[size]

            if remaining > 0 and random.random() < probability:
                # Occasional fictional promotion.
                discount = random.choice([0, 0, 0, 0.10])
                actual_price = round(selling_price * (1 - discount), 2)

                sales.append({
                    "date": sale_date.isoformat(),
                    "sku": sku,
                    "style_id": style_id,
                    "size": size,
                    "quantity": 1,
                    "unit_sale_price_gbp": actual_price,
                    "revenue_gbp": actual_price,
                })

                remaining -= 1
                units_sold += 1
                last_sale_date = sale_date

        inventory.append({
            "snapshot_date": AS_OF_DATE.isoformat(),
            "sku": sku,
            "style_id": style_id,
            "category": category,
            "size": size,
            "received_date": received_date.isoformat(),
            "initial_quantity": opening_quantity,
            "quantity_sold": units_sold,
            "quantity_remaining": remaining,
            "unit_cost_gbp": unit_cost,
            "selling_price_gbp": selling_price,
            "last_sale_date": (
                last_sale_date.isoformat() if last_sale_date else ""
            ),
            "simulation_scenario": scenario,
        })

sales.sort(key=lambda row: (row["date"], row["sku"]))

# Validate stock accounting against the transaction records.
sold_by_sku = {}
for transaction in sales:
    sku = transaction["sku"]
    sold_by_sku[sku] = sold_by_sku.get(sku, 0) + transaction["quantity"]

for item in inventory:
    recorded_sales = sold_by_sku.get(item["sku"], 0)
    assert recorded_sales == item["quantity_sold"]
    assert item["quantity_remaining"] >= 0
    assert (
        item["initial_quantity"]
        == recorded_sales + item["quantity_remaining"]
    )
    assert START_DATE <= date.fromisoformat(item["received_date"]) <= AS_OF_DATE


def save_csv(filename, rows):
    with (DATA_DIR / filename).open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


save_csv("inventory.csv", inventory)
save_csv("sales.csv", sales)

remaining_pairs = sum(row["quantity_remaining"] for row in inventory)
stock_cost = sum(
    row["quantity_remaining"] * row["unit_cost_gbp"]
    for row in inventory
)

print("Synthetic data generated successfully.")
print(f"Snapshot date: {AS_OF_DATE}")
print(f"Styles: 50 | Size-level inventory rows: {len(inventory)}")
print(f"Sales transactions: {len(sales)}")
print(f"Remaining pairs: {remaining_pairs}")
print(f"Remaining stock at purchase cost: £{stock_cost:,.2f}")
print(f"Files saved in: {DATA_DIR}")