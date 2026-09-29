"""Turn seven demand predictions and owner-entered stock into a reorder plan."""

from decimal import Decimal
from math import ceil, floor, isfinite


def _nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a nonnegative number.")
    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite nonnegative number.")
    return result


def _whole_days(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative whole number of days.")
    return value


def _round_up(amount, increment):
    # Ignore floating-point dust near an exact multiple of the order increment.
    multiple = ceil(max(0.0, amount / increment - 1e-9))
    return float(multiple * Decimal(str(increment)))


def _round_down(amount, increment):
    multiple = floor(max(0.0, amount / increment + 1e-9))
    return float(multiple * Decimal(str(increment)))


def plan_restock(
    forecast_units,
    *,
    stock_on_hand,
    unit,
    order_increment,
    lead_days,
    incoming_units,
    incoming_day=None,
    extra_cover_days=1,
    minimum_order_units=None,
    pack_multiple_units=None,
    shelf_life_days=None,
):
    """Plan today's order; day 0 is the first forecast day.

    The owner must explicitly pass incoming_units=0 when no order is due.
    A delivery on day N arrives before that day's forecast sales.
    Missing supplier constraints stay unknown rather than being treated as zero.
    """
    forecast = tuple(_nonnegative(value, "forecast_units") for value in forecast_units)
    if len(forecast) != 7:
        raise ValueError("Exactly seven daily forecast values are required.")
    stock = _nonnegative(stock_on_hand, "stock_on_hand")
    incoming = _nonnegative(incoming_units, "incoming_units")
    extra_days = _nonnegative(extra_cover_days, "extra_cover_days")
    increment = _nonnegative(order_increment, "order_increment")
    if increment == 0:
        raise ValueError("order_increment must be greater than zero.")
    minimum = (
        None if minimum_order_units is None
        else _nonnegative(minimum_order_units, "minimum_order_units")
    )
    pack = (
        None if pack_multiple_units is None
        else _nonnegative(pack_multiple_units, "pack_multiple_units")
    )
    if pack is not None:
        if pack == 0 or abs(pack / increment - round(pack / increment)) > 1e-9:
            raise ValueError("pack_multiple_units must be a positive multiple of order_increment.")
    life = None if shelf_life_days is None else _whole_days(shelf_life_days, "shelf_life_days")
    if life == 0:
        raise ValueError("shelf_life_days must be at least one day.")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("unit must name the owner-confirmed stock unit.")
    lead = _whole_days(lead_days, "lead_days")
    if incoming > 0:
        arrival = _whole_days(incoming_day, "incoming_day")
    elif incoming_day is not None:
        raise ValueError("incoming_day is only used when incoming_units is positive.")
    else:
        arrival = None

    total = sum(forecast)
    average = total / 7
    buffer_units = _round_up(average * extra_days, increment)
    covered_days = 0
    running_demand = 0.0
    for demand in forecast:
        running_demand += demand
        if running_demand > stock + 1e-9:
            break
        covered_days += 1

    first_short_day = None
    largest_gap = 0.0
    cumulative_before_delivery = 0.0
    for day in range(min(lead, 7)):
        cumulative_before_delivery += forecast[day]
        available = stock + (
            incoming if arrival is not None and arrival <= day else 0
        )
        gap = cumulative_before_delivery - available
        if gap > 1e-9 and first_short_day is None:
            first_short_day = day
        largest_gap = max(largest_gap, gap)

    result = {
        "unit": unit.strip(),
        "expected_demand_7d": total,
        "average_daily_demand": average,
        "days_covered_by_current_stock": covered_days,
        "coverage_reaches_forecast_end": covered_days == 7,
        "buffer_units": buffer_units,
        "shortage_before_new_delivery": first_short_day is not None,
        "first_short_day_index": first_short_day,
        "bridging_units_needed": _round_up(largest_gap, increment),
        "pre_delivery_check_limited_to_forecast": lead >= 7,
        "lead_time_demand": None,
        "reorder_check_demand": None,
        "reorder_point_units": None,
        "stock_counted_at_reorder_check": None,
        "order_now": None,
        "suggested_order_units": None,
        "unconstrained_order_units": None,
        "minimum_order_units": minimum,
        "pack_multiple_units": pack,
        "shelf_life_days": life,
        "shelf_life_sell_through_cap_units": None,
        "shelf_life_check_limited": False,
        "order_constraint_status": "horizon_insufficient",
        "horizon_sufficient": lead < 7,
    }
    if lead >= 7:
        return result

    lead_demand = sum(forecast[:lead])
    # With same-day delivery, today's demand still matters to an order
    # decision made before the day's sales.
    reorder_check_demand = sum(forecast[:max(lead, 1)])
    reorder_point = _round_up(reorder_check_demand + buffer_units, increment)
    # A known delivery at or before the new supplier's arrival counts toward
    # the reorder check. The later stockout check will identify any shortage
    # that occurs before either delivery can arrive.
    stock_at_check = stock + (incoming if arrival is not None and arrival <= lead else 0)
    order_now = stock_at_check <= reorder_point + 1e-9

    # An existing delivery may come late in the week. Cover the largest
    # projected shortfall after our order can arrive, as well as the end-week
    # cushion; subtract the existing delivery only after its arrival day.
    needed = total + buffer_units - stock - (
        incoming if arrival is not None and arrival < 7 else 0
    )
    cumulative = 0.0
    for day, demand in enumerate(forecast):
        cumulative += demand
        if day >= lead:
            arrived = incoming if arrival is not None and arrival <= day else 0
            needed = max(needed, cumulative - stock - arrived)
    unconstrained = _round_up(needed, increment) if order_now else 0.0
    suggested = unconstrained
    constraint_status = "not_due" if unconstrained == 0 else "ready"
    shelf_cap = None
    life_limited = False
    if unconstrained > 0:
        step = pack if pack is not None else increment
        suggested = _round_up(max(unconstrained, minimum or 0), step)
        if life is not None:
            expiry = lead + life
            if expiry > 7:
                life_limited = True
            else:
                demand_before_arrival = sum(forecast[:lead])
                old_stock = stock + (
                    incoming if arrival is not None and arrival <= lead else 0
                )
                old_stock = max(0.0, old_stock - demand_before_arrival)
                later_incoming = (
                    incoming if arrival is not None and lead < arrival < expiry else 0
                )
                sell_through = max(
                    0.0, sum(forecast[lead:expiry]) - old_stock - later_incoming
                )
                shelf_cap = _round_down(sell_through, step)
                if suggested > shelf_cap + 1e-9:
                    suggested = None
                    constraint_status = "shelf_life_conflict"

    result.update({
        "lead_time_demand": lead_demand,
        "reorder_check_demand": reorder_check_demand,
        "reorder_point_units": reorder_point,
        "stock_counted_at_reorder_check": stock_at_check,
        "order_now": order_now and unconstrained > 0,
        "suggested_order_units": suggested,
        "unconstrained_order_units": unconstrained,
        "shelf_life_sell_through_cap_units": shelf_cap,
        "shelf_life_check_limited": life_limited,
        "order_constraint_status": constraint_status,
    })
    return result
