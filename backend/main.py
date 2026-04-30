import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Phone, PlanPrice, PriceSnapshot, ScrapeRun
from scrapers import persist_results, get_scraper, OPERATORS, classify_product, detect_refurbished

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory progress store: {run_id: {phones_found, phones_scraped}}
_progress: dict[int, dict] = {}


def _migrate_product_type():
    """Add product_type and is_refurbished columns if missing, classify existing rows."""
    from database import SessionLocal
    from sqlalchemy import text, inspect as sa_inspect

    db = SessionLocal()
    try:
        inspector = sa_inspect(db.bind)
        cols = [c["name"] for c in inspector.get_columns("phones")]
        if "product_type" not in cols:
            logger.info("Migrating: adding product_type column…")
            db.execute(text("ALTER TABLE phones ADD COLUMN product_type VARCHAR(32) DEFAULT 'phone'"))
            db.commit()
        if "is_refurbished" not in cols:
            logger.info("Migrating: adding is_refurbished column…")
            db.execute(text("ALTER TABLE phones ADD COLUMN is_refurbished INTEGER DEFAULT 0"))
            db.commit()

        # Reclassify all products by brand + name
        all_products = db.query(Phone).all()
        updated = 0
        for p in all_products:
            pt = classify_product(p.brand, p.name)
            if p.product_type != pt:
                p.product_type = pt
                updated += 1
        if updated:
            db.commit()
            logger.info("Reclassified %d Zeop products", updated)

        # Detect refurbished on existing data based on name + page_url
        all_phones = db.query(Phone).all()
        refurb_count = 0
        for p in all_phones:
            is_ref = detect_refurbished(p.name, p.page_url or "")
            if is_ref != p.is_refurbished:
                p.is_refurbished = is_ref
                refurb_count += 1
        if refurb_count:
            db.commit()
            logger.info("Flagged %d products as refurbished", refurb_count)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _migrate_product_type()
    yield


app = FastAPI(title="Veille Terminaux", lifespan=lifespan)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
_allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class PlanPriceOut(BaseModel):
    plan_name: str
    price_monthly: Optional[float]
    price_device: Optional[float]
    engagement_months: Optional[int]

    class Config:
        from_attributes = True


class SnapshotOut(BaseModel):
    id: int
    scraped_at: datetime
    price_nu: Optional[float]
    promotion: Optional[str]
    plan_prices: list[PlanPriceOut]

    class Config:
        from_attributes = True


class PhoneOut(BaseModel):
    id: int
    sfr_id: Optional[str]
    name: str
    brand: str
    model: str
    storage: Optional[str]
    color: Optional[str]
    image_url: Optional[str]
    page_url: Optional[str]
    operator: str
    product_type: str
    is_refurbished: bool
    latest_snapshot: Optional[SnapshotOut]

    class Config:
        from_attributes = True


class ScrapeRunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    phones_found: int
    phones_scraped: int
    error_message: Optional[str]
    operator: str

    class Config:
        from_attributes = True


class ScrapeStatusOut(BaseModel):
    run_id: int
    status: str
    phones_found: int
    phones_scraped: int
    finished_at: Optional[datetime]
    error_message: Optional[str]
    operator: str


# ─── Background task ─────────────────────────────────────────────────────────

