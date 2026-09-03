# products/adapters.py
import json
import os

SEED_FILE_PATH = os.path.join(os.path.dirname(__file__), "seed_data.json")

with open(SEED_FILE_PATH) as f:
    _SEED_PRODUCTS = json.load(f)


def lookup_registry(gtin: str):
    """
    Checks whether a GTIN is a known, registered product.

    Returns: (registry_result, product_info, raw_response)
      registry_result: "registered" | "not_found" | "unreachable"
      product_info: dict or None
      raw_response: whatever was returned, for audit/debugging
    """
    try:
        product = _SEED_PRODUCTS.get(gtin)
    except Exception:
        # stands in for a real network/timeout failure once this
        # becomes a live HTTP call to a manufacturer's API
        return "unreachable", None, None

    if product is None:
        return "not_found", None, {"gtin": gtin, "found": False}

    return "registered", product, {"gtin": gtin, "found": True, **product}