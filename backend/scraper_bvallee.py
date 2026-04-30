"""
Playwright scraper for Bureau Vallée Réunion (bureau-vallee.re) smartphone catalogue.

Strategy: Custom e-commerce frontend with .c-productCard cards.
Products listed at /fr_RE/.../smartphones.html with ?p=N pagination.
Only retail prices (TTC). Product IDs from card class c-productCard-{id}.
Title format: "Brand Model - Smartphone - 5G - RAM/Storage Go - Color"
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bureau-vallee.re/fr_RE/telephonie-mobilite/telephonie-et-tablettes/smartphones.html"

_EXTRACT_JS = """
() => {
    const products = [];
    const seen = new Set();

    document.querySelectorAll('.c-productCard').forEach(card => {
        // Product ID from class name c-productCard-XXXXXXXXX
        let productId = null;
        const idMatch = card.className.match(/c-productCard-(\\d+)/);
        if (idMatch) productId = idMatch[1];
        if (!productId) return;
        if (seen.has(productId)) return;
        seen.add(productId);

        // Title
        const titleEl = card.querySelector('.c-productCard__title');
        const name = titleEl ? titleEl.textContent.trim() : '';

        // Price from .c-price__price
        let price = null;
        const priceEl = card.querySelector('.c-price__price');
        if (priceEl) {
            const m = priceEl.textContent.replace(/\\u00a0/g, ' ').match(/([\\d\\s]+,\\d{2})/);
            if (m) price = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        // Image from img inside picture
        const img = card.querySelector('picture img');
        let imgUrl = img ? img.getAttribute('src') : null;

        // Link
        const link = card.querySelector('a.c-productCard__img, a[href*=".html"]');
        const href = link ? link.getAttribute('href') : '';
        const fullUrl = href.startsWith('http') ? href
            : 'https://www.bureau-vallee.re' + (href.startsWith('/') ? '' : '/') + href;

        if (name && price !== null) {
            products.push({ id: productId, name, price, image: imgUrl, url: fullUrl });
        }
    });

    return products;
}
"""

_MAX_PAGE_JS = """
() => {
    let maxPage = 1;
    document.querySelectorAll('a[href*="p="]').forEach(link => {
        const href = link.getAttribute('href') || '';
        const match = href.match(/[?&]p=(\\d+)/);
        if (match) {
            const p = parseInt(match[1]);
            if (p > maxPage) maxPage = p;
        }
    });
    return maxPage;
}
"""

_COLORS = {
    "noir", "blanc", "bleu", "rouge", "vert", "rose", "gris", "argent",
    "or", "violet", "jaune", "orange", "black", "white", "blue", "red",
    "green", "pink", "gray", "grey", "silver", "gold", "purple", "yellow",
    "titanium", "graphite", "midnight", "starlight", "cream", "lavender",
    "mint", "navy", "corail", "beige", "turquoise", "bronze", "lime",
}


def _parse_bvallee_name(
    name: str,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse Bureau Vallée product name.

    Format: "Brand Model - Smartphone - 5G - RAM/Storage Go - Color"
    Examples:
        'Samsung Galaxy A37 - Smartphone - 5G - 6/128 Go - Blanc'
        'Xiaomi Redmi A5 - Smartphone - 4G - 4/128 Go - noir'
        'Samsung Galaxy S26 Ultra - Smartphone - 5G - 12/256 Go - Noir'
    """
    name = " ".join(name.split())

    # Split on " - " separators
    parts = [p.strip() for p in name.split(" - ")]

    brand = ""
    model_part = parts[0] if parts else name
    color = None
    storage = None

    # First word of first part is the brand
    words = model_part.split()
    if words:
        brand = words[0]
        model_part = " ".join(words[1:])

    # Look for color in the last part (single or multi-word like "Bleu ciel")
    if parts:
        last = parts[-1].strip()
        last_lower = last.lower()
        # Check exact match first, then check if first word is a known color
        if last_lower in _COLORS:
            color = last.capitalize()
            parts = parts[:-1]
        elif last_lower.split()[0] in _COLORS:
            color = last.title()
            parts = parts[:-1]

    # Look for storage pattern "RAM/Storage Go" in parts
    for part in parts:
        m = re.match(r"(\d+)/(\d+)\s*Go", part, re.I)
        if m:
            storage = m.group(2) + "GO"
            break
        m2 = re.match(r"(\d+)\s*Go", part, re.I)
        if m2:
            storage = m2.group(1) + "GO"
            break

    # Remove "Smartphone" and connectivity parts from model
    model_words = []
    for p in parts[1:]:  # skip the brand+model part
        pl = p.lower().strip()
        if pl in ("smartphone", "4g", "5g", "3g"):
            continue
        if re.match(r"\d+/\d+\s*go", pl, re.I):
            continue
        if pl.lower() in _COLORS:
            continue
        model_words.append(p)

    model = model_part
    if model_words:
        model = model_part + " " + " ".join(model_words)
    model = model.strip(" -")

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """Scrape Bureau Vallée Réunion smartphone catalogue."""
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Loading Bureau Vallee catalogue...")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.error("Failed to load Bureau Vallee: %s", e)
            await browser.close()
            raise

        max_page = await page.evaluate(_MAX_PAGE_JS)
        page_urls = [f"{BASE_URL}?p={p}" for p in range(1, max_page + 1)]

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
        brand, model, storage, color = _parse_bvallee_name(raw["name"])

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
            product_type="phone",
            is_refurbished=detect_refurbished(raw["name"], raw.get("url", "")),
            plan_prices=[],
        )
        results.append(phone)
        logger.info(
            "[%d/%d] %s (%.2fE)",
            i + 1, len(all_raw), phone.name, phone.price_nu or 0,
        )

        if on_progress:
            await on_progress(len(all_raw), i + 1)

    return results
