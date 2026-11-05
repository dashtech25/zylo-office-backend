"""BE-247 : gestion des incidents et chronologie.

Tests écrits d'après la définition `### BE-247` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Couverture :
- CA-1 : chaque incident a owner, état et horodatage (refus sans owner, base
  et service ; détail exposé avec ces trois champs) ;
- CA-2 : la chronologie est reconstructible et `incident_events` est
  append-only (UPDATE et DELETE refusés par la base) ;
- CA-3 : la liste et le détail n'exposent pas le contenu d'un tenant (test de
  redaction) ;
- CA-4 : accès sans droit donne 403 (liste et détail).

Choix de cette suite (voir QE-EXP-05 et NON DÉFINI dans la définition) :
- le droit de lecture est la portée plateforme de BE-120 (autorité
  `operateur_plateforme`, table `admin_role_assignment`) : aucune permission
  doublon n'est créée ;
- les tests importent le code métier à l'intérieur des fonctions, pour que
  chaque test échoue pour sa seule raison tant que le code n'existe pas.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_LISTE = "/api/v1/admin/incidents"
CHEMIN_DETAIL = "/api/v1/admin/incidents/{incident_id}"
CHAMPS_LISTE_AUTORISES = {"id", "severity", "owner", "state", "occurredAt", "tenantId"}


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _moi(client: AsyncClient, utilisateur: dict) -> str:
    return (await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))).json()["id"]


async def _accorder_autorite_plateforme(client: AsyncClient, utilisateur: dict) -> None:
    """Affectation d'opérateur plateforme (BE-121/BE-120) pour le compte donné."""
    actor_id = uuid.UUID(await _moi(client, utilisateur))
    async with AsyncSessionLocal() as db:
        db.add(
            AdminRoleAssignment(
                actorId=actor_id,
                roleCode="operateur_plateforme",
                scope="platform",
                grantedBy=actor_id,
                grantedAt=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _creer_incident(owner: str = "exploitation-plateforme", tenant_id: uuid.UUID | None = None) -> str:
    from app.operator.incidents import creer_incident

    async with AsyncSessionLocal() as db:
        incident = await creer_incident(db, severite="high", owner=owner, tenant_id=tenant_id)
        await db.commit()
        return str(incident.id)


# --- CA-1 : owner, état et horodatage obligatoires ---------------------------------


async def test_be247_ca1_incident_sans_owner_refuse_par_le_service():
    from app.operator.incidents import creer_incident

    async with AsyncSessionLocal() as db:
        try:
            await creer_incident(db, severite="high", owner="   ", tenant_id=None)
            raise AssertionError("un incident sans owner doit être refusé")
        except AppError as erreur:
            assert erreur.status_code == 422


async def test_be247_ca1_incident_sans_owner_refuse_par_la_base():
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text(
                    "INSERT INTO incidents (id, severity, owner, state, occurredAt) "
                    "VALUES (:id, 'high', NULL, 'ouvert', now())"
                ).bindparams(id=uuid.uuid4())
            )
            await db.commit()
            raise AssertionError("la base doit refuser un incident sans owner")
        except IntegrityError:
            await db.rollback()


async def test_be247_ca1_detail_expose_owner_etat_et_horodatage(client: AsyncClient, registered_user: dict):
    await _accorder_autorite_plateforme(client, registered_user)
    incident_id = await _creer_incident(owner="astreinte-n2")

    res = await client.get(CHEMIN_DETAIL.format(incident_id=incident_id), headers=_entetes(registered_user, "platform"))

    assert res.status_code == 200
    corps = res.json()
    assert corps["owner"] == "astreinte-n2"
    assert corps["state"] == "ouvert"
    assert corps["occurredAt"]


# --- CA-2 : chronologie reconstructible, append-only -------------------------------


async def test_be247_ca2_chronologie_reconstructible_dans_l_ordre(client: AsyncClient, registered_user: dict):
    from app.operator.incidents import ajouter_evenement

    await _accorder_autorite_plateforme(client, registered_user)
    incident_id = await _creer_incident()
    types = ["detection", "prise_en_charge", "mesure_corrective"]
    async with AsyncSessionLocal() as db:
        for type_evenement in types:
            await ajouter_evenement(db, uuid.UUID(incident_id), type_evenement=type_evenement, resume=type_evenement)
        await db.commit()

    res = await client.get(CHEMIN_DETAIL.format(incident_id=incident_id), headers=_entetes(registered_user, "platform"))

    chronologie = [evenement["eventType"] for evenement in res.json()["chronologie"]]
    assert chronologie == types


async def test_be247_ca2_update_et_delete_sur_evenement_refuses_par_la_base():
    from app.operator.incidents import ajouter_evenement

    incident_id = await _creer_incident()
    async with AsyncSessionLocal() as db:
        evenement = await ajouter_evenement(db, uuid.UUID(incident_id), type_evenement="detection", resume="origine")
        await db.commit()
        evenement_id = evenement.id

    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("UPDATE incident_events SET summary = 'modifie' WHERE id = :id").bindparams(id=evenement_id))
            await db.commit()
            raise AssertionError("UPDATE sur incident_events doit échouer")
        except DBAPIError:
            await db.rollback()

    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("DELETE FROM incident_events WHERE id = :id").bindparams(id=evenement_id))
            await db.commit()
            raise AssertionError("DELETE sur incident_events doit échouer")
        except DBAPIError:
            await db.rollback()

    async with AsyncSessionLocal() as db:
        resume = await db.scalar(text("SELECT summary FROM incident_events WHERE id = :id").bindparams(id=evenement_id))
    assert resume == "origine"


# --- CA-3 : la liste n'expose pas le contenu d'un tenant ---------------------------


async def test_be247_ca3_liste_n_expose_pas_le_contenu_du_tenant(client: AsyncClient, registered_user: dict, organization: dict):
    await _accorder_autorite_plateforme(client, registered_user)
    await _creer_incident(tenant_id=uuid.UUID(organization["id"]))

    res = await client.get(CHEMIN_LISTE, headers=_entetes(registered_user, "platform"))

    assert res.status_code == 200
    lignes = res.json()["data"]
    assert lignes, "la liste doit contenir l'incident créé"
    for ligne in lignes:
        assert set(ligne) <= CHAMPS_LISTE_AUTORISES, f"champs exposés hors redaction : {set(ligne) - CHAMPS_LISTE_AUTORISES}"
    corps = res.text
    assert organization["name"] not in corps
    assert organization["slug"] not in corps


async def test_be247_ca3_detail_n_expose_pas_le_nom_du_tenant(client: AsyncClient, registered_user: dict, organization: dict):
    await _accorder_autorite_plateforme(client, registered_user)
    incident_id = await _creer_incident(tenant_id=uuid.UUID(organization["id"]))

    res = await client.get(CHEMIN_DETAIL.format(incident_id=incident_id), headers=_entetes(registered_user, "platform"))

    assert res.status_code == 200
    assert organization["name"] not in res.text


# --- CA-4 : accès sans droit donne 403 ---------------------------------------------


async def test_be247_ca4_liste_sans_droit_donne_403(client: AsyncClient, registered_user: dict):
    await _creer_incident()

    res = await client.get(CHEMIN_LISTE, headers=_entetes(registered_user))

    assert res.status_code == 403


async def test_be247_ca4_detail_sans_droit_donne_403(client: AsyncClient, registered_user: dict):
    incident_id = await _creer_incident()

    res = await client.get(CHEMIN_DETAIL.format(incident_id=incident_id), headers=_entetes(registered_user))

    assert res.status_code == 403
