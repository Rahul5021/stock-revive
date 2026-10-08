# Stock Revive

A footwear inventory and analytics prototype built with Python,
Pandas, Streamlit and SQLite.

## Business problem

In footwear retail, popular sizes can sell out while other sizes
of the same style remain behind shelves. New arrivals receive
attention, leaving older stock overlooked and money tied up.

This project explores how size-level stock visibility and
sales analysis can support stock-review and clearance decisions.

The problem was inspired by my experience helping with my
family's footwear business in Nepal.

## Current features

- Adjustable style-level stock-review rules
- Size-level inactivity alerts
- Customer-size stock search
- Stock map showing remaining quantities by style and size
- Discount calculator with gross profit and below-cost warnings
- Downloadable stock-review CSV
- SQLite storage with a one-time synthetic data import
- Sale recording that updates inventory and sales together
- Validation that prevents selling more stock than available
- Sales analytics with date filtering, daily revenue and gross-profit
  trends, transaction history and CSV export
- Suggested review actions based on stock age, inactivity and
  the number of sizes remaining

## Data

The demo uses reproducible synthetic data for 50 footwear styles,
each with sizes 5–10, with arrivals and sales within a one-year window.

Simulated patterns include:
- New stock selling well
- Older stock with fragmented sizes
- Older stock selling steadily
- Recent slow-selling stock

Simulation labels are excluded from alert calculations.
They describe how data was generated, not verified dead-stock labels.

## Alert evaluation
Compared size-level inactivity thresholds of 30, 60 and 90 days.

All thresholds flagged the 25 remaining old-fragmented sizes.
Alerts for old-steady sizes fell from 27 to 14 to 9, while alerts
for recent-slow sizes fell from 60 to 10 to 0.

This demonstrates a trade-off between early review and alert volume.
Simulation scenarios are not verified dead-stock labels, so these
results do not establish accuracy or an optimal threshold.

The prototype distinguishes three suggested actions:
- Check display and customer interest
- Review sales pace and price
- Clearance review

At the default settings, clearance review requires stock aged
at least 120 days, no more than two sizes remaining, and at least
60 days without a sale for the flagged size.

These are starting rules for human review, not automatic
discount decisions or validated recommendations.

## Run locally

Requires Python with Streamlit and Pandas installed.

    python -m pip install streamlit pandas
    python generate_data.py
    python database.py
    python -m streamlit run app.py

The database imports CSV data only once. Regenerating the CSVs
does not reset an existing database.

## Design decisions

- Analyse individual sizes because style-level sales can hide
  inactive sizes.
- Use transparent, adjustable rules for the first prototype.
- Store monetary amounts as integer pence in SQLite.
- Record a sale and reduce stock within one database transaction.
- Use parameterised SQL for transaction inputs.
- Explicitly close SQLite connections after each operation.
- Validate imported sale dates against stock arrival and the
  snapshot date; roll back the entire import if validation fails.

## Validation performed

- Confirmed sidebar filters, size selection and tabs update.
- Checked CSV export totals against the dashboard.
- Checked discount calculations and the zero-sales scenario.
- Recorded two one-pair sales; total stock fell from 2,825 to 2,823.
- Confirmed an attempt to sell beyond available stock was rejected.
- Confirmed recorded sales and reduced stock persist after restarting the app.
- Confirmed all three suggested actions appear in the review CSV:
  60 display/customer-interest reviews, 37 sales-pace/price reviews
  and 15 clearance reviews in the tested snapshot.
- Automated test confirms sales before stock arrival are rejected
  during CSV import, with no partial data retained.

## Run tests

    ```python -m unittest discover -v```

Tests use temporary databases and do not modify the demo database.

## Limitations

- Synthetic data; no real-world sales improvement has been measured.
- Alerts identify stock for review, not confirmed dead stock.
- Discount scenarios assume sales quantities; they do not predict demand.
- No incoming-stock, returns or stock-adjustment workflow yet.
- Current data assumes one delivery per style.
- VAT, payment fees and overheads are not modelled.
- Backdated sales before the current snapshot are not supported.
- Designed as a local, single-shop prototype.
- Review actions entered in exported CSVs are not imported into the app.

## Next steps

1. Simplify the dashboard code and document the alert rules.
2. Expand automated tests to cover sale recording, overselling,
   transaction rollback and review-action boundaries.
3. Prepare screenshots and a short portfolio case study covering
   the business problem, SQL design, analysis and limitations.
4. Add incoming stock with appropriate batch and cost handling.
5. Validate the approach using real shop data when available.