from pathlib import Path
from database import initialise_database, connect, record_sale
import pandas as pd
import streamlit as st
from contextlib import closing

st.set_page_config(
    page_title="Stock Revive",
    page_icon="👟",
    layout="wide",
)

DATA_DIR = Path(__file__).resolve().parent / "data"

st.title("👟 Stock Revive")
st.caption(
    "Synthetic footwear shop demo • "
    "Find older stock, remaining sizes and money tied up."
)

initialise_database()

with closing(connect()) as connection, connection:
    inventory = pd.read_sql_query("""
        SELECT
            m.value AS snapshot_date,
            i.sku,
            i.style_id,
            i.category,
            i.size,
            i.received_date,
            i.initial_quantity,
            COALESCE(s.quantity_sold, 0) AS quantity_sold,
            i.quantity_remaining,
            i.unit_cost_pence / 100.0 AS unit_cost_gbp,
            i.selling_price_pence / 100.0 AS selling_price_gbp,
            s.last_sale_date,
            i.simulation_scenario
        FROM inventory AS i
        CROSS JOIN metadata AS m
        LEFT JOIN (
            SELECT
                sku,
                SUM(quantity) AS quantity_sold,
                MAX(date) AS last_sale_date
            FROM sales
            GROUP BY sku
        ) AS s ON i.sku = s.sku
        WHERE m.key = 'snapshot_date'
    """, connection)

    sales = pd.read_sql_query("""
        SELECT
            s.sale_id,
            s.date,
            s.sku,
            i.style_id,
            i.category,
            i.size,
            s.quantity,
            s.unit_sale_price_pence / 100.0 AS unit_sale_price_gbp,
            s.unit_cost_pence / 100.0 AS unit_cost_gbp,
            (s.quantity * s.unit_sale_price_pence) / 100.0
                AS revenue_gbp,
            (s.quantity * s.unit_cost_pence) / 100.0
                AS cost_of_goods_gbp,
            (
                s.quantity *
                (s.unit_sale_price_pence - s.unit_cost_pence)
            ) / 100.0 AS gross_profit_gbp
        FROM sales AS s
        JOIN inventory AS i ON s.sku = i.sku
        ORDER BY s.date, s.sale_id
    """, connection)

for column in ["snapshot_date", "received_date", "last_sale_date"]:
    inventory[column] = pd.to_datetime(inventory[column])

sales["date"] = pd.to_datetime(sales["date"])

# Use the dataset's date, so results stay consistent over time.
snapshot_date = inventory["snapshot_date"].max()

inventory["age_days"] = (
    snapshot_date - inventory["received_date"]
).dt.days

inventory["stock_cost"] = (
    inventory["quantity_remaining"] * inventory["unit_cost_gbp"]
)

# Inclusive 30-day window ending on the snapshot date.
window_start = snapshot_date - pd.Timedelta(days=29)
recent_sales = sales[
    sales["date"].between(window_start, snapshot_date)
]
recent_by_style = recent_sales.groupby("style_id")["quantity"].sum()

# Aggregate all sizes into one row per style.
styles = inventory.groupby("style_id").agg(
    category=("category", "first"),
    age_days=("age_days", "max"),
    pairs_remaining=("quantity_remaining", "sum"),
    stock_cost=("stock_cost", "sum"),
    unit_cost=("unit_cost_gbp", "first"),
    selling_price=("selling_price_gbp", "first"),
    last_sale_date=("last_sale_date", "max"),
)

in_stock = inventory[inventory["quantity_remaining"] > 0]

sizes_by_style = in_stock.groupby("style_id").agg(
    sizes_left=("size", "nunique"),
    available_sizes=(
        "size",
        lambda values: ", ".join(
            str(size) for size in sorted(values.unique())
        ),
    ),
)

