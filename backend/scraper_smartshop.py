"""
Playwright scraper for SmartShop (smartshop.re) smartphone catalogue.

Strategy: SmartShop is a PrestaShop-based e-commerce site.
Products are listed on /3-smartphones with ?page=N pagination.
Only retail prices are available (no forfait/plan pricing).
Product IDs are extracted from URL paths: /brand/PRODUCT_ID-variant-slug.html
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://smartshop.re/3-smartphones"

# JavaScript executed in the browser context to extract product cards.
# PrestaShop product cards use article.js-product-miniature with specific CSS classes.
_EXTRACT_JS = """
() => {
    const products = [];
    const seen = new Set();

    document.querySelectorAll('article.js-product-miniature').forEach(card => {
        // Find the main product link (with href containing .html)
        const link = card.querySelector('a.product_img_link') || card.querySelector('a[href*=".html"]');
        if (!link) return;

        const href = link.getAttribute('href') || '';
        const match = href.match(/\\/[^/]+\\/(\\d+)(?:-\\d+)?-[^/]+\\.html/);
        if (!match) return;

        const productId = match[1];
        if (seen.has(productId)) return;
        seen.add(productId);

        // Product name from link title attribute or h3
        let name = link.getAttribute('title') || '';
        if (!name) {
            const h = card.querySelector('h3, h2, .product-title');
            if (h) name = h.textContent.trim();
        }

        // Current price from .price element
        let price = null;
        const priceEl = card.querySelector('.price');
        if (priceEl) {
            const m = priceEl.textContent.match(/([\\d\\s]+,\\d{2})/);
            if (m) price = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        // Original (crossed-out) price from .regular-price element
        let originalPrice = null;
        const regEl = card.querySelector('.regular-price');
        if (regEl) {
            const m = regEl.textContent.match(/([\\d\\s]+,\\d{2})/);
            if (m) originalPrice = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        // Image
        const img = card.querySelector('img');
        let imgUrl = null;
        if (img) {
            imgUrl = img.getAttribute('data-full-size-image-url')
                  || img.getAttribute('data-src')
                  || img.getAttribute('src')
                  || null;
        }

        // Full URL (strip fragment for clean storage)
        const cleanUrl = href.split('#')[0];
        const fullUrl = cleanUrl.startsWith('http') ? cleanUrl
            : 'https://smartshop.re' + (cleanUrl.startsWith('/') ? '' : '/') + cleanUrl;

        if (name && price !== null) {
            products.push({ id: productId, name: name.trim(), price, originalPrice, image: imgUrl, url: fullUrl });
        }
    });

    return products;
}
"""

def _parse_smartshop_name(
    name: str,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse PrestaShop product name into (brand, model, storage, color).

    Examples:
        'Apple iPhone 16 Pro Max 256Go'     → (Apple, iPhone 16 Pro Max, 256GO, None)
        'Samsung Galaxy S25 Ultra 512Go'    → (Samsung, Galaxy S25 Ultra, 512GO, None)
        'Xiaomi 15 Ultra'                   → (Xiaomi, 15 Ultra, None, None)
    """
    # Clean up extra whitespace
    name = " ".join(name.split())

    words = name.split()
    if not words:
        return name, "", None, None

    brand = words[0]
    rest = " ".join(words[1:])

    # Extract storage (e.g. 128Go, 256 Go, 1To, 512GB)
    storage = None
    storage_match = re.search(r"(\d+)\s*(Go|To|GB|TB)\b", rest, re.I)
    if storage_match:
        storage = (storage_match.group(1) + storage_match.group(2).upper()).replace(" ", "")
        rest = rest[: storage_match.start()].rstrip(" -") + rest[storage_match.end() :]

    # Extract color — common colors at the end after a dash or standalone
    color = None
    color_pattern = re.compile(
        r"[-–]\s*("
        r"noir|blanc|bleu|rouge|vert|rose|gris|argent|or|violet|jaune|orange|"
        r"black|white|blue|red|green|pink|gray|grey|silver|gold|purple|yellow|"
        r"titanium|graphite|midnight|starlight|cream|lavender|mint"
        r")\s*$",
        re.I,
    )
    color_match = color_pattern.search(rest)
    if color_match:
        color = color_match.group(1).strip()
        rest = rest[: color_match.start()].rstrip()

    model = rest.strip(" -–")

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """
    Scrape SmartShop smartphone catalogue.
    Returns list of PhoneData with price_nu only (no plan prices).
    """
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Loading SmartShop catalogue…")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.error("Failed to load SmartShop: %s", e)
            await browser.close()
            raise

        # Crawl pages until one yields no new products, instead of trusting a
        # max-page link read from the first page: if the pagination block hadn't
        # rendered yet (slow load), max_page came back as 1 and the scraper silently
        # collected only the first page (e.g. 9 instead of ~154), still marking the
        # run DONE. Crawling until exhaustion is immune to that race. PrestaShop
        # clamps out-of-range ?page=N to the last page, so a duplicate page (0 new)
        # cleanly signals the end.
        all_raw: list[dict] = []
        seen_ids: set[str] = set()

        MAX_PAGES = 100  # safety cap against an infinite loop
        page_num = 1
        while page_num <= MAX_PAGES:
            if page_num > 1:
                logger.info("Fetching page %d…", page_num)
                await page.goto(f"{BASE_URL}?page={page_num}", wait_until="networkidle", timeout=30000)
                await asyncio.sleep(0.5)

            products = await page.evaluate(_EXTRACT_JS)
            new_count = 0
            for p in products:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    all_raw.append(p)
                    new_count += 1

            logger.info("Page %d: %d product(s), %d new", page_num, len(products), new_count)

            if page_num > 1 and new_count == 0:
                logger.info("No new products on page %d — stopping.", page_num)
                break

            page_num += 1

        logger.info("Total products found: %d", len(all_raw))
        await browser.close()

    if on_progress:
        await on_progress(len(all_raw), 0)

    for i, raw in enumerate(all_raw):
        brand, model, storage, color = _parse_smartshop_name(raw["name"])

        # Build promotion string from original price
        promotion = None
        if raw.get("originalPrice"):
            discount = raw["originalPrice"] - raw["price"]
            promotion = f"-{discount:.2f}€ (au lieu de {raw['originalPrice']:.2f}€)"

        phone = PhoneData(
            vendor_id=raw["id"],
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
            "[%d/%d] %s (%.2f€%s)",
            i + 1,
            len(all_raw),
            phone.name,
            phone.price_nu or 0,
            f" promo: {promotion}" if promotion else "",
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
