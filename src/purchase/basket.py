"""Find the lowest delivered total across a small confirmed product basket."""

from decimal import Decimal
from itertools import product

from src.purchase.compare import compare_offers


def compare_basket(orders, offers, *, currency, max_combinations=100_000):
    """Charge each chosen supplier's fixed delivery fee once per basket.

    Every offer for one supplier must state the same fixed fee. Unknown,
    unmatched, or reference-only quotes are never used as order routes.
    """
    requested = list(orders)
    if not requested or len({order["product_key"] for order in requested}) != len(requested):
        raise ValueError("Basket needs unique products and at least one order.")
    offers = list(offers)
    options = []
    uncovered = []
    details = {}
    fees = {}
    for order in requested:
        key = order["product_key"]
        comparison = compare_offers(
            offers, product_key=key, unit=order["unit"], currency=currency,
            required_units=order["required_units"], needed_by_days=order["needed_by_days"],
        )
        details[key] = comparison
        eligible = [offer for offer in comparison["offers"] if offer["status"] == "eligible"]
        if not eligible:
            uncovered.append(key)
        else:
            for offer in eligible:
                supplier = offer["supplier"]
                fee = Decimal(str(offer["delivery_fee"]))
                if supplier in fees and fees[supplier] != fee:
                    raise ValueError(f"Supplier {supplier} has inconsistent fixed delivery fees.")
                fees[supplier] = fee
            options.append(eligible)
    if uncovered:
        return {"status": "incomplete", "uncovered_products": uncovered,
                "chosen_offers": [], "supplier_totals": {}, "basket_total": None,
                "comparisons": details}
    combinations = 1
    for eligible in options:
        combinations *= len(eligible)
        if combinations > max_combinations:
            raise ValueError("Too many supplier combinations for this small-basket comparison.")
    best = None
    for selected in product(*options):
        suppliers = {offer["supplier"] for offer in selected}
        goods = sum((Decimal(str(offer["goods_cost"])) for offer in selected), Decimal(0))
        total = goods + sum((fees[supplier] for supplier in suppliers), Decimal(0))
        ordering = (total, len(suppliers), tuple(offer["supplier"] for offer in selected))
        if best is None or ordering < best[0]:
            best = (ordering, selected)
    _, selected = best
    totals = {}
    for offer in selected:
        supplier = offer["supplier"]
        group = totals.setdefault(supplier, {"goods_cost": 0.0, "delivery_fee": float(fees[supplier]),
                                             "products": []})
        group["goods_cost"] += offer["goods_cost"]
        group["products"].append(offer["product_key"])
    for group in totals.values():
        group["delivered_total"] = round(group["goods_cost"] + group["delivery_fee"], 2)
    return {"status": "ready", "uncovered_products": [],
            "chosen_offers": list(selected), "supplier_totals": totals,
            "basket_total": float(best[0][0]), "comparisons": details}
