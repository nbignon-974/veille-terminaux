"""
Playwright scraper for SFR Réunion mobile phone catalogue.

Strategy: the catalogue at https://www.sfr.re/nos-telephones/ embeds an iframe
pointing to https://www.sfr.re/boutique-mobile/telephones/toutes-les-offres which
is an AngularJS app. That app calls a JSON REST API:
  GET /boutique-mobile/api/views/toutes-les-offres/devices/search?page=1&size=100

Each device variant contains a `prices` array with:
  - deedType = "Nu"       → prix nu (unlocked, no plan)
  - deedType = "Conquete" → prix avec forfait
    · clientType "ABO"    → client SFR mobile
    · clientType "CBL"    → client SFR Box (bundle)
    · categoryPrice "A"   → forfait bas de gamme (Primo / Initial)
    · categoryPrice "C"   → forfait haut de gamme (Intense / Absolu / Excellence)
    · commitment 12 / 24  → durée d'engagement en mois
  - price is in cents (divide by 100)
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, PlanPriceData, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sfr.re"
CATALOGUE_URL = f"{BASE_URL}/boutique-mobile/telephones/toutes-les-offres"
API_URL = f"{BASE_URL}/boutique-mobile/api/views/toutes-les-offres/devices/search"

# Mapping categoryPrice + clientType → human-readable forfait label
_CATEGORY_LABEL: dict[tuple[str, str], str] = {
    ("A", "ABO"): "Forfait entrée de gamme – client SFR mobile",
    ("A", "CBL"): "Forfait entrée de gamme – client SFR Box",
    ("C", "ABO"): "Forfait haut de gamme – client SFR mobile",
    ("C", "CBL"): "Forfait haut de gamme – client SFR Box",
}





def _parse_name(full_name: str) -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Parse 'APPLE IPHONE 15 128GO JAUNE' into (brand, model, storage, color).
    Returns (brand, model, storage, color).
    """
    parts = full_name.strip().split()
    if not parts:
        return full_name, full_name, None, None

    brand = parts[0].capitalize()

    storage_re = re.compile(r"^\d+\s*(?:GO|TO|GB|TB)$", re.I)
    storage_idx = next((i for i, p in enumerate(parts) if storage_re.match(p)), None)

    if storage_idx is not None:
        storage = parts[storage_idx].upper()
        model_parts = parts[1:storage_idx]
        color_parts = parts[storage_idx + 1 :]
    else:
        storage = None
        model_parts = parts[1:]
        color_parts = []

    model = " ".join(model_parts).title()
    color = " ".join(color_parts).title() if color_parts else None

    return brand, model, storage, color


