"""
Playwright scraper for DistriPC (La Réunion) smartphone catalogue.

Strategy: standard PrestaShop catalogue with numbered pagination.
Products listed at /21-telephonie, 16 per page, ?page=N.
Cards use article.js-product-miniature; id in data-id-product, price in .price,
full name in the image alt (the visible h4.card-title is CSS-truncated).
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
    const products = [];
    const seen = new Set();

    document.querySelectorAll('article.js-product-miniature').forEach(card => {
        // Product ID from the article's data attribute (reliable, no URL parsing)
        const id = card.getAttribute('data-id-product') || '';
        if (!id || seen.has(id)) return;

        const link = card.querySelector('h4.card-title a, .product-title a, a.product-thumbnail, a[href*=".html"]');
        const url = link ? link.href.split('#')[0] : '';

        // The visible h4 title is CSS-truncated ("..."); the image alt holds the full
        // product name (incl. version/storage). Prefer alt, fall back to the link text.
        const img = card.querySelector('.thumbnail img, img');
        let name = img ? (img.getAttribute('alt') || '').trim() : '';
        if (!name && link) name = link.textContent.trim();
        if (!name) return;

        // Current price
        const priceEl = card.querySelector('.product-price-and-shipping .price, .price, .current-price');
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

        // Image (full-size if available)
        const imgUrl = img ? (img.getAttribute('data-full-size-image-url') || img.src) : null;

        seen.add(id);
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

        # DistriPC migrated from a custom Algolia layout (.product-card,
        # ?prod_distripc[page]=N) to standard PrestaShop (article.js-product-miniature,
        # ?page=N). Crawl pages until one yields no new products instead of trusting a
        # max-page link — robust against both a stale over-count (empty page → crash)
        # and an under-count read before pagination rendered (silent partial collection).
        all_raw: list[dict] = []

        logger.info("Loading DistriPC catalogue page 1…")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("article.js-product-miniature", timeout=15000)
        await asyncio.sleep(2)

        # Dismiss cookie consent if present
        try:
            accept_btn = page.locator("text=J'ACCEPTE")
            if await accept_btn.count() > 0:
                await accept_btn.first.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        MAX_PAGES = 100  # safety cap against an infinite loop
        page_num = 1
        while page_num <= MAX_PAGES:
            if page_num > 1:
                url = f"{BASE_URL}?page={page_num}"
                logger.info("Loading page %d: %s", page_num, url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_selector("article.js-product-miniature", timeout=15000)
                except Exception:
                    logger.info("No products on page %d — end of pagination.", page_num)
                    break
                await asyncio.sleep(1.5)

            page_raw: list[dict] = await page.evaluate(_EXTRACT_JS)
            new_count = 0
            for item in page_raw:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    all_raw.append(item)
                    new_count += 1
            logger.info("Page %d: %d card(s), %d new (total: %d)", page_num, len(page_raw), new_count, len(all_raw))

            if page_num > 1 and new_count == 0:
                logger.info("No new products on page %d — stopping.", page_num)
                break

            page_num += 1

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