styles = styles.join(sizes_by_style)
styles["sizes_left"] = styles["sizes_left"].fillna(0).astype(int)
styles["available_sizes"] = styles["available_sizes"].fillna("")
styles["sales_last_30_days"] = (
    styles.index.to_series().map(recent_by_style).fillna(0).astype(int)
)

# For styles with no sales, count days since receipt.
styles["days_without_sale"] = (
    snapshot_date - styles["last_sale_date"]
).dt.days.fillna(styles["age_days"]).astype(int)

styles = styles[styles["pairs_remaining"] > 0].copy()

st.sidebar.header("Attention rules")

old_threshold = st.sidebar.slider(
    "Old stock: minimum age in days", 30, 300, 120, step=10
)
quiet_threshold = st.sidebar.slider(
    "Minimum days without a sale", 7, 120, 30
)
fragmented_threshold = st.sidebar.slider(
    "Few sizes: maximum sizes remaining", 1, 5, 2
)

styles["old_stock"] = styles["age_days"] >= old_threshold
styles["quiet_stock"] = (
    styles["days_without_sale"] >= quiet_threshold
)
styles["few_sizes"] = (
    styles["sizes_left"] <= fragmented_threshold
)

# Age alone does not trigger an alert.
styles["needs_attention"] = (
    styles["quiet_stock"]
    | (styles["old_stock"] & styles["few_sizes"])
)


def explain_flag(row):
    reasons = []
    if row["quiet_stock"]:
        reasons.append(f'{row["days_without_sale"]} days without a sale')
    if row["old_stock"] and row["few_sizes"]:
        reasons.append(f'Old stock with {row["sizes_left"]} sizes left')
    return "; ".join(reasons)


styles["reason"] = styles.apply(explain_flag, axis=1)

flagged = styles[styles["needs_attention"]].sort_values(
    "stock_cost", ascending=False
)

saleable_stock = inventory[
    inventory["quantity_remaining"] > 0
].set_index("sku")

