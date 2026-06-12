"""
Playwright scraper for Phenix Store (phenix-store.com) smartphone catalogue.

Strategy: Phenix Store is a PrestaShop-based e-commerce site.
Products are listed on /3-smartphones with ?page=N pagination.
Only retail prices are available (no forfait/plan pricing).
Product IDs come from data-id-product attribute on article elements.
Inventory mixes neuf + reconditionné + robuste phones.
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://phenix-store.com/3-smartphones"

# Extract product data from PrestaShop article cards.
_EXTRACT_JS = """
() => {
    const products = [];
    const seen = new Set();

    document.querySelectorAll('article.js-product-miniature, .product-miniature').forEach(card => {
        // Prefer data-id-product attribute for reliable product ID
        let productId = card.getAttribute('data-id-product');

        const link = card.querySelector('a[href*=".html"]');
        if (!link) return;
        const href = link.getAttribute('href') || '';

        // Fallback: extract ID from URL
        if (!productId) {
            const match = href.match(/\\/(\\d+)-[^/]+\\.html/);
            if (match) productId = match[1];
        }
        if (!productId) return;
        if (seen.has(productId)) return;
        seen.add(productId);

        // Product name. Phenix truncates the visible title server-side with a
        // literal "…" (and exposes no title/alt attribute), which loses the
        // storage/colour suffix. When that happens, rebuild the full name from the
        // URL slug, which carries the complete product name.
        let name = '';
        const titleEl = card.querySelector('.product-title a, h3 a, h2 a');
        if (titleEl) name = titleEl.textContent.trim();
        if (!name) name = link.getAttribute('title') || '';
        if (!name || /\\.\\.\\.|…/.test(name)) {
            const seg = (href.split('#')[0].split('?')[0].split('/').pop() || '');
            const slug = seg.replace(/\\.html$/, '')
                            .replace(/^\\d+-/, '')      // drop leading product id
                            .replace(/-\\d{8,}$/, '')   // drop trailing EAN/barcode
                            .replace(/-/g, ' ')
                            .trim();
            if (slug) name = slug;
        }

        // Current price from .price element
        let price = null;
        const priceEl = card.querySelector('.price');
        if (priceEl) {
            const m = priceEl.textContent.match(/([\\d\\s]+,\\d{2})/);
            if (m) price = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
        }

        // Original (crossed-out) price from .regular-price
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

        // Clean URL (strip fragment)
        const cleanUrl = href.split('#')[0];
        const fullUrl = cleanUrl.startsWith('http') ? cleanUrl
            : 'https://phenix-store.com' + (cleanUrl.startsWith('/') ? '' : '/') + cleanUrl;

        if (name && price !== null) {
            products.push({ id: productId, name: name.trim(), price, originalPrice, image: imgUrl, url: fullUrl });
        }
    });

    return products;
}
"""

# Common color names for extraction from product names
_COLORS = {
    "noir", "blanc", "bleu", "rouge", "vert", "rose", "gris", "argent",
    "or", "violet", "jaune", "orange", "black", "white", "blue", "red",
    "green", "pink", "gray", "grey", "silver", "gold", "purple", "yellow",
    "titanium", "graphite", "midnight", "starlight", "cream", "lavender",
    "mint", "sable", "corail", "beige", "turquoise", "bronze",
}


def _parse_phenix_name(
    name: str,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse Phenix Store product name into (brand, model, storage, color).

    Examples:
        'Apple iPhone 16E Noir 128Go'           → (Apple, iPhone 16E, 128GO, Noir)
        'Samsung Galaxy S25 Ultra 256 Go ...'    → (Samsung, Galaxy S25 Ultra, 256GO, None)
        'iPhone SE 2020 Reconditionné Blanc 64Go'→ (iPhone, SE 2020 Reconditionné, 64GO, Blanc)
        'Ulefone Armor X12 Pro 64GB Black'       → (Ulefone, Armor X12 Pro, 64GB, Black)
    """
    # Clean up extra whitespace
    name = " ".join(name.split())

    words = name.split()
    if not words:
        return name, "", None, None

    brand = words[0]
    rest_words = words[1:]

    # Extract storage (e.g. 128Go, 256 Go, 64GB, 1To)
    storage = None
    rest_rebuilt = []
    skip_next = False
    for j, w in enumerate(rest_words):
        if skip_next:
            skip_next = False
            continue
        # "128Go" or "64GB"
        if re.match(r"^\d+(?:Go|GB|To|TB)$", w, re.I):
            storage = w.upper()
            continue
        # "256 Go" (two tokens)
        if re.match(r"^\d+$", w) and j + 1 < len(rest_words) and re.match(r"^(?:Go|GB|To|TB)$", rest_words[j + 1], re.I):
            storage = (w + rest_words[j + 1]).upper()
            skip_next = True
            continue
        rest_rebuilt.append(w)

    # Extract color from remaining words
    color = None
    model_words = []
    for w in rest_rebuilt:
        if w.lower() in _COLORS and color is None:
            color = w
        else:
            model_words.append(w)

    # Strip trailing EAN (long digit string like 0195950051155)
    while model_words and re.match(r"^\d{8,}$", model_words[-1]):
        model_words.pop()

    model = " ".join(model_words).strip(" -–")

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """
    Scrape Phenix Store smartphone catalogue.
    Returns list of PhoneData with price_nu only (no plan prices).
    """
    results: list[PhoneData] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Loading Phenix Store catalogue…")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.error("Failed to load Phenix Store: %s", e)
            await browser.close()
            raise

        # Crawl pages until one yields no new products instead of trusting a max-page
        # link read from the first page (which, if the pagination block renders late,
        # comes back as 1 and silently collects only page 1). PrestaShop clamps
        # out-of-range ?page=N to the last page, so a duplicate page (0 new) marks the end.
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
                pid = str(p["id"])
                if pid not in seen_ids:
                    seen_ids.add(pid)
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
        brand, model, storage, color = _parse_phenix_name(raw["name"])

        # Build promotion string from original price
        promotion = None
        if raw.get("originalPrice"):
            discount = raw["originalPrice"] - raw["price"]
            promotion = f"-{discount:.2f}€ (au lieu de {raw['originalPrice']:.2f}€)"

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
