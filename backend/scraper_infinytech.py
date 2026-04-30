"""
Playwright scraper for Infinytech Réunion smartphone catalogue.

Strategy: Custom French CMS (cdnws.com CDN) with numbered pagination.
Products listed at /telephone-portable/, 20 per page, pages /telephone-portable/2 to /N.
Cards use article.prod__article with hidden inputs for price/brand/ID.
Name in a.prod__link title, price in input#shown-price-{id}, brand in input#brand-{id}.
Name format: "BRAND Model StorageGo Screen" IPxx Color"
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright

from scrapers import PhoneData, classify_product, detect_refurbished

logger = logging.getLogger(__name__)

BASE_URL = "https://www.infinytech-reunion.re/telephone-portable/"

_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('article.prod__article');
    const products = [];
    const seen = new Set();

    cards.forEach(card => {
        // Extract product ID from hidden input ids like "shown-price-{id}"
        const priceInput = card.querySelector('input[id^="shown-price-"]');
        if (!priceInput) return;
        const idMatch = priceInput.id.match(/shown-price-(\\d+)$/);
        if (!idMatch) return;
        const id = idMatch[1];
        if (seen.has(id)) return;
        seen.add(id);

        // Brand from hidden input
        const brandInput = card.querySelector('input[id^="brand-"]');
        const brand = brandInput ? brandInput.value : '';

        // Price from hidden input
        const priceStr = priceInput.value.replace(/\\s/g, '').replace(',', '.');
        const price = parseFloat(priceStr);
        if (isNaN(price)) return;

        // Original price (before promo)
        const nopromoInput = card.querySelector('input[id^="shown-price-no-promo-"]');
        let originalPrice = null;
        if (nopromoInput) {
            const op = parseFloat(nopromoInput.value.replace(/\\s/g, '').replace(',', '.'));
            if (!isNaN(op) && op > price) originalPrice = op;
        }

        // Name from link title
        const link = card.querySelector('a.prod__link');
        const name = link ? (link.getAttribute('title') || '').replace(/&quot;/g, '"') : '';
        const url = link ? link.href : '';

        // Image
        const img = card.querySelector('img.prod__img');
        let imgUrl = img ? img.getAttribute('src') : null;

        if (name && price > 0) {
            products.push({ id, name, brand, price, originalPrice, url, image: imgUrl });
        }
    });

    return products;
}
"""


def _parse_infinytech_name(
    name: str, brand_hint: str
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Parse Infinytech product name.

    Formats observed:
        'APPLE iPhone 16 128Go 6,1" IP68 Blanc'
        'BLACKVIEW BV4800 SE 4Go 64Go 6,56" 4G Noir'
        'BLACKVIEW WAVE 8C 2Go/64Go 6,56" 4G Bleu'
        'Câble BELKIN BoostCharge Lightning vers USB-A 1m Noir'
        'Adaptateur DEVIA Lightning vers Jack 3.5mm Blanc'
        'Smartphone KONROW Sky63 6,26" 4G Noir'
    """
    name = " ".join(name.split())

    # Brand: use brand_hint from the hidden input
    brand = brand_hint.strip().title() if brand_hint else ""
    if brand.lower() == "générique":
        brand = ""

    # Remove leading "Smartphone " or "Téléphone "
    clean = re.sub(r"^(?:Smartphone|Téléphone)\s+", "", name, flags=re.I)

    # Remove leading brand (all-caps) from the name for model extraction
    if brand:
        clean = re.sub(r"^" + re.escape(brand) + r"\s*", "", clean, flags=re.I)

    # Extract storage: "128Go", "256Go", "4Go/128Go" etc. — take the largest
    storage = None
    storage_matches = re.findall(r"(\d+)\s*Go\b", clean, re.I)
    if storage_matches:
        storage = max(storage_matches, key=lambda x: int(x)) + "GO"

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
    words = clean.split()
    for w in reversed(words):
        if w.lower().rstrip(".,") in colors:
            color = w.capitalize().rstrip(".,")
            break

    # Model: clean up the main part
    model = clean
    # Remove RAM/storage patterns
    model = re.sub(r"\d+Go/\d+\s*Go\b", "", model, flags=re.I)
    model = re.sub(r"\d+\s*Go\b", "", model, flags=re.I)
    # Remove screen size pattern like 6,1" or 6.56"
    model = re.sub(r'\d+[.,]\d+\s*"', "", model)
    # Remove IP rating like IP68
    model = re.sub(r"\bIP\d+\b", "", model, flags=re.I)
    # Remove network generation like 4G, 5G
    model = re.sub(r"\b[45]G\b", "", model)
    # Remove color
    if color:
        model = re.sub(r"\b" + re.escape(color) + r"\b", "", model, flags=re.I)
    # Remove "neuf", "reconditionné grade A+", etc.
    model = re.sub(r"\b(?:neuf|reconditionn[ée]+\s*(?:grade\s*\w+)?)\b", "", model, flags=re.I)
    # Clean up
    model = re.sub(r"\s+", " ", model).strip(" -–,")

    if not brand:
        # Try first word of original name as brand
        first_word = name.split()[0] if name.split() else "Unknown"
        if first_word[0].isupper():
            brand = first_word.title()

    return brand, model, storage, color


async def run_scrape(on_progress=None) -> list[PhoneData]:
    """Scrape Infinytech Réunion telephone catalogue via pagination."""
    results: list[PhoneData] = []
    seen_ids: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        # Load page 1 to detect max pages
        logger.info("Loading Infinytech catalogue page 1…")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("article.prod__article", timeout=15000)
        await asyncio.sleep(2)

        # Dismiss cookie consent if present
        try:
            accept_btn = page.locator("text=Tout accepter")
            if await accept_btn.count() > 0:
                await accept_btn.first.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Detect max page from pagination links
        max_page = await page.evaluate("""() => {
            let max = 1;
            document.querySelectorAll('a').forEach(a => {
                const m = a.href.match(/telephone-portable\\/(\\d+)$/);
                if (m) { const n = parseInt(m[1]); if (n > max) max = n; }
            });
            return max;
        }""")
        logger.info("Detected %d pages", max_page)

        all_raw: list[dict] = []

        for page_num in range(1, max_page + 1):
            if page_num > 1:
                url = f"{BASE_URL}{page_num}"
                logger.info("Loading page %d: %s", page_num, url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector("article.prod__article", timeout=15000)
                await asyncio.sleep(1.5)

            page_raw: list[dict] = await page.evaluate(_EXTRACT_JS)
            # Deduplicate across pages
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
        brand, model, storage, color = _parse_infinytech_name(
            raw["name"], raw.get("brand", "")
        )

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
