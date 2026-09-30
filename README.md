# Retail Intelligence

Retail Intelligence is a local prototype for exploring how a retail
application can connect sales records, demand forecasts, inventory decisions,
customer feedback, and supplier comparisons. It is intended for demonstration
and research, not for live purchasing or tax-compliant billing.

## What the application does

| Area | Function |
| --- | --- |
| Catalogue and stock | Records products, starting stock, deliveries, corrections, and purchasing settings. |
| Billing | Saves itemised receipts and deducts sold quantities from stock. Voiding a receipt restores those quantities. |
| Daily close | Confirms the day's sales once, including zero-sale observations for stocked products. The latest closed day can be reopened with a recorded reason. |
| Forecast and restocking | Checks whether each product has enough dated sales history, evaluates a shop-specific LightGBM forecast against a simple reference, and shows a next-day forecast and restocking check only when the model passes. |
| Opportunities | Organises customer feedback and owner notes into product ideas and store-improvement suggestions. |
| To-buy | Compares complete supplier offers for products and quantities selected by the owner. It does not place orders. |

The owner application, customer feedback form, and historical research explorer
are separate pages. The application stores shop records in SQLite and runs a
background forecast job after a daily close.

## Run a blank shop

Docker Desktop with Compose is required for the containerised setup. From the
repository root:

```powershell
docker compose up --build -d
```

Open <http://127.0.0.1:8000> for the owner application or
<http://127.0.0.1:8000/feedback> for the customer feedback form. The shop
database is stored in the persistent `shop_data` Docker volume. The application
starts with an empty catalogue.

To stop the container:

```powershell
docker compose down
```

The research explorer is available at <http://127.0.0.1:8000/research> when
the saved experiment files are present under `data/processed/`. Those files
are local research outputs and are not included in this repository.

## Prepare the 6-Seven historical showcase

The optional showcase replays sales from **Favorita Store 44** under the
unofficial display name **6-Seven**. Obtain the Favorita competition data
independently and place `train.csv` and `items.csv` in `data/raw/`. The
competition data and generated shop database are excluded from Git.

With Python 3.12 installed, run the preparer from the repository root:

```powershell
python -m demo.prepare_showcase
docker compose -f compose.demo.yaml up --build -d
```

Open <http://127.0.0.1:8001>. This container uses
`data/app/demo/shop.sqlite3`, separate from the blank shop's Docker volume.
The preparer refuses to overwrite an existing demo database.
The two Compose configurations use the same project name; run one at a time.

The preparer selects 24 anonymous Store 44 items within the catalogue's
product families, prioritising long and recent recorded histories and
whole-unit sales. It loads 179 closed historical days and leaves
**15 August 2017** open. Three example receipts for that date contain
quantities that sum to the selected items' recorded daily sales. Closing the
day through the application starts the forecast job. The selection details
are saved locally to `data/app/demo/selection.json`.

Favorita identifies items by number and category, not by consumer-facing
product name. The showcase's product names and pack sizes are illustrative
assignments. Opening stock, receipt prices, supplier quotes, and any feedback
entered for the showcase are also illustrative. Supplier links are catalogue
references; they do not verify the example prices or availability. Missing
sales rows are treated as zero in the replay, which does not establish that
actual demand was zero.

Stop the showcase container with:

```powershell
docker compose -f compose.demo.yaml down
```

## Forecast behaviour

The owner application requires **180 consecutive closed days** beginning no
earlier than the product's first stocked date. For an eligible product,
LightGBM is checked on three later historical weeks against a four-week
matching-weekday median.
When history is incomplete or the model performs worse, the application
withholds a numeric forecast. A passing model produces seven dated daily
estimates; the first is displayed as the next-day forecast. The inventory
calculation combines those estimates with recorded stock, delivery time,
order increments, and shelf-life settings.

The shop-specific model uses past sales and calendar features. Favorita
research results do not measure accuracy for a new shop, and passing the
three-week check is not a guarantee of safe purchasing decisions.

## Current boundaries

- The application is a local prototype without accounts or access controls.
- Receipts are stock and sales records, not formal tax invoices.
- Supplier quotes in the showcase are invented. The website observation flow
  currently expects an exact website product code; automated matching by name
  and pack size is not implemented.
- Website price observations can be incomplete or unavailable. Only offers
  with confirmed product identity and complete purchasing terms can be
  recommended.
- Opportunity suggestions are based on recorded feedback and notes, not on
  predicted demand for products outside the catalogue.
- No owner-facing bulk import is provided for an ordinary shop; the showcase
  preparer is a separate, local historical replay tool.

## Implementation

The application uses Python's standard-library HTTP server, SQLite, NumPy,
pandas, scikit-learn, and LightGBM. `Dockerfile` and `compose.yaml` define
the local deployment. `app/` contains the interface and shop workflow;
`src/` contains forecasting, inventory, opportunity, and purchasing logic;
`demo/` contains the reproducible showcase preparer and illustrative
catalogue labels.
