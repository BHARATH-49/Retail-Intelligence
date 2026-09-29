"""Local owner application with a separate historical research page."""

import csv
import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "data" / "processed"
VALIDATION_FILE = "recent_origin_check_2017.csv"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.inventory.restock import plan_restock
from app.shop import ShopStore
from app.forecast_worker import ForecastWorker
from app import owner_api

EXPERIMENT_FILES = {
    "store1-aug2017": ("Store 1 · August 2017", "linear_store1_aug2017.csv"),
    "store1-mar2017": ("Store 1 · March 2017", "linear_store1_20170308.csv"),
    "store2-aug2017": ("Store 2 · August 2017", "linear_store2_aug2017.csv"),
}


def average_error(rows, prediction_key):
    return sum(abs(row[prediction_key] - row["actual"]) for row in rows) / len(rows)


def load_experiments(results_dir=RESULTS_DIR):
    """Read the small saved comparison files; never load raw training data."""
    experiments = {}
    for experiment_id, (label, filename) in EXPERIMENT_FILES.items():
        source = Path(results_dir) / filename
        if not source.exists():
            raise FileNotFoundError(f"Missing saved experiment: {source}")
        products = defaultdict(list)
        with source.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            required = {
                "store_nbr", "item_nbr", "date", "linear_prediction",
                "four_week_prediction", "actual_unit_sales", "actual_row_was_missing",
            }
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"Missing columns in {source}")
            for record in reader:
                item = int(record["item_nbr"])
                products[item].append({
                    "date": record["date"],
                    "actual": float(record["actual_unit_sales"]),
                    "average": float(record["four_week_prediction"]),
                    "linear": float(record["linear_prediction"]),
                    "assumed_zero": record["actual_row_was_missing"] == "True",
                })
        if not products:
            raise ValueError(f"No predictions found in {source}")
        all_rows = []
        for item, rows in products.items():
            rows.sort(key=lambda row: row["date"])
            if len(rows) != 7 or len({row["date"] for row in rows}) != 7:
                raise ValueError(f"Expected seven unique dates for product {item} in {source}")
            all_rows.extend(rows)
        dates = sorted({row["date"] for row in all_rows})
        if len(dates) != 7:
            raise ValueError(f"Expected one seven-day test week in {source}")
        experiments[experiment_id] = {
            "id": experiment_id,
            "label": label,
            "store": int(experiment_id.split("-")[0].replace("store", "")),
            "start": dates[0],
            "end": dates[-1],
            "products": dict(products),
            "product_count": len(products),
            "prediction_count": len(all_rows),
            "assumed_zero_count": sum(row["assumed_zero"] for row in all_rows),
            "average_error": average_error(all_rows, "average"),
            "linear_error": average_error(all_rows, "linear"),
            "zero_error": sum(row["actual"] for row in all_rows) / len(all_rows),
        }
    return experiments


def load_future_forecasts(results_dir=RESULTS_DIR):
    """Read saved seven-day forecasts, never training data or arbitrary paths."""
    forecasts = {}
    for source in sorted(Path(results_dir).glob("forecast_store*_item*_*.csv")):
        with source.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            required = {
                "date", "store_nbr", "item_nbr", "forecast_units",
                "four_week_median_units", "model",
            }
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"Missing future forecast columns in {source}")
            rows = [{
                "date": record["date"],
                "store": int(record["store_nbr"]),
                "item": int(record["item_nbr"]),
                "forecast": float(record["forecast_units"]),
                "median": float(record["four_week_median_units"]),
                "model": record["model"],
            } for record in reader]
        if len(rows) != 7 or len({(row["store"], row["item"], row["model"]) for row in rows}) != 1:
            raise ValueError(f"Expected one store, item, model, and seven days in {source}")
        first = date.fromisoformat(rows[0]["date"])
        if [row["date"] for row in rows] != [
            (first + timedelta(days=offset)).isoformat() for offset in range(7)
        ]:
            raise ValueError(f"Expected seven consecutive forecast dates in {source}")
        if any(not (0 <= row["forecast"] < float("inf") and 0 <= row["median"] < float("inf")) for row in rows):
            raise ValueError(f"Expected finite, nonnegative forecasts in {source}")
        forecasts[source.stem] = {
            "id": source.stem,
            "store": rows[0]["store"],
            "item": rows[0]["item"],
            "start": rows[0]["date"],
            "end": rows[-1]["date"],
            "model": rows[0]["model"],
            "rows": rows,
        }
    return forecasts


