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

## Validation performed

- Confirmed sidebar filters, size selection and tabs update.
- Checked CSV export totals against the dashboard.
- Checked discount calculations and the zero-sales scenario.
- Recorded two one-pair sales; total stock fell from 2,825 to 2,823.
- Confirmed an attempt to sell beyond available stock was rejected.
- Confirmed recorded sales and reduced stock persist after restarting the app.

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

1. Confirm persistence after restarting the app.
2. Add sales history and daily revenue/gross-profit reporting.
3. Evaluate alerts across the synthetic stock patterns.
4. Add incoming stock with appropriate batch and cost handling.