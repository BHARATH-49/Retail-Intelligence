"""Compare supplier packs for a confirmed product and restocking quantity."""

import csv
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path


OFFER_FIELDS = (
    "supplier", "product_key", "unit", "currency", "pack_units",
    "pack_price", "minimum_order_units", "available_units",
    "delivery_days", "delivery_fee",
)


def _amount(value, name, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as error:
        raise ValueError(f"{name} must be a number.") from error
    if not result.is_finite() or result < 0 or (positive and result == 0):
        limit = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be a finite {limit} number.")
    return result


def _whole_days(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative whole number of days.")
    return value


def supplier_offer(
    *, supplier, product_key, unit, currency, pack_units, pack_price,
    minimum_order_units=None, available_units=None, delivery_days=None,
    delivery_fee=None, channel="owner_quote", source_url=None,
    price_status="owner_entered",
):
    """Validate facts supplied by an owner; None means a term is unknown."""
    for label, value in (
        ("supplier", supplier), ("product_key", product_key),
        ("unit", unit), ("currency", currency),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be filled in.")
    if channel not in {"online_order", "offline_reference", "owner_quote"}:
        raise ValueError("channel must name a supported purchasing route.")
    if price_status not in {"owner_entered", "live_observed"}:
        raise ValueError("price_status must identify where the price came from.")
    return {
        "supplier": supplier.strip(),
        "product_key": product_key.strip(),
        "unit": unit.strip(),
        "currency": currency.strip().upper(),
        "pack_units": _amount(pack_units, "pack_units", positive=True),
        "pack_price": _amount(pack_price, "pack_price"),
        "minimum_order_units": None if minimum_order_units is None else _amount(minimum_order_units, "minimum_order_units"),
        "available_units": None if available_units is None else _amount(available_units, "available_units"),
        "delivery_days": None if delivery_days is None else _whole_days(delivery_days, "delivery_days"),
        "delivery_fee": None if delivery_fee is None else _amount(delivery_fee, "delivery_fee"),
        "channel": channel,
        "source_url": source_url,
        "price_status": price_status,
        "source": "owner_entered" if price_status == "owner_entered" else price_status,
    }


def compare_offers(offers, *, product_key, unit, currency, required_units, needed_by_days):
    """Recommend the least total-cost confirmed offer that can arrive on time."""
    required = _amount(required_units, "required_units", positive=True)
    deadline = _whole_days(needed_by_days, "needed_by_days")
    if not all(isinstance(value, str) and value.strip() for value in (product_key, unit, currency)):
        raise ValueError("product_key, unit, and currency must be confirmed.")
    checked = []
    for offer in offers:
        if offer["product_key"] != product_key:
            continue
        status = "eligible"
        if offer["unit"] != unit or offer["currency"] != currency.upper():
            status = "unit_or_currency_mismatch"
        minimum = offer["minimum_order_units"]
        fee = offer["delivery_fee"]
        available = offer["available_units"]
        delivery = offer["delivery_days"]
        if status == "eligible" and offer["channel"] == "offline_reference":
            status = "reference_only"
        if status == "eligible" and any(value is None for value in (minimum, fee, available, delivery)):
            status = "terms_unknown"
        packs = max(1, int((max(required, minimum or 0) / offer["pack_units"]).to_integral_value(rounding=ROUND_CEILING)))
        order_units = packs * offer["pack_units"]
        goods_cost = packs * offer["pack_price"]
        total = None if fee is None else goods_cost + fee
        if status == "eligible" and available < order_units:
            status = "not_enough_available"
        if status == "eligible" and delivery > deadline:
            status = "arrives_late"
        checked.append({
            "supplier": offer["supplier"],
            "product_key": product_key,
            "unit": offer["unit"],
            "currency": offer["currency"],
            "status": status,
            "packs": packs,
            "pack_units": float(offer["pack_units"]),
            "order_units": float(order_units),
            "extra_units": float(order_units - required),
            "pack_unit_price": float(offer["pack_price"] / offer["pack_units"]),
            "goods_cost": float(goods_cost),
            "delivery_fee": None if fee is None else float(fee),
            "total_delivered_cost": None if total is None else float(total),
            "delivery_days": delivery,
            "available_units": None if available is None else float(available),
            "channel": offer["channel"],
            "source_url": offer["source_url"],
            "price_status": offer["price_status"],
            "source": offer["source"],
        })
    eligible = [offer for offer in checked if offer["status"] == "eligible"]
    eligible.sort(key=lambda offer: (
        Decimal(str(offer["total_delivered_cost"])),
        offer["delivery_days"], offer["extra_units"], offer["supplier"].casefold(),
    ))
    recommended = eligible[0]["supplier"] if eligible else None
    checked.sort(key=lambda offer: (offer["status"] != "eligible", offer["supplier"].casefold()))
    return {"required_units": float(required), "unit": unit, "currency": currency.upper(),
            "needed_by_days": deadline, "offers": checked,
            "recommended_supplier": recommended}


def read_offers(path):
    """Read a small owner-entered CSV of comparable supplier quotes."""
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not set(OFFER_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Supplier CSV needs: {', '.join(OFFER_FIELDS)}")
        result = []
        for line, row in enumerate(reader, 2):
            try:
                optional = lambda key: (row.get(key) or "").strip() or None
                result.append(supplier_offer(
                    supplier=row["supplier"], product_key=row["product_key"],
                    unit=row["unit"], currency=row["currency"],
                    pack_units=row["pack_units"], pack_price=row["pack_price"],
                    minimum_order_units=optional("minimum_order_units"),
                    available_units=optional("available_units"),
                    delivery_days=None if optional("delivery_days") is None else int(optional("delivery_days")),
                    delivery_fee=optional("delivery_fee"),
                    channel=optional("channel") or "owner_quote",
                    source_url=optional("source_url"),
                    price_status=optional("price_status") or "owner_entered",
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"Supplier row {line}: {error}") from error
    return result
