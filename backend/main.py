import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

_API_KEY = os.environ.get("API_KEY", "")

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    # Allow CORS preflight requests without auth
    if request.method == "OPTIONS":
        return await call_next(request)
    if _API_KEY:
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided, _API_KEY):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
_allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
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


class ScrapeHealthOut(BaseModel):
    operator: str
    label: str
    state: str  # "ko" | "warning"
    reason: str
    last_run_id: Optional[int]
    last_status: Optional[str]
    last_count: Optional[int]
    prev_count: Optional[int]
    last_at: Optional[datetime]


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
        query = query.filter(Phone.is_refurbished == int(is_refurbished))
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


# Below this ratio of the previous successful collection, a run is flagged as a
# suspicious volume drop (likely a partially-broken scraper) even if it ran "done".
_HEALTH_LOW_RATIO = 0.5


@app.get("/scrape/health", response_model=list[ScrapeHealthOut])
def scrape_health(db: Session = Depends(get_db)):
    """Per-operator health derived from each operator's most recent finished run.
    Surfaces scrapers that need investigation: last run errored, returned 0, or
    collected far fewer products than the previous successful run."""
    runs = (
        db.query(ScrapeRun)
        .filter(ScrapeRun.status.in_(["done", "error"]))
        .order_by(ScrapeRun.started_at.desc())
        .limit(300)
        .all()
    )
    by_op: dict[str, list[ScrapeRun]] = {}
    for r in runs:
        by_op.setdefault(r.operator, []).append(r)

    issues: list[ScrapeHealthOut] = []
    for op, label in OPERATORS.items():
        op_runs = by_op.get(op, [])
        if not op_runs:
            continue  # never collected — not an alert

        last = op_runs[0]  # most recent finished run
        state: Optional[str] = None
        reason = ""
        prev_count: Optional[int] = None

        if last.status == "error":
            state = "ko"
            msg = ""
            if last.error_message:
                msg = last.error_message.strip().splitlines()[0]
            reason = "Dernier run en erreur" + (f" — {msg[:140]}" if msg else "")
        elif last.phones_scraped == 0:
            state = "ko"
            reason = "Dernier run terminé avec 0 terminal"
        else:
            prev = next(
                (r for r in op_runs[1:] if r.status == "done" and r.phones_scraped > 0),
                None,
            )
            if prev and last.phones_scraped < prev.phones_scraped * _HEALTH_LOW_RATIO:
                state = "warning"
                prev_count = prev.phones_scraped
                drop = round((1 - last.phones_scraped / prev.phones_scraped) * 100)
                reason = (
                    f"Volume en forte baisse : {last.phones_scraped} "
                    f"vs {prev_count} précédemment (-{drop}%)"
                )

        if state:
            issues.append(
                ScrapeHealthOut(
                    operator=op,
                    label=label,
                    state=state,
                    reason=reason,
                    last_run_id=last.id,
                    last_status=last.status,
                    last_count=last.phones_scraped,
                    prev_count=prev_count,
                    last_at=last.finished_at or last.started_at,
                )
            )

    # KO first, then warnings, alphabetical within each group.
    issues.sort(key=lambda i: (i.state != "ko", i.label))
    return issues


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


@app.post("/import/orange", response_model=ScrapeRunOut)
async def import_orange_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    from scraper_orange import parse_orange_csv

    content = await file.read()
    try:
        results = parse_orange_csv(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    run = ScrapeRun(
        status="running",
        operator="orange_re",
        phones_found=len(results),
        phones_scraped=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        persist_results(results, db, run.id, "orange_re")
    except Exception as e:
        run.status = "error"
        run.error_message = str(e)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    run.status = "done"
    run.phones_scraped = len(results)
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run
