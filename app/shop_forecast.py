"""Adapt the V1 LightGBM method to dated shop sales after a later-date check."""

from datetime import date, timedelta

import numpy as np

from src.data.lightgbm_fit import fit_predict


MIN_DAYS = 180
HOLDOUT_WEEKS = 3
FEATURES = (
    "sales_7_days_ago", "sales_14_days_ago",
    "sales_21_days_ago", "sales_28_days_ago",
    "preceding_7_day_average", "preceding_28_day_average",
    "day_of_week", "day_of_month", "month", "week_of_year",
    "last_7_day_average_at_forecast_start",
)
SHOP_SETTINGS = {
    "objective": "regression_l1",
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 10,
    "random_state": 42,
    "n_jobs": 1,
    "verbosity": -1,
}


def _features(history, first_day, targets, forecast_start):
    """For each seven-day week, read only sales before that week's start."""
    rows = []
    for target in targets:
        origin = target - ((target - forecast_start) % 7)
        day = first_day + timedelta(days=target)
        rows.append([
            *(history[target - 7 * week] for week in range(1, 5)),
            float(np.mean(history[target - 13:target - 6])),
            float(np.mean(history[target - 34:target - 6])),
            day.weekday(), day.day, day.month, day.isocalendar().week,
            float(np.mean(history[origin - 7:origin])),
        ])
    return np.asarray(rows, dtype=np.float32)


def _fit_week(history, first_day, start, trainer):
    train_days = range(34, start)
    test_days = range(start, start + 7)
    x_train = _features(history, first_day, train_days, start)
    y_train = np.asarray(history[34:start], dtype=np.float32)
    x_test = _features(history, first_day, test_days, start)
    prediction = trainer(x_train, y_train, x_test, FEATURES, SHOP_SETTINGS)
    baseline = np.asarray([
        np.median([history[day - 7 * week] for week in range(1, 5)])
        for day in test_days
    ])
    return prediction, baseline


def forecast_product(product, closed_days, sales, origin_day, *, trainer=fit_predict):
    """Return no numeric forecast when history or chronological validation fails."""
    origin = date.fromisoformat(origin_day)
    result = {
        "product_id": product["id"], "status": "history_needed",
        "reason": "About six months of closed daily sales records are needed.",
        "daily": [],
    }
    first = origin - timedelta(days=MIN_DAYS - 1)
    if date.fromisoformat(product["first_stocked_on"]) > first:
        return result
    required = [(first + timedelta(days=offset)).isoformat() for offset in range(MIN_DAYS)]
    if not set(required).issubset(set(closed_days)):
        result["reason"] = "Close each trading day, including zero-sale days, to build a complete history."
        return result
    history = np.asarray([sales.get(day, 0.0) for day in required], dtype=np.float32)
    if not np.all(np.isfinite(history)) or np.any(history < 0):
        result["reason"] = "Sales history has invalid quantities."
        return result
    errors = []
    simple_errors = []
    for start in range(MIN_DAYS - HOLDOUT_WEEKS * 7, MIN_DAYS, 7):
        predicted, baseline = _fit_week(history, first, start, trainer)
        actual = history[start:start + 7]
        errors.extend(abs(predicted - actual))
        simple_errors.extend(abs(baseline - actual))
    model_mae = float(np.mean(errors))
    baseline_mae = float(np.mean(simple_errors))
    result["model_mae"] = model_mae
    result["baseline_mae"] = baseline_mae
    if model_mae > baseline_mae:
        result["status"] = "validation_failed"
        result["reason"] = (
            "The shop LightGBM missed more units than the simple reference "
            "on the last three historical weeks; no order forecast is shown."
        )
        return result
    predicted, _ = _fit_week(history, first, MIN_DAYS, trainer)
    result["status"] = "available"
    result["reason"] = "Shop LightGBM passed three later-week checks against the four-week reference."
    result["daily"] = [
        ((origin + timedelta(days=offset + 1)).isoformat(), float(predicted[offset]))
        for offset in range(7)
    ]
    return result


def build_shop_forecasts(shop, origin_day, *, trainer=fit_predict):
    shop.validate_ledger()
    results = []
    for product in shop.products():
        closed_days, sales = shop.closed_sales(product["id"], origin_day)
        results.append(
            forecast_product(product, closed_days, sales, origin_day, trainer=trainer)
        )
    return results
