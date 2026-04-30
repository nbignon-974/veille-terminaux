from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Phone(Base):
    __tablename__ = "phones"

    __table_args__ = (UniqueConstraint("sfr_id", "operator", name="uq_phone_vendor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sfr_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(256))
    brand: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    storage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    page_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    operator: Mapped[str] = mapped_column(String(32), default="sfr_re")
    product_type: Mapped[str] = mapped_column(String(32), default="phone")
    is_refurbished: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        "PriceSnapshot", back_populates="phone", cascade="all, delete-orphan"
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_id: Mapped[int] = mapped_column(Integer, ForeignKey("phones.id"))
    scrape_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("scrape_runs.id"), nullable=True
    )
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    price_nu: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    promotion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    available: Mapped[bool] = mapped_column(Integer, default=1)

    phone: Mapped["Phone"] = relationship("Phone", back_populates="snapshots")
    plan_prices: Mapped[list["PlanPrice"]] = relationship(
        "PlanPrice", back_populates="snapshot", cascade="all, delete-orphan"
    )
    scrape_run: Mapped[Optional["ScrapeRun"]] = relationship(
        "ScrapeRun", back_populates="snapshots"
    )


class PlanPrice(Base):
    __tablename__ = "plan_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("price_snapshots.id")
    )
    plan_name: Mapped[str] = mapped_column(String(128))
    price_monthly: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_device: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engagement_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    snapshot: Mapped["PriceSnapshot"] = relationship(
        "PriceSnapshot", back_populates="plan_prices"
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator: Mapped[str] = mapped_column(String(32), default="sfr_re")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    phones_found: Mapped[int] = mapped_column(Integer, default=0)
    phones_scraped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        "PriceSnapshot", back_populates="scrape_run"
    )
