"""BE-173 : export d'audit en job traçable et rétention.

Tests écrits d'après la définition `### BE-173` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Routes cibles :
- `POST /api/v1/audit/exports` : demande d'export (sujet, période, motif obligatoire) ;
- `GET /api/v1/audit/exports/{job_id}` : statut et lien de téléchargement temporaire ;
- `GET /api/v1/audit/exports/{job_id}/telechargement` : contenu de l'export (ajout
  nécessaire pour que CA-2 « le téléchargement d'un export expiré renvoie 410 » ait un objet).

Table `export_audit` (migration de BE-173). Le fichier d'export n'est pas une table.

Écarts avec la définition, signalés ici et dans app/audit/export_job.py :
- la colonne `tenantId` de la définition est nommée `organizationId`, comme le reste du
  journal d'audit (app/audit/models.py) ;
- la permission est `audit.export` (définition, CA-3) ; le lecteur du job doit la détenir aussi ;
- la durée d'expiration n'a pas de valeur par défaut (QE-PAR-07) : sans configuration, la
  demande est refusée en 503 et rien n'est écrit. Les tests la fixent par monkeypatch.

Couverture :
- CA-1 : sans motif, 422 et aucun job ; avec motif, un job est créé et l'action
  `audit.export.request` est journalisée (EVT-AUD-02) avec le motif ;
- CA-2 : le téléchargement d'un export expiré renvoie 410 ; sans configuration, la demande
  est refusée (pas de valeur par défaut) ;
- CA-3 (refus) : sans `audit.export`, 403 et aucun job ;
- CA-4 : le contenu n'expose que les champs autorisés, ni secret ni adresse ;
- CA-5 (isolation tenant) : le job d'un tenant A n'est lisible ni par B (404), ni en téléchargement.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.audit.service import record_audit_event
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from tests.conftest import unique_email

ROUTE = "/api/v1/audit/exports"
MOT_DE_PASSE = "TestPassword123!"
TYPE_SUJET = "TestBe173Sujet"
ACTION = "test.be173.action"
MOTIF = "Enquête BE173"
SECRET = "SECRET-BE173-ne-doit-pas-sortir"
ADRESSE_IP = "203.0.113.173"
AGENT = "agent-be173-ne-doit-pas-sortir"
DUREE_EXPIRATION_SECONDES = 3600
CHAMPS_INTERDITS = {"ipAddress", "userAgent", "changes", "payloadMinimal", "approvalId", "visibility"}


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _corps(**surcharges) -> dict:
    """Corps valide de demande d'export ; `surcharges` remplace ou retire (valeur None) un champ."""
    maintenant = datetime.now(timezone.utc)
    corps = {
        "sujet": TYPE_SUJET,
        "dateDebut": (maintenant - timedelta(hours=1)).isoformat(),
        "dateFin": (maintenant + timedelta(hours=1)).isoformat(),
        "motif": MOTIF,
    }
    corps.update(surcharges)
    return {cle: valeur for cle, valeur in corps.items() if valeur is not None}


def _configurer_expiration(monkeypatch) -> None:
    """Fixe la durée de rétention de la configuration de test (pas de valeur par défaut dans le code)."""
    monkeypatch.setattr(settings, "AUDIT_EXPORT_EXPIRATION_SECONDS", DUREE_EXPIRATION_SECONDES, raising=False)


async def _inscrire_et_connecter(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE173"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return {"id": str(user.id), "accessToken": login.json()["accessToken"]}


async def _membre_sans_permission(client: AsyncClient, organization_id: str) -> dict:
    """Membre actif de l'organisation sans aucun rôle, donc sans `audit.export`."""
    membre = await _inscrire_et_connecter(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(membre["id"])))
        await db.commit()
    return membre


async def _nombre_de_jobs(organization_id: str) -> int:
    from app.audit.models import ExportAudit

    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(ExportAudit).where(ExportAudit.organizationId == uuid.UUID(organization_id))
            )
        ).scalar_one()


