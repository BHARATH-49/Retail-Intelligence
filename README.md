# Retail Intelligence

Retail Intelligence V1 is a **local research prototype** for a shop owner. It joins billing, stock records, demand forecasting, restocking suggestions, customer feedback, and purchase comparison. It is a demonstration of a workflow, not a released system for real purchasing or formal invoices.

## Run the application

To prepare the optional **6-Seven historical showcase**, obtain your own
Favorita competition download and put `train.csv` and `items.csv` in
`data/raw/`. From the project folder, run:

```powershell
.\.venv\Scripts\python.exe -m demo.prepare_showcase
docker compose -f compose.demo.yaml up --build
```

Open <http://127.0.0.1:8001>. This uses an isolated, ignored database at
`data/app/demo/shop.sqlite3`; it never replaces the normal shop database.
The 24 catalogue products are selected by recent recorded history within
their families. On 15 August 2017, three illustrative bills are ready for
review and that day remains open for the viewer to close. Product names,
stock, bills, prices, and supplier quotes are invented and labelled in the
application. The linked supplier pages are catalogue references, not evidence
that the invented prices or availability were published there. A missing
Favorita sales row is treated as zero for this replay,
which does not prove zero demand. The generated selection record stays local
at `data/app/demo/selection.json`. The showcase preparer refuses to overwrite
an existing demo database.

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe app/server.py
```

Open <http://127.0.0.1:8000>. Press Ctrl+C in the terminal to stop. The application binds to this computer only. Runtime dependencies are listed in `requirements-app.txt`; the project uses Python's standard-library web server, SQLite, NumPy, and LightGBM. No fictional shop, catalogue, bills, or sales history is installed. Running directly creates a local database at `data/app/shop.sqlite3`, which Git ignores. Keep a backup of that file if your own entered records matter. The Docker setup uses a separate persistent volume.

The older Favorita experiment explorer is at <http://127.0.0.1:8000/research>. It reads saved results from `data/processed/` when present. The owner application starts even if those research files are absent. The separate customer feedback form is at <http://127.0.0.1:8000/feedback>; it is local to this computer, with no customer authentication.

## Owner workflow

1. **Store → Catalogue:** Set a shop name and currency. Add products with a unique code, counting unit, selling price, opening stock, delivery time, order increment, preferred extra days of cover, and optional shelf life or incoming stock. Later deliveries and corrections change stock through a dated record; opening stock is set once.
2. **Billing → New bill:** Add product quantities and prices, then complete a bill. The app records today's transaction and deducts each product quantity once. **Billing → History** shows that day's completed and voided bills. Voiding a bill restores its stock.
3. **Done for the day:** Review bill count, sales total, and current stock in a confirmation dialog. Closing the day records an explicit daily sales observation, including zero sales for products with no bills. If a day was closed by mistake, reopen the latest closed day with a reason, correct it, and close it again. The earlier forecast is removed on reopening.
4. **Forecast:** The app attempts a shop-specific LightGBM model after a product has **180 consecutive explicitly closed days** since it was first stocked. It checks predictions on the last three historical weeks against a simple four-week same-weekday reference. If history is incomplete or the model does worse, the screen shows “History needed” or “Model check did not pass,” with no numeric recommendation. A passing model gives a dated next-day forecast and uses its next seven daily estimates with current stock and delivery settings for a restocking check. The owner decides whether to add any quantity to To-buy.
5. **Store → Opportunities:** Customer feedback and owner notes produce product ideas and store-improvement issues for review. These are suggestions based on the entered words, not predictions of new-product demand.
6. **To-buy:** The owner selects products and quantities. The **Compare prices** button evaluates saved local supplier quotes and approved exact-product website links. A page price is only an observation; a buyable recommendation needs the owner's product/pack confirmation plus availability, delivery time, fees, and other complete terms. Offline-only price references can be viewed but cannot win an online order recommendation. The app does not place orders.

The Favorita research model and metrics are separate from a shop's own forecast. Historical public-data accuracy does **not** establish how accurate a new shop forecast will be. The shop-specific model is only a prototype adaptation, and the three-week check is a gate rather than proof that its advice is safe for actual stock decisions. There is currently no owner-facing bulk import of shop sales, no login, no tax-compliant invoicing, and no deployment. Entered receipts and daily closes are the normal shop data collection path.

