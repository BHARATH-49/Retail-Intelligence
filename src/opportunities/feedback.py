"""Turn simple owner notes and customer feedback into reviewable actions."""

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from src.opportunities.candidates import owner_candidate
from src.opportunities.rank import normalize_name


CATEGORIES = {
    "product_request", "new_product_idea", "stockout", "quality", "service", "facility_idea", "review",
}


def _infer_category(note, source):
    """Use narrow, visible wording rules; leave ambiguous notes for review."""
    words = note.casefold()
    patterns = {
        "stockout": ("shelf empty", "out of stock", "sold out", "delivery arrives"),
        "quality": ("expired", "broken", "damaged", "bad quality"),
        "service": ("slow checkout", "queue", "long wait", "rude staff"),
        "facility_idea": ("add a table", "seating", "hot water", "cold water", "water dispenser"),
        "product_request": ("asked for", "asking for", "looking for", "wish you sold"),
        "new_product_idea": ("could stock", "should stock", "idea to add"),
    }
    matches = [category for category, phrases in patterns.items()
               if any(phrase in words for phrase in phrases)]
    if len(matches) != 1:
        return "review"
    category = matches[0]
    if category == "product_request" and source != "customer":
        return "new_product_idea" if source == "owner" else "review"
    if category == "new_product_idea" and source != "owner":
        return "review"
    return category


def read_feedback(path):
    """Keep original words; infer an obvious category when left blank."""
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {"store_nbr", "date", "source", "category", "product_name", "note", "count"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Feedback CSV is missing required columns.")
        result = []
        for line, row in enumerate(reader, 2):
            try:
                entry = {
                    "store_nbr": int(row["store_nbr"]),
                    "date": date.fromisoformat(row["date"]),
                    "source": row["source"].strip().lower(),
                    "category": row["category"].strip().lower(),
                    "product_name": row["product_name"].strip(),
                    "note": row["note"].strip(),
                    "count": int(row["count"]),
                }
                if entry["store_nbr"] < 1 or entry["source"] not in {"owner", "customer"}:
                    raise ValueError("store and source must be valid")
                if not entry["note"] or entry["count"] < 1:
                    raise ValueError("note and positive count are required")
                if not entry["category"]:
                    entry["category"] = _infer_category(entry["note"], entry["source"])
                if entry["category"] not in CATEGORIES:
                    raise ValueError("unsupported feedback category")
                if entry["category"] == "new_product_idea" and entry["source"] != "owner":
                    raise ValueError("new_product_idea must be owner-labelled")
                if entry["category"] == "product_request" and entry["source"] != "customer":
                    raise ValueError("product_request must be customer feedback")
                if entry["category"] not in {"service", "facility_idea", "review"} and not entry["product_name"]:
                    raise ValueError("product name is required for this category")
                result.append(entry)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Feedback row {line}: {error}") from error
    return result


def analyze_feedback(entries, catalogue, *, store_nbr, as_of):
    """Make new-product candidates and store-change review actions."""
    today = date.fromisoformat(as_of)
    stocked = set()
    for product in catalogue:
        if product["store_nbr"] == store_nbr:
            stocked.add(normalize_name(product["product_name"]))
            stocked.update(normalize_name(alias) for alias in product.get("aliases", ()))
    if not stocked:
        raise ValueError("Feedback analysis needs a nonempty store catalogue.")
    candidates = []
    grouped_actions = defaultdict(list)
    for entry in entries:
        if entry["store_nbr"] != store_nbr or entry["date"] > today:
            continue
        key = normalize_name(entry["product_name"])
        category = entry["category"]
        if category in {"product_request", "new_product_idea"} and key not in stocked:
            candidates.append(owner_candidate(
                store_nbr=store_nbr, product_name=entry["product_name"],
                signal_type="customer_request" if category == "product_request" else "owner_observation",
                evidence=entry["note"],
                request_count=entry["count"] if category == "product_request" else None,
            ))
        else:
            action = "availability" if category in {"stockout", "product_request", "new_product_idea"} else category
            grouped_actions[(action, key)].append(entry)
    actions = []
    labels = {
        "availability": "Review shelf availability and replenishment",
        "quality": "Review product quality with the owner",
        "service": "Review the store service process",
        "facility_idea": "Consider this store facility change",
        "review": "Review this note manually",
    }
    for (category, _), group in grouped_actions.items():
        count = sum(entry["count"] for entry in group)
        actions.append({
            "category": category,
            "product_name": group[0]["product_name"],
            "reported_count": count,
            "recommendation": labels[category],
            "reasons": " | ".join(dict.fromkeys(entry["note"] for entry in group)),
            "sources": ", ".join(sorted({entry["source"] for entry in group})),
        })
    actions.sort(key=lambda row: (-row["reported_count"], row["category"], row["product_name"]))
    return candidates, actions
