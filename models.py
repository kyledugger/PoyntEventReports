from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
        nullable=False
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    poynt_connection: Mapped["PoyntConnection | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )


class PoyntConnection(Base):
    __tablename__ = "poynt_connections"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "business_id",
            name="uq_poynt_connection_user_business"
        ),
    )    

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    business_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    access_token: Mapped[str] = mapped_column(
        String(4096),
        nullable=False
    )

    refresh_token: Mapped[str | None] = mapped_column(
        String(4096),
        nullable=True
    )

    token_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    user: Mapped["User"] = relationship(
        back_populates="poynt_connection"
    )