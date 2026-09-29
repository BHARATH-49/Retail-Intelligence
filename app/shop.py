"""Persistent records for one local shop. No sample shop data is installed."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "app" / "shop.sqlite3"


def _day(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise ValueError("Date must be YYYY-MM-DD.") from error


def _positive(value, label, *, allow_zero=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as error:
        raise ValueError(f"{label} must be a number.") from error
    if not result.is_finite() or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{label} must be {'nonnegative' if allow_zero else 'positive'}.")
    return result


def _whole(value, label, *, allow_zero=True):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number.")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a whole number.") from error
    if str(number) != str(value).strip() or number < (0 if allow_zero else 1):
        raise ValueError(f"{label} must be a {'nonnegative' if allow_zero else 'positive'} whole number.")
    return number


def _cents(value, label):
    amount = _positive(value, label, allow_zero=True)
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"{label} cannot have more than two decimal places.")
    return int(cents)


def _dict(row):
    return dict(row) if row is not None else None


class ShopStore:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL, unit TEXT NOT NULL,
                    first_stocked_on TEXT NOT NULL,
                    stock REAL NOT NULL CHECK(stock >= 0),
                    opening_stock REAL NOT NULL CHECK(opening_stock >= 0),
                    unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
                    lead_days INTEGER NOT NULL CHECK(lead_days >= 0),
                    order_increment REAL NOT NULL CHECK(order_increment > 0),
                    extra_cover_days REAL NOT NULL CHECK(extra_cover_days >= 0),
                    incoming_units REAL NOT NULL DEFAULT 0 CHECK(incoming_units >= 0),
                    incoming_day INTEGER CHECK(incoming_day >= 0),
                    shelf_life_days INTEGER CHECK(shelf_life_days > 0),
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    id TEXT PRIMARY KEY, sold_on TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('completed','void')),
                    total_cents INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS receipt_lines (
                    id INTEGER PRIMARY KEY, receipt_id TEXT NOT NULL REFERENCES receipts(id),
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
                    line_total_cents INTEGER NOT NULL CHECK(line_total_cents >= 0)
                );
                CREATE TABLE IF NOT EXISTS stock_events (
                    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
                    event_day TEXT NOT NULL, quantity_change REAL NOT NULL,
                    reason TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS day_closes (
                    day TEXT PRIMARY KEY, status TEXT NOT NULL,
                    version INTEGER NOT NULL, bill_count INTEGER NOT NULL,
                    sales_cents INTEGER NOT NULL, closed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS day_close_events (
                    id INTEGER PRIMARY KEY, day TEXT NOT NULL, action TEXT NOT NULL,
                    version INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forecast_jobs (
                    origin_day TEXT NOT NULL, origin_version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','complete','failed','cancelled')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(origin_day, origin_version)
                );
                CREATE TABLE IF NOT EXISTS imported_sales (
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    day TEXT NOT NULL, units REAL NOT NULL CHECK(units >= 0),
                    PRIMARY KEY(product_id, day)
                );
                CREATE TABLE IF NOT EXISTS forecasts (
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    target_day TEXT NOT NULL, origin_day TEXT NOT NULL,
                    origin_version INTEGER NOT NULL, units REAL NOT NULL,
                    method TEXT NOT NULL,
                    PRIMARY KEY(product_id, target_day, origin_day, origin_version)
                );
                CREATE TABLE IF NOT EXISTS forecast_checks (
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    origin_day TEXT NOT NULL, origin_version INTEGER NOT NULL,
                    status TEXT NOT NULL, reason TEXT NOT NULL,
                    model_mae REAL, baseline_mae REAL,
                    PRIMARY KEY(product_id, origin_day, origin_version)
                );
                CREATE TABLE IF NOT EXISTS to_buy (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id),
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    needed_by_days INTEGER NOT NULL CHECK(needed_by_days >= 0),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
                    supplier TEXT NOT NULL, channel TEXT NOT NULL,
                    source_url TEXT, currency TEXT NOT NULL,
                    pack_units REAL NOT NULL, pack_price REAL NOT NULL,
                    minimum_order_units REAL, available_units REAL,
                    delivery_days INTEGER, delivery_fee REAL,
                    price_status TEXT NOT NULL, checked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS web_links (
                    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
                    site_name TEXT NOT NULL, approved_host TEXT NOT NULL,
                    expected_sku TEXT NOT NULL, url TEXT NOT NULL,
                    mode TEXT NOT NULL, owner_match_confirmed INTEGER NOT NULL DEFAULT 0,
                    pack_units REAL, minimum_order_units REAL, available_units REAL,
                    delivery_days INTEGER, delivery_fee REAL,
                    observed_name TEXT, observed_price REAL, observed_currency TEXT,
                    checked_at TEXT, status TEXT NOT NULL DEFAULT 'not_checked',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY, day TEXT NOT NULL,
                    source TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
                    product_name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL, reported_count INTEGER NOT NULL DEFAULT 1
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self):
        with self.connection() as db:
            values = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM settings")}
        return {
            "shop_name": values.get("shop_name", ""),
            "currency": values.get("currency", ""),
            "demo_day": values.get("demo_day", ""),
            "demo_disclosure": values.get("demo_disclosure", ""),
        }

    def save_settings(self, payload):
        name = str(payload.get("shop_name", "")).strip()
        currency = str(payload.get("currency", "")).strip().upper()
        if not name or len(name) > 100 or len(currency) != 3 or not currency.isalpha():
            raise ValueError("Enter a shop name and three-letter currency code.")
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('shop_name', ?)", (name,))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('currency', ?)", (currency,))
        return self.settings()

    def products(self, *, active_only=True):
        query = "SELECT * FROM products" + (" WHERE active = 1" if active_only else "") + " ORDER BY name"
        with self.connection() as db:
            return [_dict(row) for row in db.execute(query)]

    def product(self, product_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise ValueError("Product not found.")
        return _dict(row)

    def save_product(self, payload):
        sku = str(payload.get("sku", "")).strip()
        name = str(payload.get("name", "")).strip()
        unit = str(payload.get("unit", "")).strip()
        if not sku or not name or not unit or max(len(sku), len(name), len(unit)) > 100:
            raise ValueError("Enter a product code, name, and counting unit.")
        stock = float(_positive(payload.get("opening_stock", 0), "Opening stock", allow_zero=True))
        first_stocked_on = _day(payload.get("first_stocked_on") or date.today().isoformat())
        if first_stocked_on > date.today().isoformat():
            raise ValueError("A product cannot be first stocked on a future day.")
        cents = _cents(payload.get("unit_price", 0), "Selling price")
        lead = _whole(payload.get("lead_days", 0), "Delivery days")
        increment = float(_positive(payload.get("order_increment", 1), "Order increment"))
        cover = float(_positive(payload.get("extra_cover_days", 1), "Extra cover days", allow_zero=True))
        incoming = float(_positive(payload.get("incoming_units", 0), "Incoming units", allow_zero=True))
        incoming_day = payload.get("incoming_day")
        incoming_day = None if incoming_day in (None, "") else _whole(incoming_day, "Incoming day")
        if incoming > 0 and incoming_day is None:
            raise ValueError("Give the arrival day for incoming stock.")
        if incoming == 0:
            incoming_day = None
        shelf = payload.get("shelf_life_days")
        shelf = None if shelf in (None, "") else _whole(shelf, "Shelf life", allow_zero=False)
        product_id = payload.get("id")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if product_id is None:
                try:
                    cursor = db.execute(
                        """INSERT INTO products
                        (sku,name,unit,first_stocked_on,stock,opening_stock,unit_price_cents,lead_days,
                         order_increment,extra_cover_days,incoming_units,incoming_day,shelf_life_days)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sku, name, unit, first_stocked_on, stock, stock, cents, lead, increment,
                         cover, incoming, incoming_day, shelf),
                    )
                except sqlite3.IntegrityError as error:
                    raise ValueError("That product code already exists.") from error
                product_id = cursor.lastrowid
            else:
                original = db.execute("SELECT id,sku,unit FROM products WHERE id = ?", (product_id,)).fetchone()
                if original is None:
                    raise ValueError("Product not found.")
                has_history = db.execute(
                    """SELECT 1 FROM receipt_lines WHERE product_id=? UNION
                    SELECT 1 FROM stock_events WHERE product_id=? UNION
                    SELECT 1 FROM offers WHERE product_id=? UNION
                    SELECT 1 FROM web_links WHERE product_id=? LIMIT 1""",
                    (product_id, product_id, product_id, product_id),
                ).fetchone()
                if has_history and (sku != original["sku"] or unit != original["unit"]):
                    raise ValueError("A product with sales, stock movements, or supplier links must keep its code and unit.")
                try:
                    db.execute(
                        """UPDATE products SET sku=?,name=?,unit=?,unit_price_cents=?,
                        lead_days=?,order_increment=?,extra_cover_days=?,incoming_units=?,
                        incoming_day=?,shelf_life_days=?
                        WHERE id=?""",
                        (sku, name, unit, cents, lead, increment, cover, incoming, incoming_day,
                         shelf, product_id),
                    )
                except sqlite3.IntegrityError as error:
                    raise ValueError("That product code already exists.") from error
        return self.product(product_id)

    def _require_open(self, db, day):
        row = db.execute("SELECT status FROM day_closes WHERE day=?", (day,)).fetchone()
        if row and row["status"] == "closed":
            raise ValueError(f"{day} is closed. Reopen it with a reason before changing its records.")
        later = db.execute(
            "SELECT 1 FROM day_closes WHERE day>? AND status='closed' LIMIT 1", (day,)
        ).fetchone()
        if later:
            raise ValueError("A later day is closed. Correct the latest day first.")

    def stock_change(self, payload):
        product_id = _whole(payload.get("product_id"), "Product ID", allow_zero=False)
        day = _day(payload.get("day"))
        if day > date.today().isoformat():
            raise ValueError("Record a stock change on its actual day, not a future day.")
        reason = str(payload.get("reason", "")).strip()
        if reason not in {"delivery", "return", "correction"}:
            raise ValueError("Choose delivery, return, or correction.")
        try:
            change = Decimal(str(payload.get("quantity_change", "")))
        except (InvalidOperation, TypeError) as error:
            raise ValueError("Stock change must be a number.") from error
        if not change.is_finite() or change == 0:
            raise ValueError("Stock change must be a nonzero number.")
        note = str(payload.get("note", "")).strip()[:300]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_open(db, day)
            product = db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()
            if product is None or Decimal(str(product["stock"])) + change < 0:
                raise ValueError("Product not found or stock would become negative.")
            db.execute("UPDATE products SET stock=stock+? WHERE id=?", (float(change), product_id))
            db.execute(
                "INSERT INTO stock_events(product_id,event_day,quantity_change,reason,note,created_at) VALUES (?,?,?,?,?,?)",
                (product_id, day, float(change), reason, note, datetime.now().isoformat()),
            )
        return self.product(product_id)

    def complete_bill(self, payload):
        day = _day(payload.get("day"))
        if day > date.today().isoformat():
            raise ValueError("A bill cannot be dated in the future.")
        receipt_id = str(payload.get("receipt_id") or uuid.uuid4().hex).strip()
        lines = payload.get("lines")
        if not receipt_id or not isinstance(lines, list) or not lines:
            raise ValueError("A bill needs an ID and at least one product.")
        prepared = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_open(db, day)
            if db.execute("SELECT 1 FROM receipts WHERE id=?", (receipt_id,)).fetchone():
                raise ValueError("This bill was already completed.")
            for line in lines:
                product_id = _whole(line.get("product_id"), "Product ID", allow_zero=False)
                quantity = _positive(line.get("quantity"), "Quantity")
                product = db.execute(
                    "SELECT stock,unit_price_cents FROM products WHERE id=? AND active=1", (product_id,)
                ).fetchone()
                if product is None:
                    raise ValueError(f"Product {product_id} is not in the catalogue.")
                cents = (_cents(line["unit_price"], "Selling price")
                         if line.get("unit_price") not in (None, "") else product["unit_price_cents"])
                total = int((quantity * Decimal(cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                prepared.append((product_id, float(quantity), cents, total))
            required = {}
            for product_id, quantity, _, _ in prepared:
                required[product_id] = required.get(product_id, 0) + quantity
            for product_id, quantity in required.items():
                available = db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()["stock"]
                if available + 1e-9 < quantity:
                    raise ValueError(f"Not enough stock for product {product_id}.")
            total_cents = sum(line[3] for line in prepared)
            db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                       (receipt_id, day, "completed", total_cents, datetime.now().isoformat()))
            db.executemany(
                "INSERT INTO receipt_lines(receipt_id,product_id,quantity,unit_price_cents,line_total_cents) VALUES (?,?,?,?,?)",
                [(receipt_id, *line) for line in prepared],
            )
            for product_id, quantity in required.items():
                db.execute("UPDATE products SET stock=stock-? WHERE id=?", (quantity, product_id))
        return {"id": receipt_id, "day": day, "total_cents": total_cents}

    def bills(self, day):
        day = _day(day)
        with self.connection() as db:
            receipts = [_dict(row) for row in db.execute(
                "SELECT * FROM receipts WHERE sold_on=? ORDER BY created_at,id", (day,)
            )]
            for receipt in receipts:
                receipt["lines"] = [_dict(row) for row in db.execute(
                    """SELECT l.product_id,p.name,l.quantity,l.unit_price_cents,l.line_total_cents
                    FROM receipt_lines l JOIN products p ON p.id=l.product_id
                    WHERE l.receipt_id=? ORDER BY l.id""", (receipt["id"],)
                )]
        return receipts

    def void_bill(self, receipt_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if receipt is None or receipt["status"] != "completed":
                raise ValueError("Completed bill not found.")
            self._require_open(db, receipt["sold_on"])
            for row in db.execute("SELECT product_id,quantity FROM receipt_lines WHERE receipt_id=?", (receipt_id,)):
                db.execute("UPDATE products SET stock=stock+? WHERE id=?", (row["quantity"], row["product_id"]))
            db.execute("UPDATE receipts SET status='void' WHERE id=?", (receipt_id,))
        return {"id": receipt_id, "status": "void"}

    def day_summary(self, day):
        day = _day(day)
        with self.connection() as db:
            totals = db.execute(
                """SELECT COUNT(*) AS bills,COALESCE(SUM(total_cents),0) AS sales_cents
                FROM receipts WHERE sold_on=? AND status='completed'""", (day,)
            ).fetchone()
            close = db.execute("SELECT * FROM day_closes WHERE day=?", (day,)).fetchone()
            stock = [dict(row) for row in db.execute("SELECT id,sku,name,unit,stock FROM products WHERE active=1 ORDER BY name")]
        summary = {"day": day, "bill_count": totals["bills"], "sales_cents": totals["sales_cents"],
                   "stock": stock, "close": _dict(close)}
        snapshot = {key: summary[key] for key in ("day", "bill_count", "sales_cents", "stock")}
        summary["review_token"] = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return summary

    def close_day(self, day, review_token):
        day = _day(day)
        if day > date.today().isoformat():
            raise ValueError("A future day cannot be closed.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM day_closes WHERE day=?", (day,)).fetchone()
            if current and current["status"] == "closed":
                job = db.execute(
                    "SELECT status FROM forecast_jobs WHERE origin_day=? AND origin_version=?",
                    (day, current["version"]),
                ).fetchone()
                return {"day": day, "status": "already_closed", "version": current["version"],
                        "job_status": job["status"] if job else None}
            later = db.execute(
                "SELECT 1 FROM day_closes WHERE day>? AND status='closed' LIMIT 1", (day,)
            ).fetchone()
            if later:
                raise ValueError("Close days in date order; a later day is already closed.")
            future_record = db.execute(
                """SELECT 1 FROM receipts WHERE sold_on>? UNION
                SELECT 1 FROM stock_events WHERE event_day>? LIMIT 1""", (day, day)
            ).fetchone()
            if future_record:
                raise ValueError("Later bills or stock movements exist. Close this day before recording later dates.")
            summary = self.day_summary(day)
            if review_token != summary["review_token"]:
                raise ValueError("The bills or stock changed. Review the day again before closing.")
            version = current["version"] + 1 if current else 1
            now = datetime.now().isoformat()
            db.execute(
                """INSERT INTO day_closes(day,status,version,bill_count,sales_cents,closed_at)
                VALUES (?,'closed',?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET status='closed',version=excluded.version,
                bill_count=excluded.bill_count,sales_cents=excluded.sales_cents,closed_at=excluded.closed_at""",
                (day, version, summary["bill_count"], summary["sales_cents"], now),
            )
            db.execute(
                "INSERT INTO day_close_events(day,action,version,created_at) VALUES (?,'closed',?,?)",
                (day, version, now),
            )
            db.execute(
                "INSERT INTO forecast_jobs(origin_day,origin_version,status,created_at) VALUES (?,?,'queued',?)",
                (day, version, now),
            )
        return {"day": day, "status": "closed", "version": version, "job_status": "queued"}

    def reopen_day(self, day, reason):
        day = _day(day)
        reason = str(reason).strip()
        if len(reason) < 5:
            raise ValueError("Give a short reason for reopening the day.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM day_closes WHERE day=?", (day,)).fetchone()
            if current is None or current["status"] != "closed":
                raise ValueError("That day is not closed.")
            later = db.execute(
                "SELECT 1 FROM day_closes WHERE day>? AND status='closed' LIMIT 1", (day,)
            ).fetchone()
            if later:
                raise ValueError("Only the latest closed day can be reopened.")
            db.execute("UPDATE day_closes SET status='reopened' WHERE day=?", (day,))
            db.execute(
                "UPDATE forecast_jobs SET status='cancelled',finished_at=? WHERE origin_day=? AND origin_version=?",
                (datetime.now().isoformat(), day, current["version"]),
            )
            db.execute("DELETE FROM forecasts WHERE origin_day=?", (day,))
            db.execute("DELETE FROM forecast_checks WHERE origin_day=?", (day,))
            db.execute(
                "INSERT INTO day_close_events(day,action,version,reason,created_at) VALUES (?,'reopened',?,?,?)",
                (day, current["version"], reason[:300], datetime.now().isoformat()),
            )
        return {"day": day, "status": "reopened"}

    def closed_sales(self, product_id, origin_day):
        """Return explicit closed days and sales, never assume an unclosed day is zero."""
        origin_day = _day(origin_day)
        with self.connection() as db:
            closed = [row["day"] for row in db.execute(
                "SELECT day FROM day_closes WHERE status='closed' AND day<=? ORDER BY day", (origin_day,)
            )]
            sales = {row["sold_on"]: row["units"] for row in db.execute(
                """SELECT r.sold_on,SUM(l.quantity) AS units FROM receipts r
                JOIN receipt_lines l ON l.receipt_id=r.id
                WHERE r.status='completed' AND l.product_id=? AND r.sold_on<=?
                GROUP BY r.sold_on""", (product_id, origin_day),
            )}
            imported = {row["day"]: row["units"] for row in db.execute(
                "SELECT day,units FROM imported_sales WHERE product_id=? AND day<=?",
                (product_id, origin_day),
            )}
        for day, units in imported.items():
            if day in sales:
                raise ValueError(f"Imported and billed sales overlap on {day}.")
            sales[day] = units
        return closed, sales

    def validate_ledger(self):
        """Check saved stock and day-close totals before fitting shop sales."""
        with self.connection() as db:
            for row in db.execute("""
                SELECT p.id,p.opening_stock,p.stock,
                COALESCE((SELECT SUM(s.quantity_change) FROM stock_events s WHERE s.product_id=p.id),0) AS changes,
                COALESCE((SELECT SUM(l.quantity) FROM receipt_lines l
                  JOIN receipts r ON r.id=l.receipt_id
                  WHERE l.product_id=p.id AND r.status='completed'),0) AS sold
                FROM products p
            """):
                expected = row["opening_stock"] + row["changes"] - row["sold"]
                if abs(expected - row["stock"]) > 1e-6:
                    raise ValueError(f"Stock ledger mismatch for product {row['id']}; forecasts were stopped.")
            for row in db.execute("""
                SELECT c.day,c.bill_count,c.sales_cents,
                  (SELECT COUNT(*) FROM receipts r WHERE r.sold_on=c.day AND r.status='completed') AS bills,
                  COALESCE((SELECT SUM(r.total_cents) FROM receipts r
                    WHERE r.sold_on=c.day AND r.status='completed'),0) AS total
                FROM day_closes c WHERE c.status='closed'
            """):
                if row["bill_count"] != row["bills"] or row["sales_cents"] != row["total"]:
                    raise ValueError(f"Day-close ledger mismatch for {row['day']}; forecasts were stopped.")

    def enqueue_forecast_job(self, origin_day, version, *, retry=False):
        origin_day = _day(origin_day)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            close = db.execute("SELECT status,version FROM day_closes WHERE day=?", (origin_day,)).fetchone()
            if close is None or close["status"] != "closed" or close["version"] != version:
                raise ValueError("Only the current closed day can have a forecast task.")
            job = db.execute(
                "SELECT * FROM forecast_jobs WHERE origin_day=? AND origin_version=?",
                (origin_day, version),
            ).fetchone()
            if job is None:
                db.execute(
                    "INSERT INTO forecast_jobs(origin_day,origin_version,status,created_at) VALUES (?,?,'queued',?)",
                    (origin_day, version, datetime.now().isoformat()),
                )
            elif retry and job["status"] == "failed":
                db.execute(
                    """UPDATE forecast_jobs SET status='queued',error='',started_at=NULL,finished_at=NULL
                    WHERE origin_day=? AND origin_version=?""",
                    (origin_day, version),
                )
            return _dict(db.execute(
                "SELECT * FROM forecast_jobs WHERE origin_day=? AND origin_version=?",
                (origin_day, version),
            ).fetchone())

    def recover_forecast_jobs(self):
        """A killed process leaves running tickets queued for the next start."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO forecast_jobs(origin_day,origin_version,status,created_at)
                SELECT c.day,c.version,
                  CASE WHEN EXISTS(SELECT 1 FROM forecast_checks f
                    WHERE f.origin_day=c.day AND f.origin_version=c.version)
                  THEN 'complete' ELSE 'queued' END,
                  COALESCE(c.closed_at,?)
                FROM day_closes c WHERE c.status='closed' AND c.closed_at IS NOT NULL
                AND c.day=(SELECT MAX(day) FROM day_closes WHERE status='closed')
                AND NOT EXISTS(SELECT 1 FROM forecast_jobs j
                  WHERE j.origin_day=c.day AND j.origin_version=c.version)""",
                (datetime.now().isoformat(),),
            )
            db.execute("""UPDATE forecast_jobs SET status='queued',started_at=NULL
                WHERE status='running' AND EXISTS (
                    SELECT 1 FROM day_closes c WHERE c.day=forecast_jobs.origin_day
                    AND c.version=forecast_jobs.origin_version AND c.status='closed')""")

    def claim_forecast_job(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("""SELECT j.* FROM forecast_jobs j JOIN day_closes c
                ON c.day=j.origin_day AND c.version=j.origin_version
                WHERE j.status='queued' AND c.status='closed'
                ORDER BY j.created_at,j.origin_day LIMIT 1""").fetchone()
            if job is None:
                return None
            db.execute("""UPDATE forecast_jobs SET status='running',attempts=attempts+1,
                started_at=?,finished_at=NULL,error='' WHERE origin_day=? AND origin_version=?""",
                (datetime.now().isoformat(), job["origin_day"], job["origin_version"]),
            )
            return {"origin_day": job["origin_day"], "origin_version": job["origin_version"]}

    def fail_forecast_job(self, origin_day, version, error):
        with self.connection() as db:
            changed = db.execute("""UPDATE forecast_jobs SET status='failed',finished_at=?,error=?
                WHERE origin_day=? AND origin_version=? AND status='running'""",
                (datetime.now().isoformat(), str(error)[:300], origin_day, version),
            )
            return changed.rowcount == 1

    def save_forecast_results(self, origin_day, version, results, *, complete_job=False):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            close = db.execute("SELECT status,version FROM day_closes WHERE day=?", (origin_day,)).fetchone()
            if close is None or close["status"] != "closed" or close["version"] != version:
                raise ValueError("The day-close version changed; forecast results were not saved.")
            if complete_job:
                job = db.execute(
                    "SELECT status FROM forecast_jobs WHERE origin_day=? AND origin_version=?",
                    (origin_day, version),
                ).fetchone()
                if job is None or job["status"] != "running":
                    raise ValueError("This forecast task is no longer active.")
            db.execute("DELETE FROM forecasts WHERE origin_day=? AND origin_version=?", (origin_day, version))
            db.execute("DELETE FROM forecast_checks WHERE origin_day=? AND origin_version=?", (origin_day, version))
            for result in results:
                db.execute(
                    """INSERT INTO forecast_checks
                    (product_id,origin_day,origin_version,status,reason,model_mae,baseline_mae)
                    VALUES (?,?,?,?,?,?,?)""",
                    (result["product_id"], origin_day, version, result["status"],
                     result["reason"], result.get("model_mae"), result.get("baseline_mae")),
                )
                for target_day, units in result.get("daily", []):
                    db.execute(
                        """INSERT INTO forecasts
                        (product_id,target_day,origin_day,origin_version,units,method)
                        VALUES (?,?,?,?,?,?)""",
                        (result["product_id"], target_day, origin_day, version, units,
                         "shop_lightgbm_sales_calendar_recent"),
                    )
            if complete_job:
                db.execute("""UPDATE forecast_jobs SET status='complete',finished_at=?,error=''
                    WHERE origin_day=? AND origin_version=?""",
                    (datetime.now().isoformat(), origin_day, version),
                )

    def latest_forecast(self):
        with self.connection() as db:
            close = db.execute("SELECT day,version,status FROM day_closes ORDER BY day DESC LIMIT 1").fetchone()
            if close is None or close["status"] != "closed":
                return {"origin_day": None, "products": [], "job": None}
            job = _dict(db.execute(
                "SELECT * FROM forecast_jobs WHERE origin_day=? AND origin_version=?",
                (close["day"], close["version"]),
            ).fetchone())
            checks = [_dict(row) for row in db.execute(
                """SELECT c.*,p.sku,p.name,p.unit,p.stock FROM forecast_checks c
                JOIN products p ON p.id=c.product_id
                WHERE c.origin_day=? AND c.origin_version=? ORDER BY p.name""",
                (close["day"], close["version"]),
            )]
            for check in checks:
                check["daily"] = [_dict(row) for row in db.execute(
                    """SELECT target_day,units FROM forecasts
                    WHERE product_id=? AND origin_day=? AND origin_version=?
                    ORDER BY target_day""",
                    (check["product_id"], close["day"], close["version"]),
                )]
        return {"origin_day": close["day"], "version": close["version"],
                "job": job, "products": checks}

    def to_buy(self):
        with self.connection() as db:
            return [_dict(row) for row in db.execute(
                """SELECT b.product_id,p.sku,p.name,p.unit,b.quantity,b.needed_by_days,b.updated_at
                FROM to_buy b JOIN products p ON p.id=b.product_id ORDER BY p.name"""
            )]

    def save_to_buy(self, payload):
        product_id = _whole(payload.get("product_id"), "Product ID", allow_zero=False)
        quantity = float(_positive(payload.get("quantity"), "Quantity"))
        days = _whole(payload.get("needed_by_days", 7), "Needed by days")
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM products WHERE id=? AND active=1", (product_id,)).fetchone():
                raise ValueError("Choose a catalogue product.")
            db.execute(
                """INSERT INTO to_buy VALUES (?,?,?,?) ON CONFLICT(product_id)
                DO UPDATE SET quantity=excluded.quantity,needed_by_days=excluded.needed_by_days,
                updated_at=excluded.updated_at""",
                (product_id, quantity, days, datetime.now().isoformat()),
            )
        return self.to_buy()

    def remove_to_buy(self, product_id):
        with self.connection() as db:
            db.execute("DELETE FROM to_buy WHERE product_id=?", (product_id,))
        return self.to_buy()

    def add_feedback(self, payload, *, source):
        from src.opportunities.feedback import CATEGORIES, _infer_category

        if source not in {"customer", "owner"}:
            raise ValueError("Feedback source is invalid.")
        day = _day(payload.get("day"))
        category = str(payload.get("category", "")).strip().lower()
        product_name = str(payload.get("product_name", "")).strip()[:100]
        note = str(payload.get("note", "")).strip()
        count = _whole(payload.get("count", 1), "Reported count", allow_zero=False)
        if not note or len(note) > 1000:
            raise ValueError("Enter a note of at most 1,000 characters.")
        if not category:
            category = _infer_category(note, source)
        if category not in CATEGORIES:
            raise ValueError("Choose a supported feedback category.")
        if category == "new_product_idea" and source != "owner":
            raise ValueError("Only the owner can label a new product idea.")
        if category == "product_request" and source != "customer":
            raise ValueError("Product requests must come from customers.")
        if category not in {"service", "facility_idea", "review"} and not product_name:
            raise ValueError("Name the product mentioned in this note.")
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO feedback(day,source,category,product_name,note,reported_count) VALUES (?,?,?,?,?,?)",
                (day, source, category, product_name, note, count),
            )
        return {"id": cursor.lastrowid, "day": day}

    def feedback(self):
        with self.connection() as db:
            return [_dict(row) for row in db.execute("SELECT * FROM feedback ORDER BY day DESC,id DESC")]

    def opportunities(self, *, as_of):
        from src.opportunities.feedback import analyze_feedback
        from src.opportunities.rank import rank_opportunities

        catalogue = [
            {"store_nbr": 1, "product_name": row["name"], "aliases": []}
            for row in self.products()
        ]
        if not catalogue:
            return {"ideas": [], "store_actions": [], "message": "Add products to the catalogue first."}
        entries = [
            {"store_nbr": 1, "date": date.fromisoformat(row["day"]),
             "source": row["source"], "category": row["category"],
             "product_name": row["product_name"], "note": row["note"],
             "count": row["reported_count"]}
            for row in self.feedback()
        ]
        candidates, actions = analyze_feedback(entries, catalogue, store_nbr=1, as_of=as_of)
        ideas, _ = rank_opportunities(candidates, catalogue, store_nbr=1, as_of=as_of)
        return {"ideas": ideas, "store_actions": actions, "message": ""}

    def save_offer(self, payload):
        from src.purchase.compare import supplier_offer

        product = self.product(_whole(payload.get("product_id"), "Product ID", allow_zero=False))
        currency = self.settings()["currency"]
        if not currency:
            raise ValueError("Set the shop currency before adding offers.")
        offer = supplier_offer(
            supplier=payload.get("supplier"), product_key=product["sku"],
            unit=product["unit"], currency=currency,
            pack_units=payload.get("pack_units"), pack_price=payload.get("pack_price"),
            minimum_order_units=payload.get("minimum_order_units"),
            available_units=payload.get("available_units"),
            delivery_days=(None if payload.get("delivery_days") in (None, "")
                           else _whole(payload["delivery_days"], "Delivery days")),
            delivery_fee=payload.get("delivery_fee"),
            channel=payload.get("channel", "owner_quote"),
            source_url=payload.get("source_url") or None,
        )
        with self.connection() as db:
            cursor = db.execute(
                """INSERT INTO offers(product_id,supplier,channel,source_url,currency,
                pack_units,pack_price,minimum_order_units,available_units,delivery_days,
                delivery_fee,price_status,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (product["id"], offer["supplier"], offer["channel"], offer["source_url"],
                 currency, float(offer["pack_units"]), float(offer["pack_price"]),
                 None if offer["minimum_order_units"] is None else float(offer["minimum_order_units"]),
                 None if offer["available_units"] is None else float(offer["available_units"]),
                 offer["delivery_days"],
                 None if offer["delivery_fee"] is None else float(offer["delivery_fee"]),
                 "owner_entered", datetime.now().isoformat()),
            )
        return {"id": cursor.lastrowid}

    def offers(self):
        with self.connection() as db:
            return [_dict(row) for row in db.execute(
                """SELECT o.*,p.sku,p.name,p.unit FROM offers o
                JOIN products p ON p.id=o.product_id ORDER BY o.id DESC"""
            )]

    def save_web_link(self, payload):
        from src.purchase.web_prices import _validate_url

        product_id = _whole(payload.get("product_id"), "Product ID", allow_zero=False)
        self.product(product_id)
        site_name = str(payload.get("site_name", "")).strip()
        approved_host = str(payload.get("approved_host", "")).strip().lower()
        sku = str(payload.get("expected_sku", "")).strip()
        url = str(payload.get("url", "")).strip()
        mode = str(payload.get("mode", "online_order")).strip()
        if not site_name or not approved_host or not sku or mode not in {"online_order", "offline_reference"}:
            raise ValueError("Enter the trusted site, exact SKU, and route type.")
        _validate_url(url, approved_host)
        match = payload.get("owner_match_confirmed") is True
        pack = payload.get("pack_units")
        minimum = payload.get("minimum_order_units")
        available = payload.get("available_units")
        delivery = payload.get("delivery_days")
        fee = payload.get("delivery_fee")
        pack = None if pack in (None, "") else float(_positive(pack, "Pack units"))
        minimum = None if minimum in (None, "") else float(_positive(minimum, "Minimum order", allow_zero=True))
        available = None if available in (None, "") else float(_positive(available, "Available units", allow_zero=True))
        delivery = None if delivery in (None, "") else _whole(delivery, "Delivery days")
        fee = None if fee in (None, "") else float(_positive(fee, "Delivery fee", allow_zero=True))
        with self.connection() as db:
            cursor = db.execute(
                """INSERT INTO web_links(product_id,site_name,approved_host,expected_sku,url,mode,
                owner_match_confirmed,pack_units,minimum_order_units,available_units,
                delivery_days,delivery_fee) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (product_id, site_name, approved_host, sku, url, mode, int(match),
                 pack, minimum, available, delivery, fee),
            )
        return {"id": cursor.lastrowid}

    def web_links(self):
        with self.connection() as db:
            return [_dict(row) for row in db.execute(
                """SELECT w.*,p.name AS product_name,p.sku AS product_sku FROM web_links w
                JOIN products p ON p.id=w.product_id ORDER BY w.id DESC"""
            )]

    def compare_to_buy(self, *, observer=None):
        from src.purchase.basket import compare_basket
        from src.purchase.compare import supplier_offer
        from src.purchase.web_offers import confirmed_web_offer
        from src.purchase.web_prices import observe_product

        observer = observer or observe_product
        basket = self.to_buy()
        if not basket:
            raise ValueError("Add a product to To-buy before comparing prices.")
        currency = self.settings()["currency"]
        if not currency:
            raise ValueError("Set the shop currency before comparing prices.")
        offers = [
            supplier_offer(
                supplier=row["supplier"], product_key=row["sku"], unit=row["unit"],
                currency=row["currency"], pack_units=row["pack_units"],
                pack_price=row["pack_price"], minimum_order_units=row["minimum_order_units"],
                available_units=row["available_units"], delivery_days=row["delivery_days"],
                delivery_fee=row["delivery_fee"], channel=row["channel"],
                source_url=row["source_url"], price_status=row["price_status"],
            )
            for row in self.offers()
        ]
        observations = []
        basket_ids = {row["product_id"] for row in basket}
        links = [row for row in self.web_links() if row["product_id"] in basket_ids][:20]
        for link in links:
            try:
                observed = observer(
                    link["url"], approved_host=link["approved_host"],
                    expected_sku=link["expected_sku"], mode=link["mode"],
                )
                status = observed["status"]
                error = ""
            except Exception as problem:
                observed = {}
                status = "unavailable"
                error = str(problem)[:200]
            with self.connection() as db:
                db.execute(
                    """UPDATE web_links SET observed_name=?,observed_price=?,observed_currency=?,
                    checked_at=?,status=?,error=? WHERE id=?""",
                    (observed.get("name"), observed.get("price"), observed.get("currency"),
                     observed.get("checked_at"), status, error, link["id"]),
                )
            observations.append({
                "product_name": link["product_name"], "site_name": link["site_name"],
                "url": link["url"], "status": status, "price": observed.get("price"),
                "currency": observed.get("currency"), "checked_at": observed.get("checked_at"),
                "error": error,
            })
            if status == "observed" and link["owner_match_confirmed"]:
                try:
                    product = self.product(link["product_id"])
                    offers.append(confirmed_web_offer(
                        {**observed, "site_name": link["site_name"],
                         "expected_sku": link["expected_sku"], "mode": link["mode"],
                         "owner_match_confirmed": True},
                        {"supplier": link["site_name"], "expected_sku": link["expected_sku"],
                         "product_key": product["sku"], "unit": product["unit"],
                         "pack_units": link["pack_units"],
                         "minimum_order_units": link["minimum_order_units"],
                         "available_units": link["available_units"],
                         "delivery_days": link["delivery_days"],
                         "delivery_fee": link["delivery_fee"]},
                    ))
                except ValueError:
                    pass  # The observation stays visible but cannot be a purchasable offer.
        orders = [
            {"product_key": row["sku"], "unit": row["unit"],
             "required_units": row["quantity"], "needed_by_days": row["needed_by_days"]}
            for row in basket
        ]
        result = compare_basket(orders, offers, currency=currency)
        return {"comparison": result, "observations": observations}