async def _do_scrape(run_id: int, operator: str):
    from database import SessionLocal

    db: Session = SessionLocal()
    try:
        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        if not run:
            return
        run.status = "running"
        db.commit()

        async def progress_cb(found: int, scraped: int):
            _progress[run_id] = {"phones_found": found, "phones_scraped": scraped}
            run2 = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run2:
                run2.phones_found = found
                run2.phones_scraped = scraped
                db.commit()

        run_scrape = get_scraper(operator)
        results = await run_scrape(on_progress=progress_cb)

        persist_results(results, db, run_id, operator)

        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        run.status = "done"
        run.phones_found = len(results)
        run.phones_scraped = len(results)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        _progress.pop(run_id, None)

    except Exception as e:
        logger.exception("Scrape run %d failed", run_id)
        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        if run:
            run.status = "error"
            run.error_message = str(e)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        _progress.pop(run_id, None)
    finally:
        db.close()


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/phones", response_model=list[PhoneOut])
def list_phones(
    brand: Optional[str] = None,
    search: Optional[str] = None,
    operator: Optional[str] = None,
    product_type: Optional[str] = None,
    is_refurbished: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Phone)
    if operator:
        query = query.filter(Phone.operator == operator)
    if product_type:
        query = query.filter(Phone.product_type == product_type)
    if is_refurbished is not None:
        query = query.filter(Phone.is_refurbished == is_refurbished)
    if brand:
        query = query.filter(Phone.brand.ilike(f"%{brand}%"))
    if search:
        query = query.filter(Phone.name.ilike(f"%{search}%"))
    phones = query.order_by(Phone.brand, Phone.name).all()

    result = []
    for phone in phones:
        latest = (
            db.query(PriceSnapshot)
            .filter(PriceSnapshot.phone_id == phone.id)
            .order_by(PriceSnapshot.scraped_at.desc())
            .first()
        )
        phone_out = PhoneOut(
            id=phone.id,
            sfr_id=phone.sfr_id,
            name=phone.name,
            brand=phone.brand,
            model=phone.model,
            storage=phone.storage,
            color=phone.color,
            image_url=phone.image_url,
            page_url=phone.page_url,
            operator=phone.operator,
            product_type=phone.product_type,
            is_refurbished=phone.is_refurbished,
            latest_snapshot=SnapshotOut(
                id=latest.id,
                scraped_at=latest.scraped_at,
                price_nu=latest.price_nu,
                promotion=latest.promotion,
                plan_prices=[
                    PlanPriceOut(
                        plan_name=pp.plan_name,
                        price_monthly=pp.price_monthly,
                        price_device=pp.price_device,
                        engagement_months=pp.engagement_months,
                    )
                    for pp in latest.plan_prices
                ],
            ) if latest else None,
        )
        result.append(phone_out)

    return result


@app.get("/phones/{phone_id}/history", response_model=list[SnapshotOut])
def phone_history(phone_id: int, db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")

    snapshots = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.phone_id == phone_id)
        .order_by(PriceSnapshot.scraped_at.asc())
        .all()
    )
    return [
        SnapshotOut(
            id=s.id,
            scraped_at=s.scraped_at,
            price_nu=s.price_nu,
            promotion=s.promotion,
            plan_prices=[
                PlanPriceOut(
                    plan_name=pp.plan_name,
                    price_monthly=pp.price_monthly,
                    price_device=pp.price_device,
                    engagement_months=pp.engagement_months,
                )
                for pp in s.plan_prices
            ],
        )
        for s in snapshots
    ]


@app.post("/scrape", response_model=ScrapeRunOut, status_code=202)
async def start_scrape(operator: str = "sfr_re", db: Session = Depends(get_db)):
    if operator not in OPERATORS:
        raise HTTPException(status_code=400, detail=f"Unknown operator: {operator}")

    # Check if a run is already in progress for this operator
    active = db.query(ScrapeRun).filter(
        ScrapeRun.status.in_(["pending", "running"]),
        ScrapeRun.operator == operator,
    ).first()
    if active:
        raise HTTPException(
            status_code=409, detail=f"A scrape run is already in progress (id={active.id})"
        )

    run = ScrapeRun(status="pending", operator=operator)
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(_do_scrape(run.id, operator))

    return run


@app.get("/scrape/runs", response_model=list[ScrapeRunOut])
def list_scrape_runs(db: Session = Depends(get_db)):
    runs = db.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(50).all()
    return runs


@app.delete("/scrape/{run_id}", status_code=200)
def cancel_scrape(run_id: int, db: Session = Depends(get_db)):
    run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Run is not in progress")
    run.status = "error"
    run.error_message = "Cancelled manually"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"detail": f"Run {run_id} cancelled"}


@app.get("/scrape/{run_id}", response_model=ScrapeStatusOut)
def scrape_status(run_id: int, db: Session = Depends(get_db)):
    run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Merge live in-memory progress
    live = _progress.get(run_id, {})
    return ScrapeStatusOut(
        run_id=run.id,
        status=run.status,
        phones_found=live.get("phones_found", run.phones_found),
        phones_scraped=live.get("phones_scraped", run.phones_scraped),
        finished_at=run.finished_at,
        error_message=run.error_message,
        operator=run.operator,
    )


@app.get("/brands")
def list_brands(operator: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Phone.brand).distinct()
    if operator:
        query = query.filter(Phone.operator == operator)
    brands = query.order_by(Phone.brand).all()
    return [b[0] for b in brands]


@app.get("/operators")
def list_operators():
    return [{"id": k, "label": v} for k, v in OPERATORS.items()]
