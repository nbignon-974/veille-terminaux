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


async def _trigger_lazy_prices(page):
    """Bureau Vallée renders prices lazily on scroll. Scroll the page top→bottom
    to force all .c-price__price to render, then wait for skeletons to clear."""
    height = await page.evaluate("document.body.scrollHeight")
    step = 800
    for y in range(0, height + step, step):
        await page.evaluate(f"window.scrollTo(0, {y})")
        await asyncio.sleep(0.3)
    try:
        await page.wait_for_function(
            "() => document.querySelectorAll('.c-productCard__priceWrapper .react-loading-skeleton').length === 0",
            timeout=10000,
        )
    except Exception:
        logger.warning("Some prices may still be skeleton-loading; extracting what's available")


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """Scrape Bureau Vallée Réunion smartphone catalogue."""
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        logger.info("Loading Bureau Vallee catalogue...")
        try:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(".c-productCard", timeout=15000)
            await _trigger_lazy_prices(page)
        except Exception as e:
            logger.error("Failed to load Bureau Vallee: %s", e)
            await browser.close()
            raise

        # Crawl pages sequentially until one yields no (new) products, rather than
        # trusting a max-page link — a stale "?p=N" link pointing past the last real
        # page made the scraper request an empty page, time out on .c-productCard and
        # crash the whole run (losing every product already collected). An empty page
        # now simply marks the end of pagination.
        all_raw: list[dict] = []
        seen_ids: set[str] = set()

        MAX_PAGES = 50  # safety cap against an infinite loop
        page_num = 1
        while page_num <= MAX_PAGES:
            if page_num > 1:
                logger.info("Fetching page %d...", page_num)
                await page.goto(f"{BASE_URL}?p={page_num}", wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_selector(".c-productCard", timeout=15000)
                except Exception:
                    logger.info("No products on page %d — end of pagination.", page_num)
                    break
                await _trigger_lazy_prices(page)

            products = await page.evaluate(_EXTRACT_JS)
            new_count = 0
            for p in products:
                pid = str(p["id"])
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_raw.append(p)
                    new_count += 1

            logger.info("Page %d: %d card(s), %d new", page_num, len(products), new_count)

            # End of catalogue (or a duplicate last page) once a page brings nothing new.
            if page_num > 1 and new_count == 0:
                logger.info("No new products on page %d — stopping.", page_num)
                break

            page_num += 1

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
