"""BE-175 : preuve de sauvegarde et de restauration.

Tests écrits d'après la définition `### BE-175` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

La preuve porte sur les tables `setting_value` et `audit_event` (BE-154, BE-152).
Aucune route : la restauration est une opération d'exploitation, réservée à
l'opérateur plateforme. La sauvegarde et la restauration passent par les scripts
existants `scripts/backup.sh` et `scripts/restore.sh` (réutilisés, non dupliqués),
et la restauration cible toujours une base jetable distincte de la base source.

Couverture :
- CA-1 : sauvegarde puis restauration sur base jetable reproduisent à l'identique
  les lignes `setting_value` et les paramètres résolus (`lire_valeur_courante`) ;
- CA-2 : après restauration, `audit_event` reste en ajout seul (UPDATE et DELETE
  refusés par le trigger BE-260, rejoué sur la base restaurée) ;
- CA-3 (refus) : une restauration sans droit opérateur plateforme est refusée `403`
  et ne touche pas la base cible ;
- CA-4 (isolation tenant) : les lignes d'un autre tenant ne changent pas entre la
  sauvegarde et la base restaurée. Limite : la restauration porte sur la base entière
  (pas de restauration par tenant, voir QE) ; le test ne couvre donc que ce cas.

Garde ajoutée : la restauration refuse de cibler la base source (pas de test
spécifique dans la définition, couvert par `test_be175_restauration_refuse_base_source`).
"""

import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.audit.service import record_audit_event
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.exploitation.restauration import restaurer_sauvegarde, sauvegarder_base
from app.identity.models import User
from app.parametres.models import SettingDefinition
from app.parametres.service import ecrire_version, lire_valeur_courante

# Base jetable de la restauration. Le nom n'entre pas dans le motif zylo_t<NNN>_test
# (garde de conftest), volontairement : c'est une base éphémère créée et supprimée
# par ce module, jamais la base de la tâche.
NOM_BASE_RESTAURATION = "zylo_t175_restauration_test"


