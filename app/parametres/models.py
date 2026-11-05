"""Modèle des paramètres : définitions et valeurs versionnées par portée (BE-154).

Deux tables :
- `setting_definition` : une ligne par paramètre déclaré (clé, portée de déclaration,
  propriétaire, type de valeur, défaut, sensibilité). Les règles de validation
  viendront avec BE-155 ; ce modèle ne valide pas le contenu des valeurs.
- `setting_value` : une ligne par version écrite d'une valeur, pour une clé, une
  portée et un identifiant de portée donnés. Une valeur n'est jamais modifiée sur
  place : une nouvelle écriture crée la version suivante (historique complet).

Portées (`scopeKind`) : `plateforme`, `organisation`, `module`, `utilisateur`.
La base refuse toute autre valeur (CHECK). `scopeId` identifie l'organisation ou
l'utilisateur ciblé ; la définition ne fixe pas encore la valeur de `scopeId` pour
les portées plateforme et module (point ouvert, à trancher avec BE-155).

Invariants portés par la base, pas seulement par le code :
- unicité de `(definitionKey, scopeKind, scopeId, version)` : deux écritures sur la
  même version ne peuvent pas coexister ; le service (`app.parametres.service`)
  traduit la seconde en `VERSION_CONFLICT` ;
- `createdBy` obligatoire et `reason` non vide (sans espaces seuls) sur chaque ligne,
  pour que toute valeur ait un auteur et une raison traçables.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin

# Valeurs admises pour `scopeKind`, identiques dans les deux tables (CHECK en base).
PORTEES_PARAMETRE = ("plateforme", "organisation", "module", "utilisateur")
_PORTEES_SQL = ", ".join(f"'{portee}'" for portee in PORTEES_PARAMETRE)


class SettingDefinition(Base):
    """Déclaration d'un paramètre : la clé est l'identifiant stable utilisé par
    toutes les valeurs (`setting_value.definitionKey`).

    - `scopeKind` : portée où le paramètre peut être défini ;
    - `owner` : entité qui déclare le paramètre (texte court, non défini plus finement
      par la définition) ;
    - `valueType` : type attendu de la valeur, interprété par BE-155 ;
    - `defaultValue` : valeur de repli JSON, nullable tant que QE-PAR-03 n'est pas
      tranché (aucune sémantique de repli n'est appliquée ici) ;
    - `sensitive` : booléen obligatoire ; un paramètre sensible ne doit jamais être
      journalisé en clair (sémantique de QE-PAR-12 non tranchée ici).
    """

    __tablename__ = "setting_definition"
    __table_args__ = (
        CheckConstraint(f"\"scopeKind\" IN ({_PORTEES_SQL})", name="ck_setting_definition_scopeKind"),
        CheckConstraint("length(btrim(key)) > 0", name="ck_setting_definition_key_non_vide"),
        {"comment": "Déclaration des paramètres : clé, portée, type, défaut et sensibilité."},
    )

    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    scopeKind: Mapped[str] = mapped_column(String(20), nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    valueType: Mapped[str] = mapped_column(String(40), nullable=False)
    defaultValue: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class SettingValue(UUIDPrimaryKeyMixin, Base):
    """Une version d'une valeur de paramètre pour une portée donnée.

    - `version` : entier attribué par l'écrivain (BE-157 le fera de façon atomique) ;
      l'unicité en base empêche deux versions identiques ;
    - `value` : valeur JSON, dont la forme est contrôlée par BE-155 ;
    - `applied` : indique si cette version est en vigueur ; la règle d'application
      (BE-157) n'est pas encore implémentée ici, la valeur par défaut est `false` ;
    - `createdBy` : utilisateur auteur de l'écriture ;
    - `reason` : justification libre, obligatoire et non vide.
    """

    __tablename__ = "setting_value"
    __table_args__ = (
        UniqueConstraint(
            "definitionKey", "scopeKind", "scopeId", "version",
            name="uq_setting_value_definitionKey_scopeKind_scopeId_version",
        ),
        CheckConstraint(f"\"scopeKind\" IN ({_PORTEES_SQL})", name="ck_setting_value_scopeKind"),
        CheckConstraint("version >= 1", name="ck_setting_value_version_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_setting_value_reason_non_vide"),
        {"comment": "Valeurs versionnées des paramètres par portée ; une ligne par version écrite."},
    )

    definitionKey: Mapped[str] = mapped_column(
        String(150), ForeignKey("setting_definition.key"), nullable=False, index=True
    )
    scopeKind: Mapped[str] = mapped_column(String(20), nullable=False)
    scopeId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    createdBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
