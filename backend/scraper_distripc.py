"""
Playwright scraper for DistriPC (La Réunion) smartphone catalogue.

Strategy: Algolia-powered e-commerce site with numbered pagination.
Products listed at /21-telephonie, 16 per page, ?prod_distripc[page]=N for pages 1-7.
Cards use .product-card, price in span.current-price, name in h6.card-title a.
Name format: "Téléphone portable BRAND Model - Version RAMGo / StorageGo / xG"
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, classify_product, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://www.distripc.com/21-telephonie"

_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('.product-card');
    const products = [];
    const seen = new Set();

    cards.forEach(card => {
        const titleEl = card.querySelector('h6.card-title a');
        if (!titleEl) return;

        const name = (titleEl.getAttribute('title') || titleEl.textContent.trim());
        const url = titleEl.href || '';

        // Extract product ID from URL: /9978-gsm-samsung-...html
        const idMatch = url.match(/\\/(\\d+)-[^/]+\\.html/);
        const id = idMatch ? idMatch[1] : '';
        if (!id || seen.has(id)) return;
        seen.add(id);

        // Current price
        const priceEl = card.querySelector('.current-price');
        let price = null;
        if (priceEl) {
            const m = priceEl.textContent.replace(/\\u00a0/g, ' ').match(/([\\d\\s]+,\\d{2})/);
            if (m) price = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }
        if (price === null) return;

        // Regular price (before promo)
        const regPriceEl = card.querySelector('.regular-price');
        let originalPrice = null;
        if (regPriceEl) {
            const m = regPriceEl.textContent.replace(/\\u00a0/g, ' ').match(/([\\d\\s]+,\\d{2})/);
            if (m) {
                const op = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
                if (op > price) originalPrice = op;
            }
        }

        // Image
        const img = card.querySelector('.card-image img');
        const imgUrl = img ? img.src : null;

        products.push({ id, name, price, originalPrice, url, image: imgUrl });
    });

    return products;
}
"""