def _url_base_source():
    """URL de la base de test de la tâche (TEST_DATABASE_URL, posée par l'environnement)."""
    return make_url(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
async def base_jetable():
    """Crée une base vide dédiée à la restauration, la supprime à la fin du test."""
    admin = create_async_engine(_url_base_source().set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)

    async def _recreer() -> None:
        async with admin.connect() as connexion:
            await connexion.execute(text(f'DROP DATABASE IF EXISTS "{NOM_BASE_RESTAURATION}" WITH (FORCE)'))
            await connexion.execute(text(f'CREATE DATABASE "{NOM_BASE_RESTAURATION}"'))

    await _recreer()
    yield NOM_BASE_RESTAURATION
    async with admin.connect() as connexion:
        await connexion.execute(text(f'DROP DATABASE IF EXISTS "{NOM_BASE_RESTAURATION}" WITH (FORCE)'))
    await admin.dispose()


async def _moteur_base(nom: str):
    return create_async_engine(_url_base_source().set(database=nom), poolclass=NullPool)


async def _utilisateur_et_organisation(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _semer_parametres(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Crée une définition et deux versions pour une organisation. Retourne la clé."""
    cle = f"test.be175.{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        db.add(SettingDefinition(key=cle, scopeKind="organisation", owner="test-be175", valueType="texte", sensitive=False))
        await db.commit()
    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, "organisation", org_id, 1, {"v": "un"}, user_id, "version initiale")
    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, "organisation", org_id, 2, {"v": "deux"}, user_id, "version corrigée", applied=True)
    return cle


async def _semer_journal(user_id: uuid.UUID, org_id: uuid.UUID, prefixe: str) -> None:
    for numero in range(2):
        request_id_ctx.set(f"req-{prefixe}-{numero}")
        async with AsyncSessionLocal() as db:
            await record_audit_event(db, org_id, user_id, f"test.be175.{prefixe}", "Test", None, f"Entrée {prefixe} {numero}")
            await db.commit()


async def _lignes_parametres(moteur, org_id: uuid.UUID) -> list[tuple]:
    """Toutes les lignes `setting_value` d'un moteur, ordonnées : sert à la comparaison."""
    async with moteur.connect() as connexion:
        resultat = await connexion.execute(text(
            'SELECT id, "definitionKey", "scopeKind", "scopeId", version, value, applied, "createdBy", reason '
            'FROM setting_value ORDER BY id'
        ))
        return [tuple(ligne) for ligne in resultat.fetchall()]


async def _lignes_journal_organisation(moteur, org_id: uuid.UUID) -> list[tuple]:
    async with moteur.connect() as connexion:
        resultat = await connexion.execute(text(
            'SELECT id, "eventId", action, summary, "organizationId", "actorUserId", request_id '
            'FROM audit_event WHERE "organizationId" = :org ORDER BY id'
        ).bindparams(org=org_id))
        return [tuple(ligne) for ligne in resultat.fetchall()]


def _operateur_autorise(monkeypatch, user_id: uuid.UUID) -> None:
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(user_id))


async def test_be175_ca1_restauration_reproduit_parametres_et_versions(
    client: AsyncClient, registered_user: dict, organization: dict, tmp_path: Path, base_jetable: str, monkeypatch
):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    cle = await _semer_parametres(user_id, org_id)
    _operateur_autorise(monkeypatch, user_id)

    fichier = sauvegarder_base(tmp_path)
    restaurer_sauvegarde(user_id, fichier, base_jetable)

    moteur_source = create_async_engine(_url_base_source(), poolclass=NullPool)
    moteur_cible = await _moteur_base(base_jetable)
    try:
        assert await _lignes_parametres(moteur_cible, org_id) == await _lignes_parametres(moteur_source, org_id)

        async with AsyncSessionLocal() as db_source:
            attendu = await lire_valeur_courante(db_source, cle, "organisation", org_id)
        async with moteur_cible.connect() as connexion:
            restauree = await connexion.execute(text(
                'SELECT version, value FROM setting_value WHERE "definitionKey" = :cle AND "scopeId" = :org '
                'ORDER BY version DESC LIMIT 1'
            ).bindparams(cle=cle, org=org_id))
            version_restauree, valeur_restauree = restauree.one()
        assert attendu is not None
        assert (version_restauree, valeur_restauree) == (attendu.version, attendu.value)
    finally:
        await moteur_source.dispose()
        await moteur_cible.dispose()


async def test_be175_ca2_journal_reste_ajout_seul_apres_restauration(
    client: AsyncClient, registered_user: dict, organization: dict, tmp_path: Path, base_jetable: str, monkeypatch
):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    await _semer_journal(user_id, org_id, "ca2")
    _operateur_autorise(monkeypatch, user_id)

    fichier = sauvegarder_base(tmp_path)
    restaurer_sauvegarde(user_id, fichier, base_jetable)

    moteur_source = create_async_engine(_url_base_source(), poolclass=NullPool)
    moteur_cible = await _moteur_base(base_jetable)
    try:
        lignes_restaurees = await _lignes_journal_organisation(moteur_cible, org_id)
        assert lignes_restaurees, "le journal doit contenir les entrées semées avant la sauvegarde"
        assert lignes_restaurees == await _lignes_journal_organisation(moteur_source, org_id)

        with pytest.raises(DBAPIError):
            async with moteur_cible.begin() as connexion:
                await connexion.execute(text("UPDATE audit_event SET summary = 'modifié' WHERE action = 'test.be175.ca2'"))
        with pytest.raises(DBAPIError):
            async with moteur_cible.begin() as connexion:
                await connexion.execute(text("DELETE FROM audit_event WHERE action = 'test.be175.ca2'"))

        assert await _lignes_journal_organisation(moteur_cible, org_id) == lignes_restaurees
    finally:
        await moteur_source.dispose()
        await moteur_cible.dispose()


async def test_be175_ca3_restauration_sans_droit_operateur_donne_403(
    client: AsyncClient, registered_user: dict, organization: dict, tmp_path: Path, base_jetable: str, monkeypatch
):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    await _semer_parametres(user_id, org_id)
    fichier = sauvegarder_base(tmp_path)
    # Le compte n'est pas dans l'allowlist d'exploitation : la restauration est refusée.
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))

    with pytest.raises(AppError) as erreur:
        restaurer_sauvegarde(user_id, fichier, base_jetable)
    assert erreur.value.status_code == 403

    moteur_cible = await _moteur_base(base_jetable)
    try:
        async with moteur_cible.connect() as connexion:
            tables = await connexion.scalar(text("SELECT to_regclass('setting_value')"))
        assert tables is None, "une restauration refusée ne doit rien écrire dans la base cible"
    finally:
        await moteur_cible.dispose()


async def test_be175_ca4_restauration_ne_modifie_pas_un_autre_tenant(
    client: AsyncClient, registered_user: dict, organization: dict, tmp_path: Path, base_jetable: str, monkeypatch
):
    user_id, org_a = await _utilisateur_et_organisation(registered_user, organization)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org", "slug": f"autre-org-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    org_b = uuid.UUID(reponse.json()["id"])
    await _semer_parametres(user_id, org_a)
    await _semer_parametres(user_id, org_b)
    await _semer_journal(user_id, org_b, "ca4")
    _operateur_autorise(monkeypatch, user_id)

    moteur_source = create_async_engine(_url_base_source(), poolclass=NullPool)
    try:
        avant_parametres = await _lignes_parametres(moteur_source, org_b)
        avant_journal = await _lignes_journal_organisation(moteur_source, org_b)
        assert avant_parametres and avant_journal, "le test doit porter sur de vraies lignes de l'autre tenant"
    finally:
        await moteur_source.dispose()

    fichier = sauvegarder_base(tmp_path)
    restaurer_sauvegarde(user_id, fichier, base_jetable)

    moteur_cible = await _moteur_base(base_jetable)
    try:
        assert await _lignes_parametres(moteur_cible, org_b) == avant_parametres
        assert await _lignes_journal_organisation(moteur_cible, org_b) == avant_journal
    finally:
        await moteur_cible.dispose()


async def test_be175_restauration_refuse_base_source(
    client: AsyncClient, registered_user: dict, organization: dict, tmp_path: Path, monkeypatch
):
    user_id, _ = await _utilisateur_et_organisation(registered_user, organization)
    _operateur_autorise(monkeypatch, user_id)
    fichier = sauvegarder_base(tmp_path)
    nom_source = _url_base_source().database

    with pytest.raises(AppError) as erreur:
        restaurer_sauvegarde(user_id, fichier, nom_source)
    assert erreur.value.status_code == 422
