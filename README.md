# Retail Intelligence

Retail Intelligence is a local prototype that connects billing, stock records,
demand forecasting, restocking suggestions, customer feedback, and supplier
comparison in one shop workflow. It is a demonstration and research project,
not a production system for purchasing or tax-compliant invoicing.

## Run the application

**Required:** Git and Docker Desktop with Docker Compose. Clone the repository,
then start the application:

```powershell
git clone https://github.com/BHARATH-49/Retail-Intelligence.git
cd Retail-Intelligence
docker compose up --build -d
docker compose ps
```

When the container is healthy, open:

| Page | Address |
| --- | --- |
| Owner application | <http://127.0.0.1:8000> |
| Customer feedback form | <http://127.0.0.1:8000/feedback> |
| Historical research explorer | <http://127.0.0.1:8000/research> |

The owner application starts with an empty catalogue. Its SQLite database is
kept in the persistent `shop_data` Docker volume, so ordinary restarts do not
erase entered records. The research explorer needs saved experiment files in
`data/processed/`; these files are not included in the repository.

### Basic walkthrough without a dataset

1. Open **Store → Catalogue**. Set a shop name and currency, then add a
   product. For example: code `WATER-01`, name `Bottled water`, unit
   `bottle`, selling price `1.00`, and opening stock `10`. The remaining
   delivery and stock settings can keep their defaults.
2. Open **Billing → New bill**. Add two bottles and complete the bill. Under
   **Billing → History**, the receipt should appear and catalogue stock should
   now be eight bottles.
3. Open the separate **Customer feedback form** and enter a facility
   suggestion, such as a request for a seating area. Return to
   **Store → Opportunities** to see the suggestion grouped for review.
4. Open **To-buy**, add six bottles, then add a local supplier quote. A
   complete example is six units per pack, price `4.50` per pack, minimum
   six units, 60 available units, delivery in two days, and delivery fee
   `1.00`. Set the purchase deadline to seven days and press
   **Compare prices**. The application compares complete offers but places
   no order.
5. In **Billing → History**, scroll below the transactions and select
   **Done for the day**. Review the summary, then select **Confirm day close**.
   The Forecast tab will show **History needed** for this new product.
   A numerical forecast requires a longer dated sales history; this is
   expected behaviour, not a startup error.

This path demonstrates the application without downloading any external data.
To see the historical forecasting workflow, use the optional replay below.

## Run the 6-Seven historical replay

The replay uses sales from Favorita Store 44 under the **unofficial** display
name **6-Seven**. It is separate from the empty-shop database. Obtain
`train.csv` and `items.csv` from the
[Favorita competition dataset](https://www.kaggle.com/competitions/favorita-grocery-sales-forecasting/data)
and place them in `data/raw/`. The data files are not distributed with this
repository. Python 3.12 is also required to prepare the replay.

Stop the empty-shop container if it is running, then prepare and launch the
replay from the repository root:

```powershell
docker compose down
python -m demo.prepare_showcase
docker compose -f compose.demo.yaml up --build -d
docker compose -f compose.demo.yaml ps
```

Open <http://127.0.0.1:8001>. The preparer creates
`data/app/demo/shop.sqlite3` and refuses to overwrite an existing demo
database. The generated database and selection record are excluded from Git.
The two Compose configurations use the same project name, so run one at a
time.

The replay selects 24 anonymous Store 44 items with long, recent,
whole-unit sales histories. It loads 179 closed days and leaves
**15 August 2017** open. Three example bills on that date sum to the
selected items' recorded sales quantities. A suggested route through the
interface is:

1. Review **Store → Catalogue** for the 24 selected products and their
   starting stock.
2. Review **Billing → History** for the three example bills and current
   stock. Scroll below the transactions, select **Done for the day**, review
   the summary, then select **Confirm day close**.
3. Open **Forecast**. The background job checks each product against a
   simple historical reference. Products that fail that check remain in the
   table without a numerical forecast.
4. For a product with a forecast, review the restocking result and, if
   desired, add a quantity to **To-buy**. Press **Compare prices** to
   compare the saved illustrative supplier quotes.
5. Submit a customer comment through <http://127.0.0.1:8001/feedback>,
   then review it under **Store → Opportunities**.

The selection details are recorded locally in
`data/app/demo/selection.json`. To replay from the beginning after changing
the demo, stop the container and back up or remove the generated demo
database before running the preparer again.

### What the replay represents

| Element | Origin |
| --- | --- |
| Store number, anonymous item IDs, and dated sales quantities | Favorita data supplied by the person running the replay |
| Product display names and pack sizes | Illustrative assignments based on item categories |
| Opening stock, receipt prices, supplier quotes, and feedback | Illustrative values or entries |

Favorita does not identify the real consumer-facing names of its numbered
items. The linked supplier pages are catalogue references, not evidence
for the invented prices or availability. Missing sales rows are treated as
zero for the replay, which does not prove that actual demand was zero.

## Forecast and application boundaries

The shop-specific LightGBM model uses past sales and calendar features.
A product needs **180 consecutive closed days** beginning no earlier than
its first stocked date. The model is tested on three later historical weeks
against a four-week matching-weekday median. A passing model provides seven
daily estimates; the next day's estimate appears in Forecast, and the
seven-day series feeds the restocking calculation. A failed check withholds
the numerical recommendation. Historical Favorita results do not establish
accuracy for a new shop.

The application runs locally without accounts or access controls. Receipts
are sales and stock records, not formal tax invoices. The website
observation feature currently requires an exact website product code;
automated matching by name and pack size is not implemented. Saved
showcase supplier quotes are invented, and incomplete website observations
cannot become purchase recommendations. Opportunities are suggestions
from feedback and owner notes, not forecasts for new products.

To stop the blank shop, run `docker compose down`. To stop the historical
replay, run `docker compose -f compose.demo.yaml down`. Neither command
deletes the saved shop database.

The application uses Python's standard-library HTTP server, SQLite, NumPy,
pandas, scikit-learn, and LightGBM. `app/` contains the interface and
shop workflow; `src/` contains the decision logic; `demo/` contains the
local replay preparer and illustrative catalogue labels.