with st.expander("Record a sale", expanded=False):
    st.caption(
        "Saves a transaction and updates available stock. "
        "Use this demo database for practice."
    )

    if saleable_stock.empty:
        st.info("No stock is available to sell.")
    else:
        selected_sale_sku = st.selectbox(
            "Style and size sold",
            options=saleable_stock.index.tolist(),
            format_func=lambda sku: (
                f"{sku} — {saleable_stock.loc[sku, 'category']} "
                f"— {int(saleable_stock.loc[sku, 'quantity_remaining'])} available"
            ),
            key="record_sale_sku",
        )

        sale_item = saleable_stock.loc[selected_sale_sku]
        available_pairs = int(sale_item["quantity_remaining"])

        # The product selector is outside the form so switching
        # products immediately updates its quantity and price.
        with st.form(f"sale_form_{selected_sale_sku}"):
            sale_quantity = st.number_input(
                "Pairs sold",
                min_value=1,
                step=1,
                value=1,
            )

            actual_price = st.number_input(
                "Actual selling price per pair (£)",
                min_value=0.0,
                value=float(sale_item["selling_price_gbp"]),
                step=0.01,
                format="%.2f",
            )

            entered_date = st.date_input(
                "Sale date",
                value=snapshot_date.date(),
                min_value=snapshot_date.date(),
            )

            st.caption(
                f"Available: {available_pairs} pairs. "
                "Dates before the current stock snapshot are not supported."
            )

            submitted = st.form_submit_button("Save sale")

        if submitted:
            try:
                sale_id = record_sale(
                    sku=selected_sale_sku,
                    quantity=int(sale_quantity),
                    unit_price=actual_price,
                    sale_date=entered_date,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["sale_confirmation"] = (
                    f"Sale #{sale_id} saved: {int(sale_quantity)} "
                    f"pair(s) of {selected_sale_sku}."
                )
                st.rerun()

confirmation = st.session_state.pop("sale_confirmation", None)
if confirmation:
    st.success(confirmation)

tab_overview, tab_sizes, tab_discount, tab_export, tab_sales = st.tabs([
    "Overview",
    "Size Alerts",
    "Discount Calculator",
    "Review Export",
    "Sales Analytics",
])

with tab_overview:
    st.caption(f"Stock snapshot: {snapshot_date:%d %B %Y}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pairs in stock", f'{styles["pairs_remaining"].sum():,}')
    col2.metric("Styles needing attention", len(flagged))
    col3.metric("Purchase cost tied up", f'£{flagged["stock_cost"].sum():,.2f}')
    col4.metric("Pairs needing attention", f'{flagged["pairs_remaining"].sum():,}')

    st.caption(
        "Purchase cost tied up is the cost of remaining flagged stock, "
        "not a realised loss. Alerts are adjustable rules, not predictions."
    )

    st.subheader("Stock needing attention")

    if flagged.empty:
        st.info("No styles match the current attention rules.")
    else:
        display = flagged.reset_index()[[
            "style_id",
            "category",
            "age_days",
            "available_sizes",
            "pairs_remaining",
            "sales_last_30_days",
            "stock_cost",
            "reason",
        ]].rename(columns={
            "style_id": "Style",
            "category": "Category",
            "age_days": "Age (days)",
            "available_sizes": "Remaining sizes",
            "pairs_remaining": "Pairs left",
            "sales_last_30_days": "Sold in 30 days",
            "stock_cost": "Stock cost (£)",
            "reason": "Why flagged",
        })

        st.dataframe(
            display,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Stock cost (£)": st.column_config.NumberColumn(
                    format="£%.2f"
                )
            },
        )

    st.subheader("Find stock in a customer's size")

    selected_size = st.selectbox(
        "Customer's shoe size", sorted(inventory["size"].unique())
    )

    matches = in_stock[in_stock["size"] == selected_size].copy()
    matches = matches.merge(
        styles[["needs_attention", "reason"]],
        left_on="style_id",
        right_index=True,
    )

    # Prioritise flagged stock, then older arrivals.
    matches = matches.sort_values(
        ["needs_attention", "age_days"],
        ascending=[False, False],
    )

    size_display = matches[[
        "style_id",
        "category",
        "quantity_remaining",
        "selling_price_gbp",
        "age_days",
        "reason",
    ]].rename(columns={
        "style_id": "Style",
        "category": "Category",
        "quantity_remaining": "Pairs available",
        "selling_price_gbp": "Price (£)",
        "age_days": "Age (days)",
        "reason": "Attention reason",
    })

    st.dataframe(
        size_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Price (£)": st.column_config.NumberColumn(format="£%.2f")
        },
    )

    with st.expander("How this prototype works"):
        st.write(
            "A style needs attention if it has had no sales for the chosen "
            "period, or if it is old and has few sizes remaining. "
            "One recent sale can hide slower sizes within a style; "
            "See the Size Alerts tab for individual sizes needing review."
        )
        st.write(
            "The simulation labels are deliberately excluded from scoring. "
            "All calculations use inventory and transaction records."
        )