def _device_to_phone_data(device: dict) -> PhoneData:
    """Convert a device JSON object from the SFR API into a PhoneData."""
    manufacturer = device.get("manufacturer", "").strip()
    model_raw = device.get("model", "").strip()
    sfr_id = str(device.get("masterDeviceId", "")) or None
    slug = device.get("slug", "")

    # Build display name  (APPLE IPHONE 15 128GO JAUNE)
    full_name = f"{manufacturer} {model_raw}".upper().strip()
    brand, model, storage, color = _parse_name(full_name)

    # The API returns the best fromPrice across all variants (in cents)
    from_price_cents = device.get("fromPrice")
    price_nu: Optional[float] = None

    image_url: Optional[str] = None
    page_url = f"{BASE_URL}/boutique-mobile/telephones/toutes-les-offres/{slug}" if slug else None

    plan_prices: list[PlanPriceData] = []
    promo_texts: list[str] = []

    # Process all variants (color × memory combinations)
    for variant in device.get("variants", []):
        variant_color = variant.get("color", "")
        variant_memory = variant.get("memory", "")
        variant_id = variant.get("recordId")

        # Image from first variant
        if image_url is None and variant.get("images"):
            # Prefer medium front image
            imgs = variant["images"]
            med = next((i["url"] for i in imgs if i.get("size") == "M" and i.get("position") == "front"), None)
            image_url = med or imgs[0].get("url")

        if variant.get("odrUrl") or variant.get("odrAmount"):
            promo_texts.append(f"ODR {variant.get('odrAmount', '')}€ sur {variant_color} {variant_memory}Go")

        for p in variant.get("prices", []):
            deed = p.get("deedType", "")
            client = p.get("clientType") or ""
            category = p.get("categoryPrice") or ""
            commitment = p.get("commitment", 0) or 0
            price_cents = p.get("price")
            if price_cents is None:
                continue
            price_euros = price_cents / 100.0

            odr = p.get("odramount")
            if odr:
                promo_texts.append(f"ODR {odr/100:.0f}€")

            if deed == "Nu":
                # Prix nu – keep the lowest across variants
                if price_nu is None or price_euros < price_nu:
                    price_nu = price_euros
            else:
                # Forfait price — build label
                base_label = _CATEGORY_LABEL.get((category, client), f"Forfait {client}/{category}")
                plan_label = f"{base_label} – {commitment} mois"
                # Store device price for this plan (terminal subsidised price)
                plan_prices.append(PlanPriceData(
                    plan_name=plan_label,
                    price_monthly=None,      # monthly plan fee not in this API
                    price_device=price_euros,
                    engagement_months=commitment if commitment > 0 else None,
                ))

    # Fallback: use fromPrice as price_nu if no explicit Nu price found
    if price_nu is None and from_price_cents is not None:
        price_nu = from_price_cents / 100.0

    # Deduplicate plan prices (same label → keep lowest device price)
    deduped: dict[str, PlanPriceData] = {}
    for pp in plan_prices:
        key = pp.plan_name
        if key not in deduped or (pp.price_device or 0) < (deduped[key].price_device or 0):
            deduped[key] = pp

    promotion = " | ".join(set(promo_texts)) if promo_texts else None

    return PhoneData(
        vendor_id=sfr_id,
        name=full_name,
        brand=brand,
        model=model,
        storage=storage,
        color=color,
        image_url=image_url,
        page_url=page_url,
        price_nu=price_nu,
        promotion=promotion,
        is_refurbished=detect_refurbished(full_name),
        plan_prices=list(deduped.values()),
    )


_API_HEADERS = {
    "region": "re",
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "referer": CATALOGUE_URL,
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_API_BODY = {"viewSlug": ["toutes-les-offres"], "region": "RE"}

_FETCH_JS = """
async ([url, pageNum]) => {
    const r = await fetch(url + '?page=' + pageNum + '&size=10', {
        method: 'POST',
        headers: {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json;charset=UTF-8',
            'region': 're',
        },
        body: JSON.stringify({"viewSlug": ["toutes-les-offres"], "region": "RE"}),
    });
    return r.json();
}
"""


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """
    Main scrape entry point. Fetches all SFR Réunion phones via JSON API.

    on_progress(phones_found, phones_scraped): optional async callback.
    Returns a list of PhoneData objects.
    """
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=_API_HEADERS["user-agent"],
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        # Load the catalogue page once so the browser has correct origin context
        logger.info("Loading catalogue page…")
        await page.goto(CATALOGUE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)

        # Step 1: first API call to discover total
        logger.info("Fetching device catalogue via JSON API…")
        first_page: dict = await page.evaluate(_FETCH_JS, [API_URL, 1])

        nb_elements: int = first_page.get("nbElements", 0)
        nb_pages: int = first_page.get("nbPages", 1)
        logger.info("Total devices: %d across %d pages", nb_elements, nb_pages)

        if on_progress:
            await on_progress(nb_elements, 0)

        all_devices: list[dict] = list(first_page.get("content", []))

        # Step 2: fetch remaining pages
        for p_num in range(2, nb_pages + 1):
            logger.info("Fetching page %d/%d…", p_num, nb_pages)
            page_data: dict = await page.evaluate(_FETCH_JS, [API_URL, p_num])
            all_devices.extend(page_data.get("content", []))
            await asyncio.sleep(0.2)

        logger.info("Total devices fetched: %d", len(all_devices))
        await browser.close()

    # Step 3: convert API data to PhoneData objects (no browser needed)
    for i, device in enumerate(all_devices):
        try:
            phone_data = _device_to_phone_data(device)
            results.append(phone_data)
            logger.info(
                "[%d/%d] %s (nu: %s€, %d forfaits)",
                i + 1, len(all_devices),
                phone_data.name,
                f"{phone_data.price_nu:.2f}" if phone_data.price_nu else "N/A",
                len(phone_data.plan_prices),
            )
        except Exception as e:
            logger.warning("Failed to process device %s: %s", device.get("slug"), e)
        if on_progress:
            await on_progress(len(all_devices), i + 1)

    return results
