"""
Playwright scraper for Ravate.com (La Réunion) smartphone catalogue.

Strategy: PrestaShop e-commerce site with infinite scroll.
Products listed at /114-smartphone-telephonie, 24 per scroll batch.
Cards use .product-card with data-id-product attribute.
Prices in .current-price, brand in .product-brand.
Name format varies: "Brand Model specs - BRAND - REF" or "iPhone 16 128Go noir - neuf - APPLE - REF"
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, classify_product, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ravate.com/114-smartphone-telephonie"

_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('.product-card[data-id-product]');
    const products = [];
    const seen = new Set();

    cards.forEach(card => {
        const id = card.getAttribute('data-id-product');
        if (!id || seen.has(id)) return;
        seen.add(id);

        const nameEl = card.querySelector('.product-name');
        const brandEl = card.querySelector('.product-brand');
        const priceEl = card.querySelector('.current-price');
        const linkEl = card.querySelector('a.product-link');
        const imgEl = card.querySelector('.product-image-wrapper img');

        const name = nameEl ? nameEl.textContent.trim() : '';
        const brand = brandEl ? brandEl.textContent.trim() : '';

        let price = null;
        if (priceEl) {
            const m = priceEl.textContent.replace(/\\u00a0/g, ' ').match(/([\\d\\s]+,\\d{2})/);
            if (m) price = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        const url = linkEl ? linkEl.href : '';
        let imgUrl = imgEl ? (imgEl.getAttribute('data-src') || imgEl.getAttribute('src')) : null;

        if (name && price !== null) {
            products.push({ id, name, brand, price, url, image: imgUrl });
        }
    });

    return products;
}
"""


def _parse_ravate_name(
    name: str, brand_hint: str
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse Ravate product name.

    Formats observed:
        'iPhone 16 128Go noir - neuf - APPLE - IPHONE16128BK6'
        'Smartphone Redmi A5 4/128Go 6,88" vert - XIAOMI - XIAREDMIA5128GREE2'
        'Smartphone Galaxy A06 4/64Go Noir - SAMSUNG - A06BLACK'
        'iPhone 12 Pro 128Go graphite reconditionné grade A+ - APPLE - ...'
    """
    name = " ".join(name.split())

    # Remove trailing " - BRAND - REF" parts
    # Split on " - " and drop parts that are all-uppercase (brand/ref)
    parts = name.split(" - ")
    main_parts = []
    for p in parts:
        stripped = p.strip()
        if stripped.isupper() and len(stripped) > 1:
            continue
        main_parts.append(stripped)
    main = " - ".join(main_parts).strip(" -")
    if not main:
        main = parts[0].strip()

    # Remove leading "Smartphone " or "Téléphone "
    main_clean = re.sub(r"^(?:Smartphone|Téléphone)\s+", "", main, flags=re.I)

    # Extract storage: "128Go", "256Go", "4/128Go" etc.
    storage = None
    storage_m = re.search(r"(?:\d+/)?([\d]+)\s*Go\b", main_clean, re.I)
    if storage_m:
        storage = storage_m.group(1) + "GO"

    # Known colors
    colors = {
        "noir", "blanc", "bleu", "rouge", "vert", "rose", "gris", "argent",
        "or", "violet", "jaune", "orange", "black", "white", "blue", "red",
        "green", "pink", "gray", "grey", "silver", "gold", "purple", "yellow",
        "titanium", "graphite", "midnight", "starlight", "cream", "lavender",
        "mint", "navy", "corail", "beige", "turquoise", "bronze", "lime",
        "mojito", "sable",
    }

    color = None
    words = main_clean.split()
    # Scan from end for a color word
    for w in reversed(words):
        if w.lower().rstrip(".,") in colors:
            color = w.capitalize().rstrip(".,")
            break

    # Brand: use brand_hint from the page
    brand = brand_hint.strip().title() if brand_hint else ""
    # Special cases
    if brand.upper() == "APPLE" and main_clean.lower().startswith("iphone"):
        brand = "Apple"
    if not brand:
        brand = words[0] if words else "Unknown"

    # Model: clean up the main part
    model = main_clean
    # Remove storage pattern
    model = re.sub(r"\d+/\d+\s*Go\b", "", model, flags=re.I)
    model = re.sub(r"\d+\s*Go\b", "", model, flags=re.I)
    # Remove color
    if color:
        model = re.sub(r"\b" + re.escape(color) + r"\b", "", model, flags=re.I)
    # Remove screen size pattern like 6,88"
    model = re.sub(r'\d+[.,]\d+\s*"', "", model)
    # Remove "neuf", "reconditionné grade A+", etc.
    model = re.sub(r"\b(?:neuf|reconditionn[ée]+\s*(?:grade\s*\w+)?)\b", "", model, flags=re.I)
    # Remove "Non EU" reference
    model = re.sub(r"\bNon\s*EU\b", "", model, flags=re.I)
    # Remove leading brand from model
    if brand:
        model = re.sub(r"^" + re.escape(brand) + r"\s*[-–]?\s*", "", model, flags=re.I)
    # Clean up double spaces and trailing dashes
    model = re.sub(r"\s+", " ", model).strip(" -–,")

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """Scrape Ravate smartphone/telephony catalogue via infinite scroll."""
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Loading Ravate catalogue…")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector(".product-card", timeout=15000)
        await asyncio.sleep(2)

        # Scroll to load all products (infinite scroll, ~24 per batch)
        prev_count = 0
        stable_rounds = 0
        max_scrolls = 30  # safety cap (~720 products max)

        for scroll_i in range(max_scrolls):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            count = await page.evaluate(
                "document.querySelectorAll('.product-card[data-id-product]').length"
            )
            logger.info("Scroll %d: %d products loaded", scroll_i + 1, count)
            if count == prev_count:
                stable_rounds += 1
                if stable_rounds >= 2:
                    break
            else:
                stable_rounds = 0
            prev_count = count

        all_raw: list[dict] = await page.evaluate(_EXTRACT_JS)
        logger.info("Total products extracted: %d", len(all_raw))
        await browser.close()

    if on_progress:
        await on_progress(len(all_raw), 0)

    for i, raw in enumerate(all_raw):
        brand, model, storage, color = _parse_ravate_name(
            raw["name"], raw.get("brand", "")
        )
        phone = PhoneData(
            vendor_id=str(raw["id"]),
            name=raw["name"],
            brand=brand,
            model=model,
            storage=storage,
            color=color,
            image_url=raw.get("image"),
            page_url=raw.get("url"),
            price_nu=raw["price"],
            promotion=None,
            product_type=classify_product(brand, raw["name"]),
            is_refurbished=detect_refurbished(raw["name"], raw.get("url", "")),
            plan_prices=[],
        )
        results.append(phone)
        logger.info(
            "[%d/%d] %s (%.2f€) [%s]",
            i + 1, len(all_raw), phone.name, phone.price_nu or 0,
            phone.product_type,
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
