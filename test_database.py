import csv
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import database


class TestDatabase(unittest.TestCase):
    def test_sale_before_arrival_rejected_without_partial_import(self):
        with tempfile.TemporaryDirectory() as folder:
            data_dir = Path(folder)

            inventory = [{
                "snapshot_date": "2026-10-06",
                "sku": "TEST-7",
                "style_id": "TEST",
                "category": "Trainers",
                "size": 7,
                "received_date": "2026-10-01",
                "initial_quantity": 5,
                "quantity_remaining": 4,
                "unit_cost_gbp": 20,
                "selling_price_gbp": 35,
            }]

            sales = [{
                "date": "2026-09-30",
                "sku": "TEST-7",
                "quantity": 1,
                "unit_sale_price_gbp": 35,
            }]

            for filename, rows in [
                ("inventory.csv", inventory),
                ("sales.csv", sales),
            ]:
                with (data_dir / filename).open(
                    "w", newline="", encoding="utf-8"
                ) as file:
                    writer = csv.DictWriter(
                        file, fieldnames=list(rows[0])
                    )
                    writer.writeheader()
                    writer.writerows(rows)

            with patch.object(database, "DATA_DIR", data_dir), \
                 patch.object(
                     database, "DB_PATH", data_dir / "test.db"
                 ):
                with self.assertRaisesRegex(
                    ValueError, "precedes stock arrival"
                ):
                    database.initialise_database()

                with closing(database.connect()) as connection:
                    for table in ["inventory", "sales", "metadata"]:
                        count = connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
                        self.assertEqual(count, 0, table)


if __name__ == "__main__":
    unittest.main()