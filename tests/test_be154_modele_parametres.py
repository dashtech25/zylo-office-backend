"""BE-154 : modèle des paramètres par portée et versions.

Tests écrits d'après la définition `### BE-154` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : la migration crée `setting_definition` et `setting_value`, et l'unicité
  `(definitionKey, scopeKind, scopeId, version)` est refusée par la base ;
- CA-2 : deux écritures concurrentes sur la même version : la seconde reçoit
  `VERSION_CONFLICT` (409) ;
- CA-3 : une ligne de `setting_value` sans `createdBy` ou sans `reason` non vide
  est refusée par la base ;
- CA-4 : isolation tenant : une valeur de l'organisation A n'est jamais lue
  pour l'organisation B.

Hypothèses de test (points NON DÉFINI de la définition, à confirmer en QE) :
- `defaultValue` (QE-PAR-03) : colonne présente, nullable ;
- `sensitive` (QE-PAR-12) : booléen NOT NULL ;
- `scopeId` est obligatoire pour les portées organisation et utilisateur seules
  (la définition ne cite que ces deux cas).
"""

import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Organization, User
from app.parametres.models import SettingDefinition, SettingValue
from app.parametres.service import ecrire_version, lire_valeur_courante

COLONNES_DEFINITION = {"key", "scopeKind", "owner", "valueType", "defaultValue", "sensitive"}
COLONNES_VALEUR = {"id", "definitionKey", "scopeKind", "scopeId", "version", "value", "applied", "createdBy", "createdAt", "reason"}


async def _utilisateur_et_organisation(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _creer_organisation(nom: str) -> uuid.UUID:
    slug = f"be154-{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=nom, slug=slug, status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _creer_definition(cle: str | None = None) -> str:
    cle = cle or f"be154.{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        db.add(SettingDefinition(key=cle, scopeKind="organisation", owner="test", valueType="texte", sensitive=False))
        await db.commit()
    return cle


async def test_be154_ca1_tables_et_colonnes_presentes(client: AsyncClient):
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN ('setting_definition', 'setting_value')"
        ))).all()
    colonnes: dict[str, set[str]] = {}
    for table, colonne in lignes:
        colonnes.setdefault(table, set()).add(colonne)

    assert "setting_definition" in colonnes, "table setting_definition absente"
    assert "setting_value" in colonnes, "table setting_value absente"
    assert not COLONNES_DEFINITION - colonnes["setting_definition"], "colonnes manquantes dans setting_definition"
    assert not COLONNES_VALEUR - colonnes["setting_value"], "colonnes manquantes dans setting_value"


async def test_be154_ca1_unicite_par_version_refusee_par_la_base(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    cle = await _creer_definition()

    async def inserer(version: int) -> None:
        async with AsyncSessionLocal() as db:
            db.add(SettingValue(
                definitionKey=cle, scopeKind="organisation", scopeId=org_id, version=version,
                value={"v": version}, applied=False, createdBy=user_id, reason="test unicité",
            ))
            await db.commit()

    await inserer(1)
    try:
        await inserer(1)
    except IntegrityError:
        refusee = True
    else:
        refusee = False
    assert refusee, "une seconde ligne de même (clé, portée, version) doit être refusée"

    await inserer(2)  # une version suivante reste acceptée


async def test_be154_ca1_portee_limitee_aux_valeurs_de_la_definition(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    cle = await _creer_definition()

    try:
        async with AsyncSessionLocal() as db:
            db.add(SettingValue(
                definitionKey=cle, scopeKind="inconnue", scopeId=org_id, version=1,
                value={"v": 1}, applied=False, createdBy=user_id, reason="portée inconnue",
            ))
            await db.commit()
    except IntegrityError:
        return
    raise AssertionError("un scopeKind hors plateforme/organisation/module/utilisateur doit être refusé")


async def test_be154_ca2_ecritures_concurrentes_meme_version_conflit(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    cle = await _creer_definition()

    async def ecrire() -> None:
        async with AsyncSessionLocal() as db:
            await ecrire_version(db, cle, "organisation", org_id, 1, {"v": 1}, user_id, "écriture concurrente")

    resultats = await asyncio.gather(ecrire(), ecrire(), return_exceptions=True)

    succes = [r for r in resultats if not isinstance(r, BaseException)]
    echecs = [r for r in resultats if isinstance(r, BaseException)]
    assert len(succes) == 1, f"une seule écriture doit réussir, résultats : {resultats!r}"
    assert len(echecs) == 1 and isinstance(echecs[0], AppError), f"la seconde doit lever AppError : {echecs!r}"
    assert echecs[0].code == "VERSION_CONFLICT"
    assert echecs[0].status_code == 409


async def test_be154_ca3_createdBy_obligatoire_en_base(client: AsyncClient, registered_user: dict, organization: dict):
    _user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    cle = await _creer_definition()

    try:
        async with AsyncSessionLocal() as db:
            db.add(SettingValue(
                definitionKey=cle, scopeKind="organisation", scopeId=org_id, version=1,
                value={"v": 1}, applied=False, createdBy=None, reason="sans auteur",
            ))
            await db.commit()
    except IntegrityError:
        return
    raise AssertionError("une ligne sans createdBy doit être refusée par la base")


async def test_be154_ca3_reason_vide_ou_blanc_refuse_en_base(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    cle = await _creer_definition()

    for raison in ("", "   "):
        try:
            async with AsyncSessionLocal() as db:
                db.add(SettingValue(
                    definitionKey=cle, scopeKind="organisation", scopeId=org_id, version=1,
                    value={"v": 1}, applied=False, createdBy=user_id, reason=raison,
                ))
                await db.commit()
        except IntegrityError:
            continue
        raise AssertionError(f"reason {raison!r} doit être refusée par la base")


async def test_be154_ca4_valeur_d_une_organisation_jamais_lue_par_une_autre(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_a = await _utilisateur_et_organisation(registered_user, organization)
    org_b = await _creer_organisation("Organisation B BE-154")
    cle = await _creer_definition()

    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, "organisation", org_a, 1, {"secret": "A"}, user_id, "valeur de A")

    async with AsyncSessionLocal() as db:
        vue_b = await lire_valeur_courante(db, cle, "organisation", org_b)
    assert vue_b is None, "l'organisation B ne doit jamais lire la valeur de l'organisation A"

    async with AsyncSessionLocal() as db:
        vue_a = await lire_valeur_courante(db, cle, "organisation", org_a)
    assert vue_a is not None and vue_a.value == {"secret": "A"}