with tab_sizes:
    st.subheader("Sizes needing attention")
    st.caption(
        "Check each style and size separately, so sales in one size "
        "do not hide stock sitting unsold in another."
    )

    # Only analyse sizes that still have stock.
    size_stock = inventory[
        inventory["quantity_remaining"] > 0
    ].copy()

    # Last sale is already recorded separately for each SKU.
    size_stock["days_without_sale"] = (
        snapshot_date - size_stock["last_sale_date"]
    ).dt.days.fillna(size_stock["age_days"]).astype(int)

    # Count recent sales separately for each style-size combination.
    recent_by_sku = recent_sales.groupby("sku")["quantity"].sum()

    size_stock["sales_last_30_days"] = (
        size_stock["sku"].map(recent_by_sku).fillna(0).astype(int)
    )

    # Reuse the existing sidebar threshold.
    size_stock["quiet_size"] = (
        size_stock["days_without_sale"] >= quiet_threshold
    )

    # Identify sizes overlooked by the existing style-level alert.
    size_stock["style_already_flagged"] = (
        size_stock["style_id"]
        .map(styles["needs_attention"])
        .fillna(False)
        .astype(bool)
    )

    size_alerts = size_stock[size_stock["quiet_size"]].copy()

    size_alerts["sizes_left"] = (
        size_alerts["style_id"].map(styles["sizes_left"])
    )

    def suggest_review(row):
        old = row["age_days"] >= old_threshold
        fragmented = row["sizes_left"] <= fragmented_threshold
        long_inactive = row["days_without_sale"] >= max(
            60, quiet_threshold
        )

        if old and fragmented and long_inactive:
            return "Clearance review"
        if old:
            return "Review sales pace and price"
        return "Check display and customer interest"

    size_alerts["suggested_action"] = size_alerts.apply(
        suggest_review, axis=1
    )

    size_alerts["alert_reason"] = size_alerts.apply(
        lambda row: (
            f"No sales since arrival "
            f"({row['days_without_sale']} days)"
            if pd.isna(row["last_sale_date"])
            else f"{row['days_without_sale']} days since last sale"
        ),
        axis=1,
    )

    size_alerts = size_alerts.sort_values(
        ["stock_cost", "days_without_sale"],
        ascending=[False, False],
    )

    newly_detected = size_alerts[
        ~size_alerts["style_already_flagged"]
    ]

    col1, col2, col3 = st.columns(3)

    col1.metric("Style-size combinations flagged", len(size_alerts))
    col2.metric(
        "Pairs in these sizes",
        f'{size_alerts["quantity_remaining"].sum():,}',
    )
    col3.metric(
        "Purchase cost in these sizes",
        f'£{size_alerts["stock_cost"].sum():,.2f}',
    )

    st.caption(
        "These totals overlap with the style-level alerts above. "
        "Do not add them together."
    )

    st.info(
        f"{len(newly_detected)} size-level alerts belong to styles "
        "that the original style-level rules did not flag."
    )

    only_new = st.checkbox(
        "Show only alerts missed by the style-level rules",
        value=False,
        key="only_new_size_alerts",
    )

    visible_alerts = newly_detected if only_new else size_alerts

    if visible_alerts.empty:
        st.info("No matching size-level alerts with the current rules.")
    else:
        alert_table = visible_alerts[[
            "style_id",
            "category",
            "size",
            "quantity_remaining",
            "age_days",
            "sales_last_30_days",
            "stock_cost",
            "alert_reason",
            "suggested_action",
        ]].rename(columns={
            "style_id": "Style",
            "category": "Category",
            "size": "Size",
            "quantity_remaining": "Pairs left",
            "age_days": "Age (days)",
            "sales_last_30_days": "Sold in 30 days",
            "stock_cost": "Stock cost (£)",
            "alert_reason": "Why flagged",
            "suggested_action": "Suggested action",
        })

        st.dataframe(
            alert_table,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Stock cost (£)": st.column_config.NumberColumn(
                    format="£%.2f"
                )
            },
        )

with tab_export:
    st.subheader("Download stock review list")
    st.caption(
        "Export the size-level alerts under the current sidebar rules."
    )

    if size_alerts.empty:
        st.info("No size-level alerts to export.")
    else:
        review_list = size_alerts[[
            "style_id",
            "category",
            "size",
            "quantity_remaining",
            "age_days",
            "days_without_sale",
            "sales_last_30_days",
            "stock_cost",
            "alert_reason",
            "suggested_action",
        ]].copy()


        # Blank fields for the owner to record decisions and outcomes.
        review_list["chosen_action"] = ""
        review_list["review_date"] = ""
        review_list["pairs_sold_after_action"] = ""
        review_list["stock_cost"] = review_list["stock_cost"].round(2)

        st.download_button(
            label="Download review list as CSV",
            data=review_list.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"stock_review_{snapshot_date:%Y-%m-%d}.csv",
            mime="text/csv",
        )

