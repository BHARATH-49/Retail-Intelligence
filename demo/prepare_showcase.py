"""Prepare an isolated 6-Seven replay from the viewer's own Favorita files.

Run from the repository root: python -m demo.prepare_showcase
The generated database and selection record stay under ignored data/app/demo/.
"""

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from app.shop import ShopStore


ROOT = Path(__file__).resolve().parents[1]
DAY = date(2017, 8, 15)
START = DAY - timedelta(days=179)
OUTPUT = ROOT / "data" / "app" / "demo" / "shop.sqlite3"
NAMES = Path(__file__).with_name("catalogue_names.json")
DISCLOSURE = (
    "6-Seven is an unofficial name for a replay of Favorita Store 44. "
    "Item names, stock, bills, selling prices, supplier quotes and feedback are "
    "illustrative; dated sales quantities come from the viewer's own Favorita "
    "download. Missing sales rows are assumed zero, not confirmed zero demand. "
    "This is a prototype, not a live shop."
)


def read_families(items_file):
    return {
        int(row["item_nbr"]): row["family"]
        for row in csv.DictReader(items_file.open(newline="", encoding="utf-8"))
    }


def read_store_sales(train_file, family_by_item, names):
    """Calculate full-history eligibility and replay sales in one raw-data scan."""
    needed = Counter(product["family"] for product in names)
    candidates = {}
    recent = defaultdict(dict)
    clipped_negatives = 0
    with train_file.open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source)
        header = next(reader)
        required = {"date", "store_nbr", "item_nbr", "unit_sales"}
        if not required.issubset(header):
            raise ValueError(f"Training CSV is missing {required - set(header)}")
        column = {name: header.index(name) for name in required}
        for row in reader:
            if row[column["store_nbr"]] != "44":
                continue
            item = int(row[column["item_nbr"]])
            family = family_by_item.get(item)
            if family not in needed:
                continue
            day = row[column["date"]]
            info = candidates.get(item)
            if info is None:
                info = {
                    "family": family, "first_date": day, "last_date": day,
                    "full_recorded_rows": 0,
                }
                candidates[item] = info
            info["first_date"] = min(info["first_date"], day)
            info["last_date"] = max(info["last_date"], day)
            info["full_recorded_rows"] += 1
            if day < START.isoformat() or day > DAY.isoformat():
                continue
            units = float(row[column["unit_sales"]])
            if not math.isfinite(units):
                raise ValueError(f"Non-finite sales for item {item} on {day}")
            if day in recent[item]:
                raise ValueError(f"Duplicate Store 44 sales row for item {item} on {day}")
            if units < 0:
                clipped_negatives += 1
            recent[item][day] = max(0.0, units)
    candidates = {
        item: info for item, info in candidates.items()
        if info["first_date"] <= START.isoformat()
        and info["last_date"] == DAY.isoformat()
    }
    counts = Counter(row["family"] for row in candidates.values())
    missing = {family: count for family, count in needed.items() if counts[family] < count}
    if missing:
        raise ValueError(f"Not enough recent Store 44 items for these families: {missing}")
    return candidates, recent, clipped_negatives


def choose_items(names, candidates, recent):
    by_family = defaultdict(list)
    last_120 = (DAY - timedelta(days=119)).isoformat()
    for item, info in candidates.items():
        sales = recent.get(item, {})
        if DAY.isoformat() not in sales:
            continue
        # These illustrative catalogue units are countable packs, bottles and
        # cans; a fractional Favorita series would make a bill misleading.
        if any(not units.is_integer() for units in sales.values()):
            continue
        by_family[info["family"]].append((
            -len(sales),
            -sum(day >= last_120 for day in sales),
            -info["full_recorded_rows"],
            item,
        ))
    for family in by_family:
        by_family[family].sort()
    index = Counter()
    chosen = []
    for label in names:
        family = label["family"]
        position = index[family]
        if position >= len(by_family[family]):
            raise ValueError(f"Too few eligible {family} items with final-day sales")
        item = by_family[family][position][-1]
        index[family] += 1
        chosen.append((item, label, candidates[item], recent[item]))
    return chosen


def demo_price(label):
    """Stable illustrative USD prices, not inferred from Favorita."""
    base = {
        "BEVERAGES": 1.25, "DAIRY": 2.75, "GROCERY I": 2.20,
        "BREAD/BAKERY": 2.10, "CLEANING": 5.50,
    }[label["family"]]
    return base


