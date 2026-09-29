"""Validate product ideas explicitly supplied by a shop owner."""

from datetime import date


SIGNAL_TYPES = {
    "customer_request": "Customer request",
    "local_event": "Local event",
    "seasonal_need": "Seasonal need",
    "owner_observation": "Owner observation",
}


def owner_candidate(
    *, store_nbr, product_name, signal_type, evidence,
    event_date=None, request_count=None,
):
    """Return a clear candidate record; never infer demand for a new item."""
    if isinstance(store_nbr, bool) or not isinstance(store_nbr, int) or store_nbr < 1:
        raise ValueError("store_nbr must be a positive store number.")
    if (not isinstance(product_name, str) or not product_name.strip()
            or not any(character.isalnum() for character in product_name)
            or len(product_name.strip()) > 120):
        raise ValueError("product_name must be 1 to 120 characters.")
    if not isinstance(signal_type, str) or signal_type not in SIGNAL_TYPES:
        raise ValueError("signal_type must be a supported owner-entered reason.")
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence.strip()) > 400:
        raise ValueError("evidence must explain the idea in 1 to 400 characters.")
    if event_date is not None:
        try:
            event_date = date.fromisoformat(event_date).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("event_date must be YYYY-MM-DD.") from error
    if signal_type == "local_event" and event_date is None:
        raise ValueError("A local event needs its date.")
    if request_count is not None:
        if signal_type != "customer_request":
            raise ValueError("request_count is only used for customer requests.")
        if isinstance(request_count, bool) or not isinstance(request_count, int) or request_count < 1:
            raise ValueError("request_count must be a positive whole number.")
    return {
        "store_nbr": store_nbr,
        "product_name": product_name.strip(),
        "signal_type": signal_type,
        "signal_label": SIGNAL_TYPES[signal_type],
        "evidence": evidence.strip(),
        "event_date": event_date,
        "request_count": request_count,
        "source": "owner_entered",
    }