def _parse_distripc_name(
    name: str,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse DistriPC product name.

    Formats observed:
        'Téléphone portable Samsung Galaxy A07 - Version 6Go / 128Go'
        'TELEPHONE PORTABLE SAMSUNG GALAXY S25FE - Version 8Go / 128Go / 5G'
        'TELEPHONE PORTABLE APPLE IPHONE AIR - Version 256Go'
        'TELEPHONE PORTABLE BLACKVIEW SHARK 6 - VERSION 5G'
        'Telephone portable MOTO G15 - Version 4Go / 128Go - XT2433-5'
        'TELEPHONE SENIOR BINOM SX1 - AVEC BOUTON SOS'
        'Télpéhone à touches BARTYPE C80 BEAFON - MODELE 4G'
    """
    name = " ".join(name.split())

    # Remove leading phone-type prefixes, but NOT "téléphone fixe/sans-fil/filaire"
    clean = re.sub(
        r"^T[ée]l[ée]?ph?[oé]ne[s]?\s+"
        r"(?!fixe|sans|filaire)"
        r"(?:"
        r"portable\s+(?:(?:pliant|r[ée]sistant)\s+)?"
        r"|senior\s+"
        r"|[àa]\s+(?:touches|clapet)\s+"
        r"|r[ée]sistant\s+(?:portable\s+)?"
        r"|pliable\s+"
        r"|ortable\s+"
        r")?",
        "", name, flags=re.I,
    )

    # Split on " - " to separate model from version info
    parts = clean.split(" - ")
    model_part = parts[0].strip()

    # Extract version info (storage, RAM, network)
    version_part = " ".join(parts[1:]) if len(parts) > 1 else ""

    # Extract storage from version part: "Version 6Go / 128Go" → 128Go
    storage = None
    storage_matches = re.findall(r"(\d+)\s*Go\b", version_part, re.I)
    if storage_matches:
        storage = max(storage_matches, key=lambda x: int(x)) + "GO"
    else:
        # Try model part
        storage_matches = re.findall(r"(\d+)\s*Go\b", model_part, re.I)
        if storage_matches:
            storage = max(storage_matches, key=lambda x: int(x)) + "GO"

    # Brand: known brands at start of model_part
    brand_patterns = [
        "samsung", "apple", "blackview", "xiaomi", "motorola", "moto",
        "honor", "huawei", "google", "oppo", "nokia", "nothing", "cmf",
        "konrow", "beafon", "binom", "crosscall", "realme", "oneplus",
        "doro", "energizer", "bartype", "poco", "alcatel",
    ]
    brand = ""
    model = model_part
    first_word = model_part.split()[0].lower() if model_part.split() else ""
    for bp in brand_patterns:
        if first_word == bp or model_part.lower().startswith(bp + " "):
            brand = bp.title()
            model = model_part[len(bp):].strip()
            break

    # Special cases
    if brand.lower() == "moto":
        brand = "Motorola"
    if brand.lower() == "cmf":
        # "CMF NOTHING PHONE 1" → brand=Nothing
        if model.lower().startswith("nothing"):
            brand = "Nothing"
            model = model[len("nothing"):].strip()
        else:
            brand = "CMF"
    if brand.lower() == "bartype":
        # "BARTYPE C80 BEAFON" → brand=Beafon
        brand = "Beafon"
        model = model_part  # keep full

    # Remove reference codes like "A075", "A366B", "XT2433-5", "SM-731B"
    model = re.sub(r"\b[A-Z]{1,3}\d{3,}[A-Z]?\b", "", model)
    model = re.sub(r"\bXT\d+-\d+\b", "", model, flags=re.I)
    model = re.sub(r"\bSM-\w+\b", "", model, flags=re.I)

    # Remove storage/RAM from model
    model = re.sub(r"\d+\s*Go\b", "", model, flags=re.I)
    # Remove screen size
    model = re.sub(r'\d+[.,]\d+\s*"?', "", model)
    # Remove network gen
    model = re.sub(r"\b[45]G\b", "", model)
    # Remove "android" references
    model = re.sub(r"\bandroid\b", "", model, flags=re.I)
    # Remove APN specs
    model = re.sub(r"\bapn\s*\d+mp\b", "", model, flags=re.I)

    model = re.sub(r"\s+", " ", model).strip(" -–,/")

    return brand, model, storage, None  # DistriPC doesn't list colors


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """Scrape DistriPC telephone catalogue via pagination."""
    results: list[PhoneData] = []
    seen_ids: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        # Load page 1 (no param) to detect max pages
        logger.info("Loading DistriPC catalogue page 1…")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector(".product-card", timeout=15000)
        await asyncio.sleep(2)

        # Dismiss cookie consent if present
        try:
            accept_btn = page.locator("text=J'ACCEPTE")
            if await accept_btn.count() > 0:
                await accept_btn.first.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Detect max page from pagination links
        max_page = await page.evaluate("""() => {
            let max = 1;
            document.querySelectorAll('a').forEach(a => {
                const m = a.href.match(/prod_distripc.*page.*=(\\d+)/);
                if (m) { const n = parseInt(m[1]); if (n > max) max = n; }
            });
            return max;
        }""")
        logger.info("Detected %d pages", max_page)

        all_raw: list[dict] = []

        # Page 1 (already loaded)
        page_raw: list[dict] = await page.evaluate(_EXTRACT_JS)
        for item in page_raw:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                all_raw.append(item)
        logger.info("Page 1: %d products (total: %d)", len(page_raw), len(all_raw))

        # Pages 2..max_page (param is 1-indexed but page 1 = first next page)
        for page_num in range(2, max_page + 1):
            url = f"{BASE_URL}?prod_distripc%5Bpage%5D={page_num}"
            logger.info("Loading page %d: %s", page_num, url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(".product-card", timeout=15000)
            await asyncio.sleep(1.5)

            page_raw = await page.evaluate(_EXTRACT_JS)
            for item in page_raw:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    all_raw.append(item)
            logger.info("Page %d: %d products (total: %d)", page_num, len(page_raw), len(all_raw))

        await browser.close()

    logger.info("Total products extracted: %d", len(all_raw))

    if on_progress:
        await on_progress(len(all_raw), 0)

    for i, raw in enumerate(all_raw):
        brand, model, storage, color = _parse_distripc_name(raw["name"])

        promo = None
        if raw.get("originalPrice"):
            promo = f"-{int(raw['originalPrice'] - raw['price'])}€"

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
            promotion=promo,
            product_type=classify_product(brand, raw["name"]),
            is_refurbished=detect_refurbished(raw["name"], raw.get("url", "")),
            plan_prices=[],
        )
        results.append(phone)
        logger.info(
            "[%d/%d] %s (%.2f€) [%s]%s",
            i + 1, len(all_raw), phone.name, phone.price_nu or 0,
            phone.product_type,
            " REFURB" if phone.is_refurbished else "",
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
