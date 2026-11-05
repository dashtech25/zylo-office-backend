"""BE-139 : rejeu d'un événement à effet métier.

Tests écrits d'après la définition `### BE-139` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/events/{event_id}/replay-commands` (201, puis 200 au rejeu identique).

Fonctions testées :
- `app.operator.event_replay.executer_replay` (exécuteur du domaine, enregistré dans
  `app.operator.guard.EXECUTEURS` sous la classe `evenement.replay`).
- `app.operator.sensitive_classes.exiger_approbation` (double validation, CA-2).

Couverture (critères d'acceptation) :
- CA-1 : rejeu d'un événement déjà appliqué avec la même clé : aucun second effet ;
- CA-2 (refus de droit) : rejeu sans approbation distincte : 409 ; rôle non habilité : 403 ;
- CA-3 (isolation tenant) : rejeu d'un événement du tenant B depuis une affectation au tenant A : 403 ;
- CA-4 : rejeu ambigu : résultat inconnu, aucun nouvel appel au consommateur.

Hypothèses de test :
- l'événement source est inséré directement dans `outbox_evenement`, comme les affectations
  de rôle le sont dans BE-135 : pas de montage de la chaîne complète de publication ;
- le consommateur de test est un handler fictif, branché dans `CONSOMMATEURS` par monkeypatch ;
- le passage complet par la garde `executer_commande` (preview confirmée, etc.) n'est pas
  rejoué ici : il est couvert par `tests/test_be126_garde_commande.py`. Le test CA-4 vérifie
  donc que l'exécuteur ne réessaie pas et remonte l'exception que la garde transforme en
  résultat inconnu.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import settings  # noqa: F401 : réservé au montage de configuration
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.evenements.consumer import CONSOMMATEURS
from app.evenements.models import OutboxEvenement
from app.operator.guard import EXECUTEURS, ResultatInconnu
from app.operator.sensitive_classes import classe_par_code, exiger_approbation

MOT_DE_PASSE = "TestPassword123!"
ROLE_GESTION = "securite_incident_commander"
ROLE_L2 = "agent_support_l2"
CLASSE = "evenement.replay"
CONSOMMATEUR = "consommateur.be139"
TYPE_EVENEMENT = "Tenant.test.be139"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be139-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-139"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
    """Pose une affectation de rôle administrative sur une portée (table `admin_role_assignment`)."""
    from app.rbac.role_assignments import AdminRoleAssignment

    async with AsyncSessionLocal() as db:
        db.add(AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=datetime.now(timezone.utc),
            expiresAt=None,
            revokedAt=None,
        ))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> uuid.UUID:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"tenant-be139-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return uuid.UUID(reponse.json()["id"])


async def _evenement(tenant_id: uuid.UUID) -> uuid.UUID:
    """Insère un événement de tenant publié dans l'outbox et renvoie son `eventId`."""
    event_id = uuid.uuid4()
    enveloppe = {
        "eventId": str(event_id),
        "eventType": TYPE_EVENEMENT,
        "schemaVersion": 1,
        "occurredAt": datetime.now(timezone.utc).isoformat(),
        "tenantId": str(tenant_id),
        "scope": {"type": "Tenant", "id": str(tenant_id)},
        "actor": {},
        "subject": {"type": "Tenant", "id": str(tenant_id)},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"valeur": 1},
    }
    async with AsyncSessionLocal() as db:
        db.add(OutboxEvenement(
            eventId=event_id,
            eventType=TYPE_EVENEMENT,
            schemaVersion=1,
            portee="tenant",
            tenantId=tenant_id,
            acteur={},
            correlationId=None,
            payload=enveloppe,
            dataClassification="internal",
            statut="publie",
            tentatives=0,
        ))
        await db.commit()
    return event_id


def _chemin(event_id: uuid.UUID) -> str:
    return f"/api/v1/admin/events/{event_id}/replay-commands"


def _corps() -> dict:
    return {
        "consommateur": CONSOMMATEUR,
        "reasonTicket": "INC-139",
        "idempotencyKey": uuid.uuid4().hex,
    }


def _commande(event_id: uuid.UUID, tenant_id: uuid.UUID) -> SimpleNamespace:
    """Intention minimale au sens de l'exécuteur : seuls les champs qu'il lit sont présents."""
    return SimpleNamespace(
        commandId=uuid.uuid4(),
        commandType=CLASSE,
        tenantId=tenant_id,
        targetObjectType="Evenement",
        targetObjectId=str(event_id),
        payload={"consommateur": CONSOMMATEUR},
    )


def _brancher(monkeypatch, handler: Any) -> None:
    """Branche un consommateur fictif, et le domaine `evenement.replay` tel que le code le prévoit."""
    monkeypatch.setitem(CONSOMMATEURS, CONSOMMATEUR, handler)