with tab_discount:
    st.subheader("Discount calculator by size")
    st.caption(
        "Explore a discount for one flagged style-size combination. "
        "Sales quantities are assumptions, not predictions."
    )

    if size_alerts.empty:
        st.info("No size-level alerts. Adjust the sidebar rules.")
    else:
        calculator_stock = size_alerts.set_index("sku")

        selected_sku = st.selectbox(
            "Choose a style and size",
            options=calculator_stock.index.tolist(),
            format_func=lambda sku: (
                f"{sku} — {calculator_stock.loc[sku, 'category']} "
                f"— {int(calculator_stock.loc[sku, 'quantity_remaining'])} pairs"
            ),
            key="size_discount_sku",
        )

        item = calculator_stock.loc[selected_sku]

        current_price = float(item["selling_price_gbp"])
        purchase_cost = float(item["unit_cost_gbp"])
        pairs_left = int(item["quantity_remaining"])

        st.write(
            f"**Style:** {item['style_id']} · **Size:** {int(item['size'])}"
        )
        st.write(f"**Why flagged:** {item['alert_reason']}")

        discount_percent = st.slider(
            "Discount for this size (%)",
            min_value=0,
            max_value=80,
            value=20,
            step=5,
            key="size_discount_percent",
        )

        discounted_price = round(
            current_price * (1 - discount_percent / 100), 2
        )
        profit_per_pair = round(discounted_price - purchase_cost, 2)
        margin_percent = (
            profit_per_pair / discounted_price * 100
            if discounted_price > 0 else 0
        )

        col1, col2, col3 = st.columns(3)

        col1.metric("Discounted price", f"£{discounted_price:.2f}")
        col1.caption(f"Original price: £{current_price:.2f}")

        col2.metric("Gross profit per pair", f"£{profit_per_pair:.2f}")
        col3.metric("Gross margin", f"{margin_percent:.1f}%")

        if profit_per_pair < 0:
            st.warning(
                f"Below purchase cost: gross loss of "
                f"£{abs(profit_per_pair):.2f} per pair sold."
            )
        elif profit_per_pair == 0:
            st.info("Covers purchase cost only, before other expenses.")
        else:
            st.success(
                f"£{profit_per_pair:.2f} per pair remains after "
                "purchase cost, before other expenses."
            )

        pairs_to_sell = st.number_input(
            "Assumed pairs sold in this size",
            min_value=0,
            max_value=pairs_left,
            value=pairs_left,
            step=1,
            key=f"size_sales_assumption_{selected_sku}",
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Scenario revenue",
            f"£{discounted_price * pairs_to_sell:,.2f}",
        )
        col2.metric(
            "Scenario gross profit",
            f"£{profit_per_pair * pairs_to_sell:,.2f}",
        )
        col3.metric(
            "Purchase cost still tied up",
            f"£{purchase_cost * (pairs_left - pairs_to_sell):,.2f}",
        )

        st.caption(
            f"Assumes {pairs_to_sell} of {pairs_left} pairs in this "
            "size sell at the selected price. Other sizes are excluded. "
            "VAT, fees, overheads and returns are not modelled."
        )