def prepare_database(output, chosen):
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(
            f"{output} already exists. The showcase never replaces an existing database. "
            "Choose an empty location or move the old demo aside yourself."
        )
    shop = ShopStore(output)
    shop.save_settings({"shop_name": "6-Seven", "currency": "USD"})
    with shop.connection() as db:
        db.executemany(
            "INSERT INTO settings(key,value) VALUES (?,?)",
            [("demo_day", DAY.isoformat()), ("demo_disclosure", DISCLOSURE)],
        )
    product_ids = {}
    for item, label, _, sales in chosen:
        last_week = [
            sales.get((DAY - timedelta(days=offset)).isoformat(), 0.0)
            for offset in range(1, 8)
        ]
        final_units = sales.get(DAY.isoformat(), 0.0)
        # Invent enough stock to cover the example bills and leave a small balance.
        opening = final_units + max(3, math.ceil(sum(last_week) / 7 * 3))
        product = shop.save_product({
            "sku": f"F44-{item}",
            "name": label["display_name"],
            "unit": label["sale_unit"],
            "first_stocked_on": START.isoformat(),
            "opening_stock": opening,
            "unit_price": demo_price(label),
            "lead_days": 2,
            "order_increment": label["supplier_pack_units"],
            "extra_cover_days": 1,
            "shelf_life_days": 5 if label["family"] in {"DAIRY", "BREAD/BAKERY"} else None,
        })
        product_ids[item] = product["id"]

    imported = []
    for item, _, _, sales in chosen:
        imported.extend(
            (product_ids[item], day, units)
            for day, units in sales.items() if day < DAY.isoformat()
        )
    previous_days = [
        (START + timedelta(days=offset)).isoformat() for offset in range(179)
    ]
    with shop.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.executemany(
            "INSERT INTO imported_sales(product_id,day,units) VALUES (?,?,?)", imported
        )
        db.executemany(
            "INSERT INTO day_closes(day,status,version,bill_count,sales_cents,closed_at) "
            "VALUES (?,'closed',1,0,0,NULL)",
            [(day,) for day in previous_days],
        )

    # Simulated bills are the only sales source for 15 August. Their quantities
    # exactly equal the recorded Store 44 totals for selected items.
    bills = [[], [], []]
    for position, (item, _, _, sales) in enumerate(chosen):
        units = sales.get(DAY.isoformat(), 0.0)
        if units > 0:
            bills[position % len(bills)].append({
                "product_id": product_ids[item], "quantity": units,
            })
    for position, lines in enumerate(bills, 1):
        if lines:
            shop.complete_bill({
                "receipt_id": f"DEMO-20170815-{position:02d}",
                "day": DAY.isoformat(), "lines": lines,
            })
    for item, label, _, _ in chosen:
        pack = label["supplier_pack_units"]
        for supplier, channel, factor, fee, url in (
            ("Eureka (illustrative quote)", "online_order", 0.78, 4.00, label["source_page"]),
            ("Local wholesaler (illustrative quote)", "owner_quote", 0.84, 0.00, None),
        ):
            shop.save_offer({
                "product_id": product_ids[item],
                "supplier": supplier,
                "channel": channel,
                "source_url": url,
                "pack_units": pack,
                "pack_price": round(demo_price(label) * pack * factor, 2),
                "minimum_order_units": pack,
                "available_units": max(100, pack * 20),
                "delivery_days": 2 if url else 1,
                "delivery_fee": fee,
            })
    shop.validate_ledger()
    return {
        "shop": "6-Seven (unofficial Store 44 alias)",
        "replay_day": DAY.isoformat(),
        "history_start": START.isoformat(),
        "selected_products": len(chosen),
        "historical_closed_days": len(previous_days),
        "imported_recorded_rows": len(imported),
        "missing_product_days_assumed_zero": len(chosen) * len(previous_days) - len(imported),
        "example_bills": sum(bool(lines) for lines in bills),
        "illustrative_supplier_quotes": len(chosen) * 2,
        "final_day_still_open": True,
        "selection_rule": (
            "Within each illustrative family: first recorded by history start, "
            "recorded on final day, whole-unit sales throughout the replay, "
            "then most recorded days in the last 180, "
            "last 120, and full history. Model validation results are not used."
        ),
        "products": [
            {
                "anonymous_favorita_item_nbr": item,
                "illustrative_display_name": label["display_name"],
                "family": label["family"],
                "recorded_days_in_180": len(sales),
                "assumed_zero_days_in_180": 180 - len(sales),
                "recorded_rows_full_history": info["full_recorded_rows"],
                "recorded_final_day_units": sales[DAY.isoformat()],
            }
            for item, label, info, sales in chosen
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=ROOT / "data/raw/train.csv")
    parser.add_argument("--items", type=Path, default=ROOT / "data/raw/items.csv")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    for path in (args.train, args.items, NAMES):
        if not path.is_file():
            parser.error(f"Missing {path}. Obtain your own Favorita download first.")
    if args.output.exists():
        parser.error(f"{args.output} already exists; move it aside before preparing a new demo.")
    labels = json.loads(NAMES.read_text(encoding="utf-8"))["products"]
    print("Scanning Store 44 history to select recent, long-running items...", flush=True)
    candidates, recent, clipped = read_store_sales(
        args.train, read_families(args.items), labels
    )
    chosen = choose_items(labels, candidates, recent)
    summary = prepare_database(args.output, chosen)
    summary["negative_recorded_values_set_to_zero"] = clipped
    manifest = args.output.with_name("selection.json")
    manifest.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Selected {len(chosen)} products with recent history.")
    print(f"Example bills: {summary['example_bills']}; 15 August remains open.")
    print(f"Assumed-zero historical product-days: {summary['missing_product_days_assumed_zero']:,}")
    print(f"Demo database: {args.output}")
    print(f"Local selection record: {manifest}")


if __name__ == "__main__":
    main()
