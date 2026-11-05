"""Tables du registre des réglages et de leur historique (BE-237).

- `settings_registry` : une ligne par réglage déclaré. La clé est l'identifiant stable.
  La portée, le propriétaire, la sensibilité et l'effet sont fermés en base (CHECK) :
  un réglage sans propriétaire ou hors portée connue ne peut pas exister, même si le code
  Python de déclaration était contourné (CA-1).
- `settings_history` : une ligne par modification. Elle garde l'ancienne et la nouvelle
  valeur, l'acteur et le motif. Une modification n'écrase jamais une ligne : la valeur
  courante d'une portée est la dernière entrée de cette table (voir app.settings.service).

Pour un réglage secret, `oldValue` et `newValue` contiennent le masque, jamais la valeur
en clair : l'historique est une table lisible par les administrateurs de portée.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin

# Portées fermées : seules ces valeurs sont admises, en code et en base.
PORTEES_REGLAGE = ("platform", "tenant", "membership", "workspace")
_PORTEES_SQL = ", ".join(f"'{portee}'" for portee in PORTEES_REGLAGE)


class SettingsRegistry(Base):
    """Déclaration d'un réglage. `defaultValue` peut être NULL (NON DÉFINI dans la définition)."""

    __tablename__ = "settings_registry"
    __table_args__ = (
        CheckConstraint(f"\"scopeKind\" IN ({_PORTEES_SQL})", name="ck_settings_registry_scopeKind"),
        CheckConstraint("length(btrim(owner)) > 0", name="ck_settings_registry_owner_non_vide"),
        CheckConstraint("length(btrim(effect)) > 0", name="ck_settings_registry_effect_non_vide"),
        CheckConstraint("length(btrim(key)) > 0", name="ck_settings_registry_key_non_vide"),
        {"comment": "Registre des réglages : clé, propriétaire, portée, sensibilité, effet et défaut."},
    )

    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    scopeKind: Mapped[str] = mapped_column(String(20), nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    effect: Mapped[str] = mapped_column(String(40), nullable=False)
    effectiveAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    defaultValue: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)


class SettingsHistory(UUIDPrimaryKeyMixin, Base):
    """Une modification d'un réglage pour une portée donnée, avec acteur et motif."""

    __tablename__ = "settings_history"
    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="ck_settings_history_reason_non_vide"),
        {"comment": "Historique des modifications des réglages : ancienne et nouvelle valeur, acteur, motif."},
    )

    settingKey: Mapped[str] = mapped_column(
        String(150), ForeignKey("settings_registry.key"), nullable=False, index=True
    )
    scopeKind: Mapped[str] = mapped_column(String(20), nullable=False)
    # NULL pour la portée plateforme ; identifiant de l'organisation pour la portée tenant.
    scopeId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    oldValue: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    newValue: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    actorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