async def test_ca1_rejeu_de_meme_evenement_sans_second_effet(client: AsyncClient, monkeypatch):
    """CA-1 : un événement déjà appliqué, rejoué, ne produit aucun second effet (test d'idempotence)."""
    from app.operator.event_replay import executer_replay

    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire, "Tenant CA-1 BE-139")
    event_id = await _evenement(tenant)
    effets: list[uuid.UUID] = []

    async def handler(evenement) -> None:
        effets.append(evenement.eventId)

    _brancher(monkeypatch, handler)
    commande = _commande(event_id, tenant)

    async with AsyncSessionLocal() as db:
        premier = await executer_replay(db, commande)
        await db.commit()
    async with AsyncSessionLocal() as db:
        second = await executer_replay(db, commande)
        await db.commit()

    assert premier["issue"] == "traite"
    assert second["issue"] == "doublon"
    assert effets == [event_id], "le consommateur ne doit appliquer l'effet qu'une seule fois"


def test_ca2_sans_approbation_distincte_409():
    """CA-2 (refus de droit) : un rejeu sans approbateur distinct est refusé par 409 `approval_required`."""
    classe = classe_par_code(CLASSE)
    assert classe is not None and classe.requiresDoubleValidation is True

    with pytest.raises(AppError) as erreur:
        exiger_approbation(classe, None)
    assert erreur.value.status_code == 409
    assert erreur.value.code == "approval_required"

    exiger_approbation(classe, uuid.uuid4())  # un approbateur distinct suffit à passer la garde


async def test_ca2_agent_l2_rejeu_403(client: AsyncClient):
    """CA-2 (refus de droit) : un agent L2 n'est pas habilité à demander un rejeu : 403."""
    proprietaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, proprietaire, "Tenant CA-2 BE-139")
    event_id = await _evenement(tenant)
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], ROLE_L2, f"tenant:{tenant}")

    reponse = await client.post(_chemin(event_id), json=_corps(), headers=_entetes(agent))

    assert reponse.status_code == 403, reponse.text


async def test_ca3_rejeu_evenement_tenant_b_depuis_affectation_tenant_a_403(client: AsyncClient):
    """CA-3 (isolation tenant) : un gestionnaire du tenant A ne peut pas rejouer un événement du tenant B."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, gestionnaire, "Tenant A CA-3 BE-139")
    tenant_b = await _organisation(client, gestionnaire, "Tenant B CA-3 BE-139")
    event_b = await _evenement(tenant_b)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant_a}")

    reponse = await client.post(_chemin(event_b), json=_corps(), headers=_entetes(gestionnaire))

    assert reponse.status_code == 403, reponse.text


async def test_ca4_rejeu_ambigu_resultat_inconnu_sans_nouvel_appel(client: AsyncClient, monkeypatch):
    """CA-4 : un rejeu dont l'issue est ambiguë remonte `ResultatInconnu` et ne rappelle jamais le consommateur.

    La garde (`app.operator.guard`) transforme cette exception en statut `resultat_inconnu`
    (nom retenu dans le code ; la définition écrit `unknown`, voir le compte rendu).
    """
    from app.operator.event_replay import executer_replay

    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire, "Tenant CA-4 BE-139")
    event_id = await _evenement(tenant)
    appels: list[uuid.UUID] = []

    async def handler(evenement) -> None:
        appels.append(evenement.eventId)
        raise ResultatInconnu()

    _brancher(monkeypatch, handler)
    commande = _commande(event_id, tenant)

    async with AsyncSessionLocal() as db:
        with pytest.raises(ResultatInconnu):
            await executer_replay(db, commande)
        # La garde committe après ResultatInconnu (voir `_arreter_resultat_inconnu`) : la trace persiste.
        await db.commit()
    async with AsyncSessionLocal() as db:
        # Le rejeu suivant ne doit pas rappeler le consommateur : la trace de consommation est conservée.
        second = await executer_replay(db, commande)
        await db.commit()

    assert appels == [event_id], "aucun second appel au consommateur après un résultat inconnu"
    assert second["issue"] == "doublon"
    assert CLASSE in EXECUTEURS, "le domaine evenement.replay doit être branché dans la garde"


async def test_nominal_intention_201_puis_rejeu_identique_200(client: AsyncClient):
    """Création de l'intention de rejeu par un gestionnaire (201), puis même clé et même corps (200)."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire, "Tenant nominal BE-139")
    event_id = await _evenement(tenant)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    corps = _corps()

    premiere = await client.post(_chemin(event_id), json=corps, headers=_entetes(gestionnaire))
    rejeu = await client.post(_chemin(event_id), json=corps, headers=_entetes(gestionnaire))

    assert premiere.status_code == 201, premiere.text
    assert premiere.json()["commandType"] == CLASSE
    assert premiere.json()["status"] == "intention"
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["commandId"] == premiere.json()["commandId"]
