"""Kelkoo Italy feed. Requires Python 3.10+ and requests.
Read-only Shopify API access. No remote file/repository changes.
See the accompanying instructions before replacing your current generator.
"""
import csv
import json
import os
import re
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import requests

SHOP_URL = os.getenv("SHOP_URL", "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-10")
PUBLIC_DOMAIN = os.getenv("PUBLIC_DOMAIN", "25thstreet.it").strip()
OUTPUT = Path(os.getenv("FEED_OUTPUT", "kelkoo.xml"))
DELIVERY_COST = os.getenv("KELKOO_DELIVERY_COST", "0.00")
# Intentionally no invented delivery promise. Set only to your verified delivery time.
DELIVERY_TIME = os.getenv("KELKOO_DELIVERY_TIME", "").strip()
UTM_SOURCE = os.getenv("KELKOO_UTM_SOURCE", "kelkoo")
UTM_CAMPAIGN = os.getenv("KELKOO_UTM_CAMPAIGN", "catalogo")
# Invalid/missing GTINs are excluded by default, and recorded in the report.
REQUIRE_GTIN = os.getenv("KELKOO_REQUIRE_VALID_GTIN", "true").lower() in {"1", "true", "yes"}
SESSION = requests.Session()

VARIANT_FIELDS = """
              id
              title
              sku
              price
              compareAtPrice
              availableForSale
              barcodes(first: 1) {
                nodes {
                  value
                }
                pageInfo {
                  hasNextPage
                  endCursor
                }
              }
              media(first: 1) {
                edges {
                  node {
                    ... on MediaImage {
                      image {
                        url
                      }
                    }
                  }
                }
                pageInfo {
                  hasNextPage
                  endCursor
                }
              }
"""
PRODUCT_QUERY = """
query FeedProducts($cursor: String) {
  products(first: 5, after: $cursor, query: "status:active") {
    edges {
      node {
        id
        title
        handle
        vendor
        productType
        description
        category {
          fullName
        }
        onlineStoreUrl
        featuredMedia {
          ... on MediaImage {
            image {
              url
            }
          }
        }
        variants(first: 20) {
          edges {
            node {
""" + VARIANT_FIELDS + """
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""
VARIANT_QUERY = """
query FeedVariants($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 20, after: $cursor) {
      edges {
        node {
""" + VARIANT_FIELDS + """
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


def clean_text(value, limit=None):
    # Remove characters forbidden in XML 1.0. ElementTree escapes XML entities.
    value = str(value or "")
    value = "".join(c for c in value if c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] if limit else value


def valid_https(value):
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname)
    except ValueError:
        return False


def money(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Non-finite money value")
    return format(number.quantize(Decimal("0.01")), "f")


def clean_gtin(value):
    """Accept only valid GTIN lengths/check digits; never invent missing digits.
    A numeric string ending in .0 is cleaned without conversion to float.
    Scientific notation, separators, signs and arbitrary characters are rejected.
    """
    value = str(value or "").strip()
    if re.fullmatch(r"[0-9]+\.0+", value):
        value = value.split(".", 1)[0]
    if not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})", value):
        return ""
    total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(value[:-1])))
    return value if (10 - total % 10) % 10 == int(value[-1]) else ""


def access_token():
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com", SHOP_URL):
        raise ValueError("SHOP_URL must be your shop's myshopify.com hostname, without a path")
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("Set CLIENT_ID and CLIENT_SECRET as environment secrets")
    response = SESSION.post(f"https://{SHOP_URL}/admin/oauth/access_token", json={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
    }, timeout=(15, 60))
    response.raise_for_status()
    return response.json()["access_token"]


def graphql(token, query, variables):
    for attempt in range(7):
        response = SESSION.post(
            f"https://{SHOP_URL}/admin/api/{API_VERSION}/graphql.json",
            json={"query": query, "variables": variables},
            headers={"X-Shopify-Access-Token": token}, timeout=(15, 90))
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(min(2 ** attempt + 1, 60))
            continue
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") or []
        if errors:
            if all(error.get("extensions", {}).get("code") == "THROTTLED" for error in errors):
                time.sleep(min(2 ** attempt + 1, 60))
                continue
            # Do not publish partial data after a query or permission error.
            raise RuntimeError("GraphQL failed: " + json.dumps(errors, ensure_ascii=False))
        if payload.get("data") is None:
            raise RuntimeError("Shopify did not return query data")
        throttle = payload.get("extensions", {}).get("cost", {}).get("throttleStatus", {})
        if throttle.get("currentlyAvailable", 1000) < 200:
            time.sleep(2)
        return payload["data"]
    raise RuntimeError("Shopify API retries exhausted; existing feed not overwritten")


def fetch_products(token):
    cursor = None
    while True:
        page = graphql(token, PRODUCT_QUERY, {"cursor": cursor})["products"]
        for edge in page["edges"]:
            product = edge["node"]
            connection = product["variants"]
            variants = [item["node"] for item in connection["edges"]]
            while connection["pageInfo"]["hasNextPage"]:
                data = graphql(token, VARIANT_QUERY, {
                    "id": product["id"], "cursor": connection["pageInfo"]["endCursor"]})
                if data["product"] is None:
                    raise RuntimeError("Product disappeared during pagination; rerun export")
                connection = data["product"]["variants"]
                variants.extend(item["node"] for item in connection["edges"])
            product["feed_variants"] = variants
            yield product
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
        if not cursor:
            raise RuntimeError("Missing pagination cursor")