with tab_sizes:
    st.divider()
    st.subheader("Stock map by style and size")
    st.caption(
        "Each number is the remaining quantity. "
        "Grey = sold out · Orange = size needs review · "
        "Blue = in stock without a size-level alert."
    )

    show_old_only = st.checkbox(
        "Show only older styles",
        value=True,
        key="stock_map_old_only",
    )

    map_styles = styles.copy()

    if show_old_only:
        map_styles = map_styles[
            map_styles["age_days"] >= old_threshold
        ]

    # Show styles with fewer remaining sizes first.
    map_styles = map_styles.sort_values(
        ["sizes_left", "age_days"],
        ascending=[True, False],
    )

    if map_styles.empty:
        st.info("No styles match this filter.")
    else:
        stock_map = inventory.pivot_table(
            index="style_id",
            columns="size",
            values="quantity_remaining",
            aggfunc="sum",
            fill_value=0,
        )

        stock_map = stock_map.reindex(
            index=map_styles.index,
            columns=sorted(inventory["size"].unique()),
            fill_value=0,
        ).astype(int)

        alert_cells = set(
            zip(size_alerts["style_id"], size_alerts["size"])
        )

        def colour_stock_map(table):
            colours = pd.DataFrame(
                "", index=table.index, columns=table.columns
            )

            for style_id in table.index:
                for size in table.columns:
                    quantity = table.loc[style_id, size]

                    if quantity == 0:
                        colour = (
                            "background-color: #e5e7eb; color: #374151"
                        )
                    elif (style_id, size) in alert_cells:
                        colour = (
                            "background-color: #fed7aa; color: #7c2d12"
                        )
                    else:
                        colour = (
                            "background-color: #dbeafe; color: #1e3a8a"
                        )

                    colours.loc[style_id, size] = colour

            return colours

        st.dataframe(
            stock_map.style
            .apply(colour_stock_map, axis=None)
            .format("{:.0f}"),
            use_container_width=True,
            height=450,
        ) 

with tab_sales:
    st.subheader("Sales Analytics")
    st.caption(
        "Revenue and gross profit from recorded transactions. "
        "The original sales history is synthetic."
    )

    if sales.empty:
        st.info("No sales have been recorded.")
    else:
        first_date = sales["date"].min().date()
        last_date = max(
            sales["date"].max().date(),
            snapshot_date.date(),
        )

        default_start = max(
            first_date,
            last_date - pd.Timedelta(days=29),
        )

        selected_dates = st.date_input(
            "Select a date range",
            value=(default_start, last_date),
            min_value=first_date,
            max_value=last_date,
            key="sales_date_range",
        )

        if len(selected_dates) != 2:
            st.info("Select both a start date and an end date.")
        else:
            start_date, end_date = selected_dates

            period_sales = sales[
                sales["date"].between(
                    pd.Timestamp(start_date),
                    pd.Timestamp(end_date),
                )
            ].copy()

            pairs_sold = int(period_sales["quantity"].sum())
            revenue = period_sales["revenue_gbp"].sum()
            cost_of_goods = period_sales["cost_of_goods_gbp"].sum()
            gross_profit = period_sales["gross_profit_gbp"].sum()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Pairs sold", f"{pairs_sold:,}")
            col2.metric("Revenue", f"£{revenue:,.2f}")
            col3.metric("Cost of goods sold", f"£{cost_of_goods:,.2f}")
            col4.metric("Gross profit", f"£{gross_profit:,.2f}")

            if revenue > 0:
                st.caption(
                    f"Gross margin: {gross_profit / revenue:.1%}. "
                    "Gross profit excludes VAT adjustments, fees, "
                    "overheads and returns."
                )
            else:
                st.caption(
                    "Gross margin is undefined when revenue is zero. "
                    "Gross profit excludes VAT adjustments, fees, "
                    "overheads and returns."
                )

            if period_sales.empty:
                st.info("No sales in this date range.")
            else:
                st.markdown("**Daily revenue and gross profit**")

                daily_sales = period_sales.groupby("date")[[
                    "revenue_gbp",
                    "gross_profit_gbp",
                ]].sum()

                # Include zero-sales days within the chosen range.
                daily_sales = daily_sales.reindex(
                    pd.date_range(start_date, end_date, freq="D"),
                    fill_value=0,
                )
                daily_sales.index.name = "Date"

                daily_sales = daily_sales.rename(columns={
                    "revenue_gbp": "Revenue (£)",
                    "gross_profit_gbp": "Gross profit (£)",
                })

                if len(daily_sales) == 1:
                    st.bar_chart(daily_sales)
                else:
                    st.line_chart(daily_sales)

                st.markdown("**Transaction history**")

                history = period_sales.sort_values(
                    ["date", "sale_id"],
                    ascending=[False, False],
                )[[
                    "sale_id",
                    "date",
                    "style_id",
                    "category",
                    "size",
                    "quantity",
                    "unit_sale_price_gbp",
                    "unit_cost_gbp",
                    "revenue_gbp",
                    "cost_of_goods_gbp",
                    "gross_profit_gbp",
                ]].rename(columns={
                    "sale_id": "Sale ID",
                    "date": "Date",
                    "style_id": "Style",
                    "category": "Category",
                    "size": "Size",
                    "quantity": "Pairs",
                    "unit_sale_price_gbp": "Price per pair (£)",
                    "unit_cost_gbp": "Cost per pair (£)",
                    "revenue_gbp": "Revenue (£)",
                    "cost_of_goods_gbp": "Cost of goods (£)",
                    "gross_profit_gbp": "Gross profit (£)",
                })

                money_columns = [
                    "Price per pair (£)",
                    "Cost per pair (£)",
                    "Revenue (£)",
                    "Cost of goods (£)",
                    "Gross profit (£)",
                ]

                st.dataframe(
                    history,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        column: st.column_config.NumberColumn(
                            format="£%.2f"
                        )
                        for column in money_columns
                    },
                )

                st.download_button(
                    "Download filtered sales as CSV",
                    data=history.to_csv(
                        index=False,
                        float_format="%.2f",
                    ).encode("utf-8-sig"),
                    file_name=(
                        f"sales_{start_date}_{end_date}.csv"
                    ),
                    mime="text/csv",
                    key="download_sales_history",
                )

