"""Filter and explain owner-entered product ideas for one store."""

import argparse
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from src.opportunities.candidates import owner_candidate


OUTPUT_FIELDS = (
    "review_order", "store_nbr", "product_name", "rule_score",
    "signal_count", "reason", "source", "as_of",
)


def normalize_name(name):
    """Match case, spaces, and punctuation; do not guess product synonyms."""
    return " ".join(re.findall(r"\w+", name.casefold()))


def _as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError("as_of must be YYYY-MM-DD.") from error


def rank_opportunities(candidates, catalogue, *, store_nbr, as_of):
    """Return suggestions and counts of excluded or deferred ideas."""
    today = _as_date(as_of)
    if isinstance(store_nbr, bool) or not isinstance(store_nbr, int) or store_nbr < 1:
        raise ValueError("store_nbr must be a positive number.")
    stocked = set()
    for product in catalogue:
        if product["store_nbr"] != store_nbr:
            continue
        stocked.add(normalize_name(product["product_name"]))
        for alias in product.get("aliases", ()):
            stocked.add(normalize_name(alias))
    if not stocked:
        raise ValueError(f"Store {store_nbr} needs a nonempty owner catalogue.")

    grouped = defaultdict(list)
    counts = {"already_stocked": 0, "past_event": 0, "later_event": 0}
    for idea in candidates:
        if idea["store_nbr"] != store_nbr:
            continue
        key = normalize_name(idea["product_name"])
        if key in stocked:
            counts["already_stocked"] += 1
            continue
        kind = idea["signal_type"]
        if kind == "local_event":
            days_away = (date.fromisoformat(idea["event_date"]) - today).days
            if days_away < 0:
                counts["past_event"] += 1
                continue
            if days_away > 30:
                counts["later_event"] += 1
                continue
            points = 5 if days_away <= 7 else 4
            detail = f"Local event on {idea['event_date']}: {idea['evidence']}"
        elif kind == "customer_request":
            requests = idea["request_count"]
            points = 4 + min(requests, 3) if requests is not None else 4
            count_text = f" ({requests} reported)" if requests is not None else ""
            detail = f"Customer request{count_text}: {idea['evidence']}"
        elif kind == "seasonal_need":
            points = 3
            detail = f"Seasonal need: {idea['evidence']}"
        elif kind == "owner_observation":
            points = 2
            detail = f"Owner observation: {idea['evidence']}"
        else:
            raise ValueError(f"Unsupported signal type: {kind}")
        grouped[key].append((idea, points, detail))

    suggestions = []
    for signals in grouped.values():
        kinds = {idea["signal_type"] for idea, _, _ in signals}
        corroboration = min(len(kinds) - 1, 2)
        score = max(points for _, points, _ in signals) + corroboration
        reasons = list(dict.fromkeys(detail for _, _, detail in signals))
        if corroboration:
            word = "point" if corroboration == 1 else "points"
            reasons.append(f"{corroboration} extra {word} for distinct supporting signal types")
        suggestions.append({
            "store_nbr": store_nbr,
            "product_name": signals[0][0]["product_name"],
            "rule_score": score,
            "signal_count": len(signals),
            "reason": " | ".join(reasons),
            "source": "owner_entered",
            "as_of": today.isoformat(),
        })
    suggestions.sort(key=lambda row: (-row["rule_score"], normalize_name(row["product_name"])))
    for index, suggestion in enumerate(suggestions, 1):
        suggestion["review_order"] = index
    return suggestions, counts


def _read_rows(path, required):
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing columns in {path}: {', '.join(sorted(required))}")
        return list(reader)


def read_candidates(path):
    rows = _read_rows(path, {"store_nbr", "product_name", "signal_type", "evidence"})
    result = []
    for line, row in enumerate(rows, 2):
        try:
            count = (row.get("request_count") or "").strip()
            result.append(owner_candidate(
                store_nbr=int(row["store_nbr"]),
                product_name=row["product_name"],
                signal_type=row["signal_type"],
                evidence=row["evidence"],
                event_date=row.get("event_date") or None,
                request_count=int(count) if count else None,
            ))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Candidate row {line}: {error}") from error
    return result


def read_catalogue(path):
    rows = _read_rows(path, {"store_nbr", "product_name"})
    result = []
    for line, row in enumerate(rows, 2):
        try:
            store = int(row["store_nbr"])
            name = row["product_name"].strip()
            if store < 1 or not name or not normalize_name(name):
                raise ValueError("store and product_name must be filled in.")
            aliases = [alias.strip() for alias in (row.get("aliases") or "").split(";") if alias.strip()]
            result.append({"store_nbr": store, "product_name": name, "aliases": aliases})
        except (TypeError, ValueError) as error:
            raise ValueError(f"Catalogue row {line}: {error}") from error
    return result


def run(candidates_file, catalogue_file, output_file, *, store_nbr, as_of):
    candidates = read_candidates(candidates_file)
    catalogue = read_catalogue(catalogue_file)
    suggestions, counts = rank_opportunities(
        candidates, catalogue, store_nbr=store_nbr, as_of=as_of
    )
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(suggestions)
    temporary.replace(output)
    print(f"Store {store_nbr}: {len(suggestions)} ideas to review")
    print(f"Already stocked: {counts['already_stocked']}; past events: {counts['past_event']}; later events: {counts['later_event']}")
    for item in suggestions[:5]:
        print(f"  {item['review_order']}. {item['product_name']} (rule score {item['rule_score']}): {item['reason']}")
    print("Rule scores organize owner ideas; they are not demand forecasts or profit estimates.")
    print(f"Review file: {output}")
    return suggestions, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--store", type=int, required=True)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.candidates, args.catalogue, args.output, store_nbr=args.store, as_of=args.as_of)


if __name__ == "__main__":
    main()
