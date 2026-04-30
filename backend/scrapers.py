"""
Scraper registry and common types for multi-vendor price monitoring.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

OPERATORS = {
    "sfr_re": "SFR Réunion",
    "zeop": "Zeop Store",
    "smartshop": "SmartShop",
    "phenix": "Phenix Store",
    "leclic": "Leclic.re",
    "bvallee": "Bureau Vallée",
    "ravate": "Ravate",
    "infinytech": "Infinytech",
    "distripc": "DistriPC",
    "darty": "Darty Réunion",
}


@dataclass
class PlanPriceData:
    plan_name: str
    price_monthly: Optional[float] = None
    price_device: Optional[float] = None
    engagement_months: Optional[int] = None


# Brands known to be phone/terminal manufacturers
PHONE_BRANDS = {
    "apple", "samsung", "xiaomi", "honor", "huawei", "google", "oppo",
    "motorola", "crosscall", "nokia", "altice", "mobiwire", "zte",
    "blackview", "iphone", "realme", "oneplus", "nothing", "cmf", "fairphone",
    "vivo", "sony", "asus", "poco", "tcl", "wiko", "doro",
    "htc", "redmagic", "nubia", "ulefone", "konrow", "beafon",
    "refé", "refe", "logicom", "binom", "energizer",
    "echo", "itworks", "wiko",
}


import re as _re

_ACCESSORY_KEYWORDS = _re.compile(
    r"\b(?:watch|montre|bracelet|smart\s*band|band\s*\d"
    r"|airtags?|air\s*tags?|airpods?|earpods?|buds|pencil"
    r"|casque|écouteurs?|enceinte|speaker|haut.parleur"
    r"|chargeur|adaptateur|câble|coque|étui|housse"
    r"|ipad|tablette|tablet|mediapad|galaxy\s*tab"
    r"|caméra|camera|ampoule|smart\s*clock|assistant\s*connect)"
    r"\b",
    _re.IGNORECASE,
)


_PHONE_NAME_PATTERNS = _re.compile(
    r"^(?:iphone|smartphone|gsm)\b", _re.IGNORECASE,
)


def classify_product(brand: str, name: str = "") -> str:
    """Return 'phone' if brand is a known phone maker and name has no accessory keywords, else 'accessory'."""
    if _ACCESSORY_KEYWORDS.search(name):
        return "accessory"
    if brand.lower() in PHONE_BRANDS:
        return "phone"
    if _PHONE_NAME_PATTERNS.search(name):
        return "phone"
    return "accessory"

_REFURBISHED_PATTERNS = _re.compile(
    r"reconditionn|\brec\b|\bgrade\s*a|\brenewed\b|\brefurb|\boccasion\b",
    _re.IGNORECASE,
)


def detect_refurbished(name: str, url: str = "") -> bool:
    """Return True if the product name or URL indicates a refurbished item."""
    return bool(
        _REFURBISHED_PATTERNS.search(name)
        or "/reconditionne/" in url.lower()
    )


@dataclass
class PhoneData:
    vendor_id: Optional[str]
    name: str
    brand: str
    model: str
    storage: Optional[str]
    color: Optional[str]
    image_url: Optional[str]
    page_url: Optional[str]
    price_nu: Optional[float]
    promotion: Optional[str]
    product_type: str = "phone"
    is_refurbished: bool = False
    plan_prices: list[PlanPriceData] = field(default_factory=list)


def get_scraper(operator: str):
    """Return the run_scrape coroutine for the given operator."""
    if operator == "sfr_re":
        from scraper_sfr import run_scrape
        return run_scrape
    elif operator == "zeop":
        from scraper_zeop import run_scrape
        return run_scrape
    elif operator == "smartshop":
        from scraper_smartshop import run_scrape
        return run_scrape
    elif operator == "phenix":
        from scraper_phenix import run_scrape
        return run_scrape
    elif operator == "leclic":
        from scraper_leclic import run_scrape
        return run_scrape
    elif operator == "bvallee":
        from scraper_bvallee import run_scrape
        return run_scrape
    elif operator == "ravate":
        from scraper_ravate import run_scrape
        return run_scrape
    elif operator == "infinytech":
        from scraper_infinytech import run_scrape
        return run_scrape
    elif operator == "distripc":
        from scraper_distripc import run_scrape
        return run_scrape
    elif operator == "darty":
        from scraper_darty import run_scrape
        return run_scrape
    else:
        raise ValueError(f"Unknown operator: {operator}")


def persist_results(results: list[PhoneData], db, scrape_run_id: int, operator: str) -> None:
    """Persist scraped phone data to the database."""
    from models import Phone, PlanPrice, PriceSnapshot

    scraped_at = datetime.now(timezone.utc)

    for data in results:
        if data.vendor_id:
            phone = db.query(Phone).filter(
                Phone.sfr_id == data.vendor_id,
                Phone.operator == operator,
            ).first()
        else:
            phone = db.query(Phone).filter(
                Phone.name == data.name,
                Phone.operator == operator,
            ).first()

        if not phone:
            phone = Phone(
                sfr_id=data.vendor_id,
                name=data.name,
                brand=data.brand,
                model=data.model,
                storage=data.storage,
                color=data.color,
                image_url=data.image_url,
                page_url=data.page_url,
                operator=operator,
                product_type=data.product_type,
                is_refurbished=int(data.is_refurbished),
            )
            db.add(phone)
            db.flush()
        else:
            phone.image_url = data.image_url or phone.image_url
            phone.page_url = data.page_url or phone.page_url
            phone.product_type = data.product_type
            phone.is_refurbished = int(data.is_refurbished)

        snapshot = PriceSnapshot(
            phone_id=phone.id,
            scrape_run_id=scrape_run_id,
            scraped_at=scraped_at,
            price_nu=data.price_nu,
            promotion=data.promotion,
            available=1,
        )
        db.add(snapshot)
        db.flush()

        for pp in data.plan_prices:
            plan_price = PlanPrice(
                snapshot_id=snapshot.id,
                plan_name=pp.plan_name,
                price_monthly=pp.price_monthly,
                price_device=pp.price_device,
                engagement_months=pp.engagement_months,
            )
            db.add(plan_price)

    db.commit()