async def _creer_job(client: AsyncClient, utilisateur: dict, organization_id: str) -> str:
    res = await client.post(
        ROUTE, json=_corps(), headers=_entetes(utilisateur["accessToken"], organization_id)
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _evenement_de_sujet(organization_id: str, actor_user_id: str) -> None:
    """Écrit un événement d'audit du sujet, avec des champs qui ne doivent jamais sortir dans l'export."""
    async with AsyncSessionLocal() as db:
        await record_audit_event(
            db,
            uuid.UUID(organization_id),
            uuid.UUID(actor_user_id),
            action=ACTION,
            entity_type=TYPE_SUJET,
            entity_id=uuid.uuid4(),
            summary="Résumé BE173",
            changes={"password": SECRET, "nom": "valeur-visible-be173"},
            reason="Motif de l'événement BE173",
            ip_address=ADRESSE_IP,
            user_agent=AGENT,
            correlation_id="be173-corr",
        )
        await db.commit()


async def test_be173_ca1_demande_sans_motif_renvoie_422_sans_job(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : sans motif, la demande est refusée en 422 et aucun job n'est créé."""
    avant = await _nombre_de_jobs(organization["id"])

    res = await client.post(
        ROUTE,
        json=_corps(motif=None),
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 422, res.text
    assert await _nombre_de_jobs(organization["id"]) == avant


async def test_be173_ca1_motif_blanc_renvoie_422(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 (complément) : un motif fait uniquement d'espaces compte comme absent."""
    res = await client.post(
        ROUTE,
        json=_corps(motif="   "),
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 422, res.text


async def test_be173_ca1_avec_motif_cree_un_job_et_journalise_la_demande(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-1 : avec motif, un job est créé et l'action `audit.export.request` (EVT-AUD-02) est journalisée."""
    _configurer_expiration(monkeypatch)
    avant = await _nombre_de_jobs(organization["id"])

    res = await client.post(
        ROUTE,
        json=_corps(),
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 201, res.text
    assert await _nombre_de_jobs(organization["id"]) == avant + 1
    from app.audit.models import AuditEvent

    async with AsyncSessionLocal() as db:
        journal = (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.organizationId == uuid.UUID(organization["id"]),
                    AuditEvent.action == "audit.export.request",
                )
            )
        ).scalars().all()
    assert len(journal) == 1
    assert journal[0].reason == MOTIF
    assert str(journal[0].actorUserId) == (await _id_de(registered_user))


async def test_be173_ca2_telechargement_expire_renvoie_410(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-2 : un export dont l'expiration est passée renvoie 410 au téléchargement."""
    from app.audit.models import ExportAudit

    _configurer_expiration(monkeypatch)
    job_id = await _creer_job(client, registered_user, organization["id"])
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ExportAudit)
            .where(ExportAudit.id == uuid.UUID(job_id))
            .values(expireAt=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()

    res = await client.get(
        f"{ROUTE}/{job_id}/telechargement",
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 410, res.text


async def test_be173_ca2_sans_configuration_de_retention_la_demande_est_refusee(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-2 (QE-PAR-07) : la durée d'expiration n'a pas de valeur par défaut. Sans configuration,
    aucun job n'est créé et la réponse est 503."""
    monkeypatch.setattr(settings, "AUDIT_EXPORT_EXPIRATION_SECONDS", None, raising=False)
    avant = await _nombre_de_jobs(organization["id"])

    res = await client.post(
        ROUTE,
        json=_corps(),
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 503, res.text
    assert await _nombre_de_jobs(organization["id"]) == avant


async def test_be173_ca3_refus_sans_audit_export_ne_cree_aucun_job(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-3 (refus) : sans `audit.export`, la demande renvoie 403 et ne crée aucun job."""
    _configurer_expiration(monkeypatch)
    membre = await _membre_sans_permission(client, organization["id"])
    avant = await _nombre_de_jobs(organization["id"])

    res = await client.post(
        ROUTE,
        json=_corps(),
        headers=_entetes(membre["accessToken"], organization["id"]),
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"].upper() == "PERMISSION_DENIED"  # code émis en minuscules par le socle (BE-001)
    assert await _nombre_de_jobs(organization["id"]) == avant


async def test_be173_ca3_refus_lecture_du_job_sans_audit_export(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-3 (refus, lecture) : sans `audit.export`, le statut d'un job n'est pas lisible (403)."""
    _configurer_expiration(monkeypatch)
    job_id = await _creer_job(client, registered_user, organization["id"])
    membre = await _membre_sans_permission(client, organization["id"])

    res = await client.get(f"{ROUTE}/{job_id}", headers=_entetes(membre["accessToken"], organization["id"]))

    assert res.status_code == 403, res.text


async def test_be173_ca4_contenu_limite_aux_champs_autorises(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-4 : le contenu contient les événements du sujet, sans secret ni adresse de destinataire."""
    _configurer_expiration(monkeypatch)
    job_id = await _creer_job(client, registered_user, organization["id"])
    await _evenement_de_sujet(organization["id"], await _id_de(registered_user))

    res = await client.get(
        f"{ROUTE}/{job_id}/telechargement",
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 200, res.text
    texte = res.text
    assert SECRET not in texte
    assert ADRESSE_IP not in texte
    assert AGENT not in texte
    evenements = res.json()["data"]
    assert len(evenements) >= 1
    for evenement in evenements:
        assert CHAMPS_INTERDITS.isdisjoint(evenement.keys())
        assert evenement["entityType"] == TYPE_SUJET
    assert any(evenement.get("summary") == "Résumé BE173" for evenement in evenements)


async def test_be173_ca5_job_d_un_autre_tenant_renvoie_404(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-5 (isolation tenant) : un job du tenant A est introuvable pour le tenant B (404),
    statut comme téléchargement."""
    _configurer_expiration(monkeypatch)
    job_id = await _creer_job(client, registered_user, organization["id"])
    autre = await _inscrire_et_connecter(client)
    creation = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B BE173", "slug": f"tenant-b-be173-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {autre['accessToken']}"},
    )
    assert creation.status_code == 201, creation.text
    tenant_b = creation.json()["id"]

    statut = await client.get(f"{ROUTE}/{job_id}", headers=_entetes(autre["accessToken"], tenant_b))
    telechargement = await client.get(f"{ROUTE}/{job_id}/telechargement", headers=_entetes(autre["accessToken"], tenant_b))

    assert statut.status_code == 404, statut.text
    assert telechargement.status_code == 404, telechargement.text


async def _id_de(utilisateur: dict) -> str:
    """Identifiant de l'utilisateur du fixture `registered_user`, lu en base par courriel."""
    async with AsyncSessionLocal() as db:
        return str((await db.execute(select(User).where(User.email == utilisateur["email"]))).scalar_one().id)
