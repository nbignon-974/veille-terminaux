"""
Playwright scraper for Zeop Store (zeopstore.re) product catalogue.

Strategy: Zeop Store is a traditional server-rendered e-commerce site.
Products are in HTML cards on /smartphones with pagination.
Only retail prices are available (no forfait/plan pricing).
Product IDs are extracted from URL slugs: /product-slug,ID.htm
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, classify_product, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zeopstore.re/smartphones"

_EXTRACT_JS = """
() => {
    const products = [];
    const seen = new Set();

    document.querySelectorAll('a[href$=".htm"]').forEach(link => {
        const href = link.getAttribute('href') || '';
        const match = href.match(/([^/]+),(\\d+)\\.htm$/);
        if (!match) return;

        const [, slug, id] = match;
        if (seen.has(id)) return;
        seen.add(id);

        // Walk up to find card container with img + price
        let card = link;
        for (let el = link.parentElement; el && el.tagName !== 'BODY'; el = el.parentElement) {
            if (el.querySelector('img') && /\\d+[.,]\\d{2}\\s*€/.test(el.textContent)) {
                card = el;
                break;
            }
        }

        const img = card.querySelector('img');
        let imgUrl = null;
        if (img) {
            imgUrl = img.getAttribute('data-src') || img.getAttribute('src') || null;
            if (imgUrl && imgUrl.includes('loader.svg')) imgUrl = null;
        }

        let name = (img && img.getAttribute('alt')) || '';
        if (!name) name = link.textContent.trim().split('\\n')[0].trim();

        const priceMatch = card.textContent.match(/([\\d\\s]+,\\d{2})\\s*€/);
        let price = null;
        if (priceMatch) {
            price = parseFloat(priceMatch[1].replace(/\\s/g, '').replace(',', '.'));
        }

        const fullUrl = href.startsWith('http') ? href
            : 'https://www.zeopstore.re' + (href.startsWith('/') ? '' : '/') + href;

        if (name && price !== null) {
            products.push({ id, name: name.trim(), price, image: imgUrl, url: fullUrl });
        }
    });

    return products;
}
"""

_PAGINATION_JS = """
() => {
    const pages = [];
    document.querySelectorAll('a').forEach(link => {
        const text = link.textContent.trim();
        const href = link.getAttribute('href') || '';
        if (/^\\d+$/.test(text) && parseInt(text) > 1 && href && href !== '#') {
            pages.push({ page: parseInt(text), href });
        }
    });
    return pages.sort((a, b) => a.page - b.page);
}
"""


def _parse_zeop_name(name: str) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse 'Samsung S26 Ultra, Bleu, 256 Go' → (brand, model, storage, color)."""
    parts = [p.strip() for p in name.split(",")]

    first_words = parts[0].split()
    brand = first_words[0] if first_words else name
    model = " ".join(first_words[1:]) if len(first_words) > 1 else ""

    storage = None
    color = None
    storage_re = re.compile(r"^\d+\s*(?:Go|To|GB|TB)$", re.I)
    skip = {"5G", "4G", "4G+", "Wi-FI", "Wi-Fi", "A+", "EE"}

    for p in parts[1:]:
        p = p.strip()
        if storage_re.match(p):
            storage = p.upper().replace(" ", "")
        elif p in skip:
            continue
        elif not color:
            color = p

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """
    Scrape Zeop Store smartphone catalogue.
    Returns list of PhoneData with price_nu only (no plan prices).
    """
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Loading Zeop Store catalogue…")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)

        # Discover pagination
        pagination = await page.evaluate(_PAGINATION_JS)
        page_urls = [BASE_URL]
        for pg in pagination:
            href = pg["href"]
            if not href.startswith("http"):
                href = "https://www.zeopstore.re" + ("" if href.startswith("/") else "/") + href
            page_urls.append(href)

        total_pages = len(page_urls)
        logger.info("Found %d pages to scrape", total_pages)

        all_raw: list[dict] = []
        seen_ids: set[str] = set()

        for i, url in enumerate(page_urls):
            if i > 0:
                logger.info("Fetching page %d/%d…", i + 1, total_pages)
                await page.goto(url, wait_until="networkidle", timeout=30000)

            products = await page.evaluate(_EXTRACT_JS)
            for p in products:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    all_raw.append(p)

            await asyncio.sleep(0.5)

        logger.info("Total products found: %d", len(all_raw))
        await browser.close()

    if on_progress:
        await on_progress(len(all_raw), 0)

    for i, raw in enumerate(all_raw):
        brand, model, storage, color = _parse_zeop_name(raw["name"])
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
            promotion=None,
            product_type=classify_product(brand, raw["name"]),
            is_refurbished=detect_refurbished(raw["name"], raw.get("url", "")),
            plan_prices=[],
        )
        results.append(phone)
        logger.info(
            "[%d/%d] %s (%.2f€)",
            i + 1, len(all_raw), phone.name, phone.price_nu or 0,
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
