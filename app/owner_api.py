"""Owner workflow routes kept separate from the historical research explorer."""

from datetime import date

from src.inventory.restock import plan_restock


def read(path, query, shop):
    day = query.get("day", [date.today().isoformat()])[0]
    if path == "/api/shop/settings":
        return shop.settings()
    if path == "/api/shop/products":
        return shop.products()
    if path == "/api/shop/day":
        return shop.day_summary(day)
    if path == "/api/shop/bills":
        return shop.bills(day)
    if path == "/api/shop/to-buy":
        return shop.to_buy()
    if path == "/api/shop/offers":
        return shop.offers()
    if path == "/api/shop/web-links":
        return shop.web_links()
    if path == "/api/shop/feedback":
        return shop.feedback()
    if path == "/api/shop/opportunities":
        return shop.opportunities(as_of=day)
    if path == "/api/shop/forecast":
        forecast = shop.latest_forecast()
        for row in forecast["products"]:
            if row["status"] != "available" or len(row["daily"]) != 7:
                continue
            product = shop.product(row["product_id"])
            try:
                plan = plan_restock(
                    [daily["units"] for daily in row["daily"]],
                    stock_on_hand=product["stock"], unit=product["unit"],
                    order_increment=product["order_increment"],
                    lead_days=product["lead_days"],
                    incoming_units=product["incoming_units"],
                    incoming_day=product["incoming_day"],
                    extra_cover_days=product["extra_cover_days"],
                    shelf_life_days=product["shelf_life_days"],
                )
                row["restock"] = plan
            except ValueError as error:
                row["restock_error"] = str(error)
        return forecast
    raise KeyError(path)


def write(path, payload, shop):
    if path == "/api/shop/settings":
        return shop.save_settings(payload)
    if path == "/api/shop/products":
        return shop.save_product(payload)
    if path == "/api/shop/stock":
        return shop.stock_change(payload)
    if path == "/api/shop/bills":
        return shop.complete_bill(payload)
    if path == "/api/shop/bills/void":
        return shop.void_bill(payload.get("receipt_id"))
    if path == "/api/shop/day-close":
        day = payload.get("day")
        result = shop.close_day(day, payload.get("review_token"))
        job = shop.enqueue_forecast_job(result["day"], result["version"])
        result["job_status"] = job["status"]
        return result
    if path == "/api/shop/day-reopen":
        return shop.reopen_day(payload.get("day"), payload.get("reason"))
    if path == "/api/shop/forecast/retry":
        summary = shop.day_summary(payload.get("day"))
        close = summary["close"]
        if close is None or close["status"] != "closed":
            raise ValueError("Close the day before preparing its forecast.")
        return shop.enqueue_forecast_job(summary["day"], close["version"], retry=True)
    if path == "/api/shop/to-buy":
        return shop.save_to_buy(payload)
    if path == "/api/shop/to-buy/remove":
        return shop.remove_to_buy(payload.get("product_id"))
    if path == "/api/shop/offers":
        return shop.save_offer(payload)
    if path == "/api/shop/web-links":
        return shop.save_web_link(payload)
    if path == "/api/shop/compare":
        return shop.compare_to_buy()
    if path == "/api/shop/feedback/customer":
        return shop.add_feedback(payload, source="customer")
    if path == "/api/shop/feedback/owner":
        return shop.add_feedback(payload, source="owner")
    raise KeyError(path)
