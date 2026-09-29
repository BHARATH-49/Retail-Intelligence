"""Turn a checked page price into an offer only after owner confirmation."""

from src.purchase.compare import supplier_offer


def confirmed_web_offer(observation, owner_terms):
    """Require a product match and current purchase terms before comparison."""
    if observation.get("status") != "observed":
        raise ValueError("A verified page price is required.")
    if observation.get("owner_match_confirmed") not in (True, "True"):
        raise ValueError("The owner must confirm the exact shop-product and pack match.")
    if observation.get("mode") != "online_order":
        raise ValueError("An offline reference is not an online order route.")
    if not observation.get("checked_at") or not observation.get("url"):
        raise ValueError("The price needs its source URL and check time.")
    if observation.get("site_name") != owner_terms.get("supplier"):
        raise ValueError("The confirmed supplier must match the observed site.")
    if observation.get("expected_sku") != owner_terms.get("expected_sku"):
        raise ValueError("The confirmed SKU must match the observed page.")
    required = (
        "product_key", "unit", "pack_units", "minimum_order_units",
        "available_units", "delivery_days", "delivery_fee",
    )
    if any(owner_terms.get(name) in (None, "") for name in required):
        raise ValueError("Pack, stock, minimum, and delivery terms must be confirmed.")
    return supplier_offer(
        supplier=owner_terms["supplier"],
        product_key=owner_terms["product_key"], unit=owner_terms["unit"],
        currency=observation["currency"], pack_units=owner_terms["pack_units"],
        pack_price=observation["observed_price"],
        minimum_order_units=owner_terms["minimum_order_units"],
        available_units=owner_terms["available_units"],
        delivery_days=owner_terms["delivery_days"],
        delivery_fee=owner_terms["delivery_fee"], channel="online_order",
        source_url=observation["url"], price_status="live_observed",
    )