def calculate_restock(payload, forecasts):
    forecast = forecasts.get(payload.get("forecast_id"))
    if forecast is None:
        raise ValueError("Choose a saved forecast.")
    plan = plan_restock(
        [row["forecast"] for row in forecast["rows"]],
        stock_on_hand=payload.get("stock_on_hand"),
        unit=payload.get("unit"),
        order_increment=payload.get("order_increment"),
        lead_days=payload.get("lead_days"),
        incoming_units=payload.get("incoming_units"),
        incoming_day=payload.get("incoming_day"),
        extra_cover_days=payload.get("extra_cover_days", 1),
        minimum_order_units=payload.get("minimum_order_units"),
        pack_multiple_units=payload.get("pack_multiple_units"),
        shelf_life_days=payload.get("shelf_life_days"),
    )
    first_short = plan["first_short_day_index"]
    return {
        "forecast_id": forecast["id"],
        "first_short_date": forecast["rows"][first_short]["date"] if first_short is not None else None,
        "plan": plan,
    }


def load_model_metrics(results_dir=RESULTS_DIR):
    """Summarize the matched later-week validation for the current model."""
    source = Path(results_dir) / VALIDATION_FILE
    if not source.exists():
        return None
    wanted = {
        "lightgbm_promotion_recent": "Provisional LightGBM",
        "four_week_median": "Four-week median reference",
    }
    groups = {method: [] for method in wanted}
    with source.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        required = {
            "start", "store", "method", "mae", "rmse", "predictions",
            "actual_units_total", "mean_shortfall_all_dates", "misses_over_20_units",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing model metric columns in {source}")
        for row in reader:
            if row["method"] in groups:
                groups[row["method"]].append(row)
    if any(not rows for rows in groups.values()):
        raise ValueError(f"Both V1 metric methods are required in {source}")
    identities = [
        {(row["start"], row["store"]) for row in rows}
        for rows in groups.values()
    ]
    if identities[0] != identities[1]:
        raise ValueError(f"Model metric windows must match in {source}")
    target_counts = [
        {(row["start"], row["store"]): int(row["predictions"]) for row in rows}
        for rows in groups.values()
    ]
    if target_counts[0] != target_counts[1]:
        raise ValueError(f"Model metric target counts must match in {source}")
    summaries = []
    for method, label in wanted.items():
        rows = groups[method]
        count = sum(int(row["predictions"]) for row in rows)
        error = sum(float(row["mae"]) * int(row["predictions"]) for row in rows)
        actual = sum(float(row["actual_units_total"]) for row in rows)
        rmse_squared = sum(float(row["rmse"]) ** 2 * int(row["predictions"]) for row in rows)
        summaries.append({
            "method": method,
            "label": label,
            "predictions": count,
            "mae": error / count,
            "wape": error / actual if actual > 0 else None,
            "rmse": math.sqrt(rmse_squared / count),
            "mean_shortfall": sum(
                float(row["mean_shortfall_all_dates"]) * int(row["predictions"])
                for row in rows
            ) / count,
            "misses_over_20_units": sum(int(row["misses_over_20_units"]) for row in rows),
        })
    return {"store_weeks": len(identities[0]), "methods": summaries}


class DashboardHandler(BaseHTTPRequestHandler):
    experiments = None
    forecasts = None
    model_metrics = None
    shop = None
    worker = None

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=200):
        self.send_bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_GET(self):
        request = urlparse(self.path)
        if request.path == "/healthz":
            try:
                with self.shop.connection() as db:
                    db.execute("SELECT 1").fetchone()
                if self.worker is not None and not self.worker.is_alive():
                    raise RuntimeError("Forecast worker stopped")
            except Exception:
                logging.exception("Application health check failed")
                self.send_json({"status": "unhealthy"}, 503)
            else:
                self.send_json({"status": "ok"})
            return
        if request.path.startswith("/api/shop/"):
            try:
                self.send_json(owner_api.read(request.path, parse_qs(request.query), self.shop))
            except KeyError:
                self.send_json({"error": "Unknown action"}, 404)
            except (ValueError, TypeError) as error:
                self.send_json({"error": str(error)}, 400)
            return
        if request.path == "/api/forecasts":
            self.send_json(list(self.forecasts.values()))
            return
        if request.path == "/api/model-metrics":
            self.send_json(self.model_metrics)
            return
        if request.path == "/api/experiments":
            self.send_json([
                {key: value for key, value in experiment.items() if key != "products"}
                for experiment in self.experiments.values()
            ])
            return
        if request.path == "/api/products":
            query = parse_qs(request.query)
            experiment = self.experiments.get(query.get("experiment", [""])[0])
            if experiment is None:
                self.send_json({"error": "Unknown experiment"}, 404)
                return
            self.send_json(sorted(experiment["products"]))
            return
        if request.path == "/api/product":
            query = parse_qs(request.query)
            experiment = self.experiments.get(query.get("experiment", [""])[0])
            if experiment is None:
                self.send_json({"error": "Unknown experiment"}, 404)
                return
            try:
                item = int(query.get("item", [""])[0])
            except ValueError:
                self.send_json({"error": "Invalid product number"}, 400)
                return
            rows = experiment["products"].get(item)
            if rows is None:
                self.send_json({"error": "Product not found"}, 404)
                return
            self.send_json({
                "item": item,
                "rows": rows,
                "average_error": average_error(rows, "average"),
                "linear_error": average_error(rows, "linear"),
                "assumed_zero_count": sum(row["assumed_zero"] for row in rows),
            })
            return

        pages = {
            "/": ("owner.html", "text/html; charset=utf-8"),
            "/research": ("index.html", "text/html; charset=utf-8"),
            "/feedback": ("feedback.html", "text/html; charset=utf-8"),
            "/owner.css": ("owner.css", "text/css; charset=utf-8"),
            "/owner.js": ("owner.js", "text/javascript; charset=utf-8"),
            "/feedback.js": ("feedback.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if request.path not in pages:
            self.send_bytes(b"Not found", "text/plain; charset=utf-8", 404)
            return
        filename, content_type = pages[request.path]
        self.send_bytes((APP_DIR / filename).read_bytes(), content_type)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/restock" and not path.startswith("/api/shop/"):
            self.send_json({"error": "Unknown action"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise ValueError("Expected a small application request.")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Send JSON application data.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected application input fields.")
            if path.startswith("/api/shop/"):
                try:
                    self.send_json(owner_api.write(path, payload, self.shop))
                except KeyError:
                    self.send_json({"error": "Unknown action"}, 404)
            else:
                self.send_json(calculate_restock(payload, self.forecasts))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="Local browser port (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: 127.0.0.1)")
    parser.add_argument("--db", type=Path, help="Optional separate shop database path")
    args = parser.parse_args()
    try:
        DashboardHandler.experiments = load_experiments()
        DashboardHandler.forecasts = load_future_forecasts()
        DashboardHandler.model_metrics = load_model_metrics()
    except (FileNotFoundError, ValueError) as error:
        print(f"Research results unavailable: {error}")
        DashboardHandler.experiments = {}
        DashboardHandler.forecasts = {}
        DashboardHandler.model_metrics = None
    DashboardHandler.shop = ShopStore(args.db) if args.db else ShopStore()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    worker = ForecastWorker(DashboardHandler.shop)
    worker.start()
    DashboardHandler.worker = worker
    print("Retail Intelligence owner application")
    print(f"Open http://127.0.0.1:{args.port} in your browser. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
        worker.stop()


if __name__ == "__main__":
    main()