with tab_sizes:
    st.divider()

    with st.expander("Demo diagnostics: alerts by simulated scenario"):
        st.caption(
            "Uses simulation labels only to inspect alert behaviour. "
            "These labels are not verified dead-stock outcomes, "
            "so this is not an accuracy score."
        )

        diagnostic = size_stock.copy()
        diagnostic["flagged_pairs"] = (
            diagnostic["quantity_remaining"]
            .where(diagnostic["quiet_size"], 0)
        )
        diagnostic["flagged_cost"] = (
            diagnostic["stock_cost"]
            .where(diagnostic["quiet_size"], 0)
        )

        summary = diagnostic.groupby("simulation_scenario").agg(
            stocked_sizes=("sku", "count"),
            flagged_sizes=("quiet_size", "sum"),
            pairs_remaining=("quantity_remaining", "sum"),
            pairs_flagged=("flagged_pairs", "sum"),
            purchase_cost_flagged=("flagged_cost", "sum"),
        )

        summary["sizes_flagged_percent"] = (
            summary["flagged_sizes"] / summary["stocked_sizes"] * 100
        )

        summary = summary.reset_index().rename(columns={
            "simulation_scenario": "Scenario",
            "stocked_sizes": "Style-size rows in stock",
            "flagged_sizes": "Rows flagged",
            "pairs_remaining": "Pairs in stock",
            "pairs_flagged": "Pairs flagged",
            "purchase_cost_flagged": "Flagged cost (£)",
            "sizes_flagged_percent": "Rows flagged (%)",
        })

        st.dataframe(
            summary,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Flagged cost (£)": st.column_config.NumberColumn(
                    format="£%.2f"
                ),
                "Rows flagged (%)": st.column_config.NumberColumn(
                    format="%.1f"
                ),
            },
        )

        st.write(
            "Check old_steady carefully: its simulated sales are "
            "infrequent, so a 30-day gap can occur even when demand "
            "has not stopped. A review alert does not automatically "
            "justify a discount."
        )