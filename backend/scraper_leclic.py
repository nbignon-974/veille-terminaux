"""
Playwright scraper for Leclic.re (leclic.re) smartphone catalogue.

Strategy: Leclic.re is a Sylius-based marketplace (Wishibam platform).
Products are listed at /taxons/.../telephone-mobile with ?page=N pagination.
Only retail prices are available (no forfait/plan pricing).
Product IDs are UUIDs at the end of product URLs.
Cards use Semantic UI (.ui.fluid.card).
Note: requires ignore_https_errors=True (certificate mismatch on www subdomain).
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://leclic.re/taxons/electromenager-high-tech/high-tech-12/telephonie-3/telephone-mobile"

# JavaScript to extract product data from Semantic UI cards.
_EXTRACT_JS = """
() => {
    const products = [];
    const seen = new Set();

    document.querySelectorAll('.ui.fluid.card').forEach(card => {
        const link = card.querySelector('a[href*="/products/"]');
        if (!link) return;
        const href = link.getAttribute('href') || '';

        // Extract UUID from URL
        const uuidMatch = href.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/);
        const productId = uuidMatch ? uuidMatch[1] : href;
        if (seen.has(productId)) return;
        seen.add(productId);

        // Brand from dedicated span
        const brandEl = card.querySelector('.cityTheme-product-list-brand');
        const brand = brandEl ? brandEl.textContent.trim() : '';

        // Full header text: "Brand - Model details"
        const header = card.querySelector('.header');
        let name = header ? header.textContent.replace(/\\s+/g, ' ').trim() : '';

        // Current price
        let price = null;
        const priceEl = card.querySelector('.cityTheme-product-price b');
        if (priceEl) {
            const m = priceEl.textContent.replace(/\\u00a0/g, ' ').match(/([\\d\\s]+,\\d{2})/);
            if (m) price = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        // Original (barré) price
        let originalPrice = null;
        const origEl = card.querySelector('.cityTheme-product-original-price-box');
        if (origEl) {
            const m = origEl.textContent.replace(/\\u00a0/g, ' ').match(/([\\d\\s]+,\\d{2})/);
            if (m) originalPrice = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        // Image
        const img = card.querySelector('img');
        let imgUrl = img ? (img.getAttribute('data-src') || img.getAttribute('src')) : null;

        // Full URL
        const fullUrl = href.startsWith('http') ? href : 'https://leclic.re' + href;

        if (name && price !== null) {
            products.push({ id: productId, name, brand, price, originalPrice, image: imgUrl, url: fullUrl });
        }
    });

    return products;
}
"""

# Discover max page number from pagination links.
_MAX_PAGE_JS = """
() => {
    let maxPage = 1;
    document.querySelectorAll('a[href*="page="]').forEach(link => {
        const href = link.getAttribute('href') || '';
        const match = href.match(/[?&]page=(\\d+)/);
        if (match) {
            const p = parseInt(match[1]);
            if (p > maxPage) maxPage = p;
        }
    });
    return maxPage;
}
"""

# Common color tokens for extraction
_COLORS = {
    "noir", "blanc", "bleu", "rouge", "vert", "rose", "gris", "argent",
    "or", "violet", "jaune", "orange", "black", "white", "blue", "red",
    "green", "pink", "gray", "grey", "silver", "gold", "purple", "yellow",
    "titanium", "graphite", "midnight", "starlight", "cream", "lavender",
    "mint", "navy", "corail", "beige", "turquoise", "bronze", "lime",
    "blc", "nuit",
}

# Short color abbreviations used by leclic.re
_COLOR_ABBREV = {
    "blc": "Blanc",
    "nuit": "Nuit",
}


def _parse_leclic_name(
    raw_name: str, brand_hint: str
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse leclic.re product name into (brand, model, storage, color).

    Header format: "Brand - Model details"
    Examples:
        'Apple - Iphone 14 gradea+ 128g 5g noir'
        'Samsung - Samsung a07 64go noir'
        'Xiaomi - Xiaomi redmi a3 17 cm (6.71") double sim ...'
    """
    brand = brand_hint.strip() if brand_hint else ""

    # Remove "Brand - " prefix
    name = raw_name
    if " - " in name:
        name = name.split(" - ", 1)[1].strip()

    # Remove duplicate brand at start of model (e.g. "Samsung - Samsung a07")
    if brand and name.lower().startswith(brand.lower()):
        name = name[len(brand):].strip()

    words = name.split()
    if not words:
        return brand or raw_name, "", None, None

    # Extract storage (e.g. 128g, 64go, 256go, 128gb, 512o)
    storage = None
    color = None
    model_words = []
    skip_next = False

    for j, w in enumerate(words):
        if skip_next:
            skip_next = False
            continue
        wl = w.lower().rstrip("+")
        # "128go", "64gb", "128g", "256o"
        if re.match(r"^\d+(?:go|gb|g|to|tb|o)$", wl, re.I) and storage is None:
            # Normalize storage
            m = re.match(r"^(\d+)", w)
            val = m.group(1) if m else w
            storage = val + "GO"
            continue
        # "256 go" (two tokens)
        if re.match(r"^\d+$", w) and j + 1 < len(words) and re.match(r"^(?:go|gb|g|to|tb|o)$", words[j + 1], re.I):
            storage = w + "GO"
            skip_next = True
            continue
        # Color detection
        if wl in _COLORS and color is None:
            color = _COLOR_ABBREV.get(wl, w.capitalize())
            continue
        model_words.append(w)

    # Filter out noise tokens (5g, gradea+, etc. are kept as model info)
    model = " ".join(model_words).strip(" -–")

    # Title-case brand
    if brand:
        brand = brand.strip().title()

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """
    Scrape Leclic.re smartphone catalogue.
    Returns list of PhoneData with price_nu only (no plan prices).
    """
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        logger.info("Loading Leclic.re catalogue...")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.error("Failed to load Leclic.re: %s", e)
            await browser.close()
            raise

        # Discover total pages
        max_page = await page.evaluate(_MAX_PAGE_JS)
        page_urls = [f"{BASE_URL}?page={p}" for p in range(1, max_page + 1)]

        total_pages = len(page_urls)
        logger.info("Found %d page(s) to scrape", total_pages)

        all_raw: list[dict] = []
        seen_ids: set[str] = set()

        for i, url in enumerate(page_urls):
            if i > 0:
                logger.info("Fetching page %d/%d...", i + 1, total_pages)
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(0.5)

            products = await page.evaluate(_EXTRACT_JS)
            for p in products:
                pid = str(p["id"])
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_raw.append(p)

        logger.info("Total products found: %d", len(all_raw))
        await browser.close()

    if on_progress:
        await on_progress(len(all_raw), 0)

    for i, raw in enumerate(all_raw):
        brand, model, storage, color = _parse_leclic_name(raw["name"], raw.get("brand", ""))

        # Build promotion string
        promotion = None
        if raw.get("originalPrice"):
            discount = raw["originalPrice"] - raw["price"]
            promotion = f"-{discount:.2f}E (au lieu de {raw['originalPrice']:.2f}E)"

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
            promotion=promotion,
            product_type="phone",
            is_refurbished=detect_refurbished(raw["name"], raw.get("url", "")),
            plan_prices=[],
        )
        results.append(phone)
        logger.info(
            "[%d/%d] %s (%.2fE%s)",
            i + 1,
            len(all_raw),
            phone.name,
            phone.price_nu or 0,
            f" promo: {promotion}" if promotion else "",
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
