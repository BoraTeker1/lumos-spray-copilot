"""SQLAlchemy ORM models for Lumos Spray Copilot."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    # Two-letter market/country code, e.g. "US" or "TR". Drives PCA vs. agronomist wording.
    country: Mapped[str] = mapped_column(String(2), default="US")
    crop_type: Mapped[str] = mapped_column(String(100), default="greenhouse_tomato")
    greenhouse_area: Mapped[float | None] = mapped_column(Float)  # square metres
    planting_date: Mapped[date | None] = mapped_column(Date)
    expected_harvest_date: Mapped[date | None] = mapped_column(Date)

    spray_events: Mapped[list["SprayEvent"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    scout_observations: Mapped[list["ScoutObservation"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan"
    )


class SprayEvent(Base):
    __tablename__ = "spray_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    pesticide_class: Mapped[str | None] = mapped_column(String(100))
    target_pest_or_disease: Mapped[str | None] = mapped_column(String(200))
    dose: Mapped[str | None] = mapped_column(String(100))
    application_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost: Mapped[float | None] = mapped_column(Float)
    pre_harvest_interval_days: Mapped[int | None] = mapped_column(Integer)
    re_entry_interval_hours: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    farm: Mapped["Farm"] = relationship(back_populates="spray_events")


class ScoutObservation(Base):
    __tablename__ = "scout_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    crop_stage: Mapped[str | None] = mapped_column(String(100))
    visible_issue: Mapped[str | None] = mapped_column(String(200))
    severity_1_to_5: Mapped[int | None] = mapped_column(Integer)
    image_url_optional: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    farm: Mapped["Farm"] = relationship(back_populates="scout_observations")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    next_action: Mapped[str] = mapped_column(String(120), default="")
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    # agronomist workflow: pending / approved / rejected / edited
    agronomist_status: Mapped[str] = mapped_column(String(20), default="pending")
    agronomist_comment: Mapped[str | None] = mapped_column(Text)

    farm: Mapped["Farm"] = relationship(back_populates="recommendations")