def product_url(handle, variant_id):
    base = f"https://{PUBLIC_DOMAIN}/products/{handle}"
    parsed = urlsplit(base)
    parameters = dict(parse_qsl(parsed.query))
    parameters.update(variant=variant_id, utm_source=UTM_SOURCE,
                      utm_medium="cpc", utm_campaign=UTM_CAMPAIGN)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(parameters), ""))


def atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            name = stream.name
            stream.write(content)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def build_feed(products):
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", PUBLIC_DOMAIN):
        raise ValueError("PUBLIC_DOMAIN must be a hostname, not a URL or path")
    delivery = money(DELIVERY_COST)
    if Decimal(delivery) < 0:
        raise ValueError("Delivery cost cannot be negative")
    root = ET.Element("products")
    seen = set()
    counts = Counter()
    issues = []
    for product in products:
        counts["products_read"] += 1
        # ACTIVE alone does not establish Online Store publication.
        if not product.get("onlineStoreUrl"):
            counts["not_on_online_store"] += 1
            continue
        description = clean_text(product.get("description"))
        # Remove the recurring purchase/delivery boilerplate from this catalog.
        description = re.split(r"Informazioni sull['’]Acquisto\s*:", description, maxsplit=1,
                               flags=re.IGNORECASE)[0].strip()[:3000]
        category = (product.get("category") or {}).get("fullName") or product.get("productType")
        main_image = ((product.get("featuredMedia") or {}).get("image") or {}).get("url", "")
        for variant in product["feed_variants"]:
            counts["variants_read"] += 1
            if not variant.get("availableForSale"):
                counts["not_available"] += 1
                continue
            raw_id = variant["id"].rsplit("/", 1)[-1]
            offer_id = "variant_" + raw_id
            reasons = []
            barcode_data = variant["barcodes"]
            media_data = variant["media"]
            # The first image is sufficient; the product image is the fallback.
            # A valid first GTIN is sufficient. If it is invalid and more exist,
            # stop rather than silently exclude a potentially valid offer.
            gtin = next((code for node in barcode_data["nodes"]
                         if (code := clean_gtin(node.get("value")))), "")
            if not gtin and barcode_data["pageInfo"]["hasNextPage"]:
                raise RuntimeError("Additional barcodes need pagination before this variant can be exported")
            if not gtin:
                counts["missing_or_invalid_gtin"] += 1
                if REQUIRE_GTIN:
                    reasons.append("missing_or_invalid_gtin")
            image = next((item["node"].get("image", {}).get("url")
                          for item in media_data["edges"] if item["node"].get("image")), None) or main_image
            if not valid_https(image):
                reasons.append("missing_or_invalid_image_url")
            if not description:
                reasons.append("missing_description")
            if not product.get("title", "").strip():
                reasons.append("missing_title")
            try:
                price = money(variant["price"])
                if Decimal(price) <= 0:
                    reasons.append("nonpositive_price")
            except (InvalidOperation, ValueError, TypeError):
                price = ""
                reasons.append("invalid_price")
            if offer_id in seen:
                raise RuntimeError("Duplicate variant ID: " + offer_id)
            seen.add(offer_id)
            if reasons:
                issues.append({"variant_id": raw_id, "sku": variant.get("sku", ""),
                               "product": clean_text(product.get("title")),
                               "reason": ";".join(reasons)})
                counts["excluded"] += 1
                continue
            title = clean_text(product["title"])
            variant_title = clean_text(variant.get("title"))
            if variant_title and variant_title.lower() != "default title":
                # Keep the distinguishing variant feature even for long titles.
                suffix = " - " + variant_title[:70]
                title = title[:150-len(suffix)] + suffix
            fields = {
                "id": offer_id, "title": title[:150],
                "product-url": product_url(product["handle"], raw_id),
                "price": price, "description": description,
                "image-url": image, "availability": "1", "delivery-cost": delivery,
            }
            # Kelkoo keeps the final selling price in price and the original
            # price in price-no-rebate. Never infer or invent a reference price.
            reference = variant.get("compareAtPrice")
            if reference is not None:
                try:
                    reference_price = money(reference)
                    if Decimal(reference_price) > Decimal(price):
                        fields["price-no-rebate"] = reference_price
                        counts["offers_with_reference_price"] += 1
                except (InvalidOperation, ValueError, TypeError):
                    counts["invalid_reference_price_omitted"] += 1
            if product.get("vendor"):
                fields["brand"] = clean_text(product["vendor"])
            if category:
                fields["merchant-category"] = clean_text(category)
            if gtin:
                fields["ean"] = gtin
            if DELIVERY_TIME:
                fields["delivery-time"] = clean_text(DELIVERY_TIME)
            # Do NOT claim that the SKU is a manufacturer part number (MPN).
            offer = ET.SubElement(root, "product")
            for key, value in fields.items():
                ET.SubElement(offer, key).text = clean_text(value)
            counts["offers_exported"] += 1
    if not counts["offers_exported"]:
        raise RuntimeError("No valid offers; existing feed left unchanged")
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # Actual XML parser check before replacing the existing file.
    ET.fromstring(xml)
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "country": "IT", "api_version": API_VERSION, "counts": dict(counts),
              "note": "Base variant prices; automatic discounts are not calculated by this script."}
    atomic_text(OUTPUT.with_suffix(".report.json"), json.dumps(report, ensure_ascii=False, indent=2))
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["variant_id", "sku", "product", "reason"])
    writer.writeheader()
    writer.writerows(issues)
    atomic_text(OUTPUT.with_suffix(".excluded.csv"), buffer.getvalue())
    atomic_text(OUTPUT, xml.decode("utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build_feed(fetch_products(access_token()))
