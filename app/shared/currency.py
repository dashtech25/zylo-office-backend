"""Référentiel monétaire commun (devises, taux de change) — Core.

Décision d'architecture (niveau_1_base_de_donnees_et_monetisation.md §17,
§25) : une devise ou un taux de change n'est pas une donnée spécifique à
Zylo Liquid — factorisés ici pour qu'un futur module (facturation,
comptabilité...) puisse les utiliser sans dépendre de Zylo Liquid.
Aucune isolation tenant : donnée globale au système."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Currency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "currency"
    __table_args__ = (
        UniqueConstraint("code", name="uq_currency_code"),
        CheckConstraint("code = upper(code)", name="ck_currency_code_upper"),
        {"comment": "Référentiel des devises — commun à tous les modules (Core). Source : niveau_1_base_de_donnees_et_monetisation.md §17."},
    )

    code: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    decimalPlaces: Mapped[int] = mapped_column(nullable=False, default=2)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class ExchangeRate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exchangeRate"
    __table_args__ = (
        UniqueConstraint("sourceCurrencyId", "targetCurrencyId", "effectiveFrom", name="uq_exchangeRate_pair_effectiveFrom"),
        CheckConstraint("rate > 0", name="ck_exchangeRate_rate_positive"),
        CheckConstraint('"sourceCurrencyId" != "targetCurrencyId"', name="ck_exchangeRate_distinct_currencies"),
        {
            "comment": "Taux de change historisé — toujours une insertion, jamais une correction (niveau_1_base_de_donnees_et_monetisation.md §22, invariant n°4)."
        },
    )

    sourceCurrencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False, index=True)
    targetCurrencyId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("currency.id", ondelete="RESTRICT"), nullable=False, index=True)
    rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    effectiveFrom: Mapped[datetime] = mapped_column(nullable=False, index=True)
