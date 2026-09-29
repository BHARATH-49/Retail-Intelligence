"""Observe a public exact-product page from a shop-approved website."""

import ipaddress
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser


class _StructuredProducts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_json = False
        self.parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.in_json = True
            self.parts = []

    def handle_data(self, data):
        if self.in_json:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_json:
            self.scripts.append("".join(self.parts))
            self.in_json = False


def _products(value):
    if isinstance(value, list):
        for part in value:
            yield from _products(part)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if "Product" in types:
            yield value
        if "@graph" in value:
            yield from _products(value["@graph"])


def extract_exact_product(html, *, expected_sku):
    """Return only a structured price whose product SKU matches exactly."""
    if not isinstance(expected_sku, str) or not expected_sku.strip():
        raise ValueError("An exact owner-confirmed SKU or barcode is required.")
    parser = _StructuredProducts()
    parser.feed(html)
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        for product in _products(data):
            identifiers = {
                str(product.get(key, "")).strip()
                for key in ("sku", "gtin", "gtin8", "gtin12", "gtin13", "gtin14", "productID")
            }
            if expected_sku.strip() not in identifiers:
                continue
            offers = product.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                try:
                    price = Decimal(str(offer.get("price", "")))
                except InvalidOperation:
                    continue
                currency = offer.get("priceCurrency")
                if price.is_finite() and price >= 0 and isinstance(currency, str) and len(currency) == 3:
                    return {"name": product.get("name"), "sku": expected_sku.strip(),
                            "price": float(price), "currency": currency.upper(),
                            "availability_text": offer.get("availability")}
    return None


def _validate_url(url, approved_host):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = approved_host.lower().removeprefix("www.")
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only ordinary HTTPS product links are accepted.")
    if host.removeprefix("www.") != allowed or not host:
        raise ValueError("Product link is outside the approved website.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host.endswith(".local"):
            raise ValueError("Local addresses are not approved product websites.")
    else:
        if not address.is_global:
            raise ValueError("Private network addresses are not approved websites.")
    return url


class _ApprovedRedirects(HTTPRedirectHandler):
    def __init__(self, approved_host):
        self.approved_host = approved_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(urljoin(req.full_url, newurl), self.approved_host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def observe_product(url, *, approved_host, expected_sku, mode="online_order", timeout=10):
    """Fetch one approved page; never infer delivery or Quito availability."""
    _validate_url(url, approved_host)
    if mode not in {"online_order", "offline_reference"}:
        raise ValueError("mode must be online_order or offline_reference.")
    opener = build_opener(_ApprovedRedirects(approved_host))
    robots_url = f"https://{urlparse(url).hostname}/robots.txt"
    with opener.open(Request(robots_url, headers={"User-Agent": "Retail-Intelligence/1.0"}), timeout=timeout) as robots_response:
        rules = robots_response.read(200_001)
    if len(rules) > 200_000:
        raise ValueError("Website access rules are too large to inspect.")
    robots = RobotFileParser()
    robots.parse(rules.decode("utf-8", errors="replace").splitlines())
    if not robots.can_fetch("Retail-Intelligence", url):
        raise ValueError("The approved website does not permit this page to be checked.")
    request = Request(url, headers={"User-Agent": "Retail-Intelligence/1.0 (one owner-approved product page)"})
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"Product page returned HTTP {response.status}.")
        final_url = response.geturl()
        _validate_url(final_url, approved_host)
        html = response.read(2_000_001)
    if len(html) > 2_000_000:
        raise ValueError("Product page is too large for this small tracker.")
    observed = extract_exact_product(html.decode("utf-8", errors="replace"), expected_sku=expected_sku)
    if observed is None:
        return {"status": "no_verified_price", "url": final_url,
                "checked_at": datetime.now(timezone.utc).isoformat(), "mode": mode}
    return {"status": "observed", "url": final_url,
            "checked_at": datetime.now(timezone.utc).isoformat(), "mode": mode,
            **observed, "delivery_fee": None, "delivery_days": None,
            "quito_availability_confirmed": False}
