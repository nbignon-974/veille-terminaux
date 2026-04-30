"""
Playwright scraper for Darty Réunion smartphone catalogue.

Strategy: Symfony e-commerce site with server-rendered HTML and numbered pagination.
Products listed at /c/smartphone, 30 per page, ?page=N for pages 1-3.
Cards use .product-box-line-container with GTM data attributes on a.gtm-product-link:
  data-gtm-product-title, data-gtm-product-price, data-gtm-product-brand, data-gtm-product-sku_id.
Name format: "Brand MODEL STORAGESIZE COLOR" (e.g., "Apple IPHONE 11 PRO 256GO GOLD").

Note: As of April 2026, all 86 products are "Momentanément indisponible".
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, classify_product, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://reunion.darty-dom.com/c/smartphone"

_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('.product-box-line-container');
    const products = [];
    const seen = new Set();

    cards.forEach(card => {
        const link = card.querySelector('a.gtm-product-link');
        if (!link) return;

        const sku = link.dataset.gtmProductSku_id || '';
        if (!sku || seen.has(sku)) return;
        seen.add(sku);

        const title = link.dataset.gtmProductTitle || '';
        const priceStr = link.dataset.gtmProductPrice || '';
        const price = parseFloat(priceStr);
        if (!title || isNaN(price)) return;

        const brand = link.dataset.gtmProductBrand || '';
        const href = link.href || '';

        // Image
        const img = card.querySelector('img.img-product');
        const imgUrl = img ? (img.dataset.src || img.src || null) : null;

        // Availability
        const outStock = card.querySelector('.product-disponibility.out-stock');
        const available = !outStock;

        products.push({ id: sku, name: title, price, brand, url: href, image: imgUrl, available });
    });

    return products;
}
"""

# Known color words at the end of Darty product names
_COLORS = {
    "noir", "blanc", "bleu", "rouge", "rose", "or", "gold", "silver",
    "argent", "vert", "jaune", "violet", "orchidee", "orchidée", "corail",
    "gris", "anthracite", "carbone", "polaire", "midnight", "green",
    "purple", "red", "black", "white", "space", "grey", "blue",
}


def _parse_darty_name(
    name: str, gtm_brand: str,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse Darty product name.

    Formats observed:
        'Apple IPHONE 11 PRO 256GO GOLD'
        'Samsung GALAXY S8 PLUS ARGENT POLAIRE'
        'Xiaomi REDMI NOTE 5 64GO NOIR'
        'Samsung A6+ 2018 BLACK'
        'Echo CLAP 2 ROUGE'
        'Nokia 105 KING BLEU'
        'IPHONE 14 RECON GRADE A 128GO MINUIT'
    """
    name = " ".join(name.split())

    # Brand from GTM data (reliable)
    brand = gtm_brand.strip().title() if gtm_brand else ""

    # Remove brand prefix from name for model extraction
    model_str = name
    if brand and model_str.lower().startswith(brand.lower()):
        model_str = model_str[len(brand):].strip()

    # Extract storage: NNGo or NN GO patterns
    storage = None
    storage_match = re.findall(r"(\d+)\s*GO\b", model_str, re.I)
    if storage_match:
        # Take the largest as storage (smaller might be RAM)
        storage = max(storage_match, key=lambda x: int(x)) + "GO"

    # Extract color: trailing words that are known colors
    words = model_str.split()
    color_words = []
    while words:
        w = words[-1]
        if w.lower().rstrip(".,") in _COLORS:
            color_words.insert(0, w)
            words.pop()
        else:
            break
    color = " ".join(color_words).title() if color_words else None

    # Model: everything after brand, minus storage and color
    model = " ".join(words)
    # Remove storage patterns from model
    model = re.sub(r"\b\d+\s*GO\b", "", model, flags=re.I)
    # Remove year patterns like "2017", "2018" at the end
    model = re.sub(r"\b20\d{2}\b", "", model)
    # Remove "RECON GRADE A" type suffixes
    model = re.sub(r"\bRECON\b.*$", "", model, flags=re.I)
    # Remove "5G", "4G" from model
    model = re.sub(r"\b[45]G\+?\b", "", model)
    # Remove edition markers like "BS", "LS"
    model = re.sub(r"\b[A-Z]{2}\b$", "", model)
    # Clean up
    model = re.sub(r"\s+", " ", model).strip(" -+,/")

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """Scrape Darty Réunion smartphone catalogue via pagination."""
    results: list[PhoneData] = []
    seen_ids: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        # Load page 1
        logger.info("Loading Darty Réunion catalogue page 1…")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector(".product-box-line-container", timeout=15000)
        await asyncio.sleep(2)

        # Dismiss cookie consent if present
        try:
            accept_btn = page.locator("text=ACCEPTER")
            if await accept_btn.count() > 0:
                await accept_btn.first.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Detect max page from pagination links
        max_page = await page.evaluate("""() => {
            let max = 1;
            document.querySelectorAll('a.page-link').forEach(a => {
                const m = a.href.match(/[?&]page=(\\d+)/);
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

        # Pages 2..max_page
        for page_num in range(2, max_page + 1):
            url = f"{BASE_URL}?page={page_num}"
            logger.info("Loading page %d: %s", page_num, url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(".product-box-line-container", timeout=15000)
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
        brand, model, storage, color = _parse_darty_name(raw["name"], raw.get("brand", ""))

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
            "[%d/%d] %s (%.2f€) [%s]%s",
            i + 1, len(all_raw), phone.name, phone.price_nu or 0,
            phone.product_type,
            " REFURB" if phone.is_refurbished else "",
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
