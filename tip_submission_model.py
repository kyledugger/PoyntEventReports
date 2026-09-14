from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class TipSubmission(Base):
    __tablename__ = "tip_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    submitted_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    store_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    store_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    report_start_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    report_end_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    total_tip_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    payout_method: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    submission_data: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
