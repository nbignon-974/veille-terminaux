"""
CSV importer for Orange Réunion price listings.

Expected format (semicolon-separated):
  Row 0: title
  Row 1: sub-tier labels
  Row 2: PNM values
  Row 3: column headers  →  OPERATION;Cycle;Marque;Lib regroupement;250 Go Pro;250 Go GP;150Go;80 Go;30 Go;5 Go;Prix Nu
  Rows 4+: data

Rows with Cycle == "dead" (case-insensitive) are skipped.
All subscription columns carry a 24-month engagement.
"""
import csv
import io
import logging
from typing import Optional

from scrapers import PhoneData, PlanPriceData, classify_product, detect_refurbished

logger = logging.getLogger(__name__)

# (column_header_in_csv, engagement_months)
PLAN_COLUMNS = [
    ("250 Go Pro", 24),
    ("250 Go GP", 24),
    ("150Go", 24),
    ("80 Go", 24),
    ("30 Go", 24),
    ("5 Go", 24),
]

_BRAND_FROM_NAME = [
    ("iphone", "Apple"),
    ("ipad", "Apple"),
    ("galaxy", "Samsung"),
    ("xcover", "Samsung"),
    ("pixel", "Google"),
    ("redmi", "Xiaomi"),
    ("xiaomi", "Xiaomi"),
]


def _extract_brand_from_name(name: str) -> str:
    lower = name.lower()
    for hint, brand in _BRAND_FROM_NAME:
        if hint in lower:
            return brand
    return "Autre"


def _parse_price(value: str) -> Optional[float]:
    v = value.strip().replace(",", ".")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_orange_csv(content: bytes) -> list[PhoneData]:
    """Parse Orange Réunion CSV bytes and return a list of PhoneData."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = list(reader)

    # Locate the header row (contains "Lib regroupement")
    header_idx = None
    for i, row in enumerate(rows):
        if any("lib regroupement" in cell.lower() for cell in row):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("En-tête introuvable dans le CSV (colonne 'Lib regroupement' manquante)")

    headers = [h.strip() for h in rows[header_idx]]

    def col(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            raise ValueError(f"Colonne requise introuvable : '{name}'")

    col_cycle = col("Cycle")
    col_marque = col("Marque")
    col_lib = col("Lib regroupement")
    col_prix_nu = col("Prix Nu")

    plan_col_indices: list[tuple[str, int, int]] = []
    for plan_name, engagement in PLAN_COLUMNS:
        idx = next(
            (i for i, h in enumerate(headers) if h.strip().lower() == plan_name.lower()),
            None,
        )
        if idx is not None:
            plan_col_indices.append((plan_name, engagement, idx))

    results: list[PhoneData] = []

    for row in rows[header_idx + 1:]:
        if len(row) <= col_prix_nu:
            continue

        cycle = row[col_cycle].strip().lower()
        if cycle == "dead":
            continue

        lib = row[col_lib].strip()
        if not lib:
            continue

        marque_raw = row[col_marque].strip()

        is_refurb = marque_raw.upper() == "RECONDITIONNE" or detect_refurbished(lib)
        if marque_raw.upper() == "RECONDITIONNE":
            brand = _extract_brand_from_name(lib)
        else:
            brand = marque_raw.title()

        product_type = classify_product(brand, lib)
        price_nu = _parse_price(row[col_prix_nu])

        plan_prices: list[PlanPriceData] = []
        for plan_name, engagement, idx in plan_col_indices:
            if idx < len(row):
                price_device = _parse_price(row[idx])
                if price_device is not None:
                    plan_prices.append(PlanPriceData(
                        plan_name=plan_name,
                        price_monthly=None,
                        price_device=price_device,
                        engagement_months=engagement,
                    ))

        results.append(PhoneData(
            vendor_id=None,
            name=lib,
            brand=brand,
            model=lib,
            storage=None,
            color=None,
            image_url=None,
            page_url=None,
            price_nu=price_nu,
            promotion=None,
            product_type=product_type,
            is_refurbished=is_refurb,
            plan_prices=plan_prices,
        ))

    logger.info("Parsed %d Orange Réunion products from CSV", len(results))
    return results
