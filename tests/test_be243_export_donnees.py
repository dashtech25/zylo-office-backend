"""BE-243 : export de données par sujet ou tenant.

Tests écrits d'après la définition `### BE-243 — Export de données par sujet ou tenant`
de implementation-backend/tasks-exploitation-architecture.md, avant le code.

Routes cibles :
- `POST /api/v1/exports` : demande d'export (périmètre `tenant` ou `sujet`) ;
- `GET /api/v1/exports/{export_id}` : statut du job ;
- `GET /api/v1/exports/{export_id}/download` : contenu, 410 une fois expiré.

Table `export_jobs` (migration de BE-243) : id, organizationId, demandeur, perimetre,
statut, expireAt, empreinte, contenu (JSON, purgé à l'expiration), creeAt.

Écarts et choix provisoires, consignés ici et dans app/exports/ (QE-EXP-xx) :
- la colonne `tenantId` de la définition est nommée `organizationId`, comme dans
  app/audit/models.py (BE-173) ;
- la permission d'export n'a pas de nom dans la définition (NON DÉFINI) : `donnees.export.creer`
  est retenue, accordée au propriétaire ;
- la durée de préparation et d'expiration n'est pas définie (QE-EXP-12) : la durée est lue de
  `EXPORT_EXPIRATION_SECONDS`, sans valeur par défaut ; sans configuration, 503 et aucune ligne ;
- le contenu d'un export est une liste d'enregistrements de membres (identité, sans secret),
  faute de liste de données de sujet dans la définition.

Couverture :
- CA-1 : export limité au sujet ou au tenant demandé ; sujet hors tenant refusé (404) ;
- CA-2 : téléchargement d'un export expiré renvoie 410 ; export valide, empreinte vérifiée ;
- CA-3 : sans permission, 403, aucun job, refus journalisé ;
- CA-4 : un export ne contient jamais les données d'un autre tenant ; job ou tenant d'un autre
  tenant renvoie 404 ; aucun secret dans le contenu ;
- CA-5 : la purge efface le contenu d'un export expiré ; lien public interdit (401 sans jeton).
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from tests.conftest import unique_email

ROUTE = "/api/v1/exports"
MOT_DE_PASSE = "TestPassword123!"
DUREE_EXPIRATION_SECONDES = 3600
ACTION_REFUS = "donnees.export.refus"


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _configurer_expiration(monkeypatch) -> None:
    """Fixe la durée de rétention de la configuration de test (pas de valeur par défaut dans le code)."""
    monkeypatch.setattr(settings, "EXPORT_EXPIRATION_SECONDS", DUREE_EXPIRATION_SECONDES, raising=False)


async def _inscrire_et_connecter(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE243"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return {"id": str(user.id), "email": email, "accessToken": login.json()["accessToken"]}


async def _rattacher(utilisateur: dict, organization_id: str) -> None:
    """Rattache un utilisateur comme membre actif, sans rôle (donc sans `donnees.export.creer`)."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(utilisateur["id"])))
        await db.commit()


async def _id_de(utilisateur: dict) -> str:
    async with AsyncSessionLocal() as db:
        return str((await db.execute(select(User).where(User.email == utilisateur["email"]))).scalar_one().id)


async def _creer_organisation_autre(client: AsyncClient) -> dict:
    """Second tenant, avec son propriétaire : sert à vérifier l'isolation (CA-4)."""
    proprietaire = await _inscrire_et_connecter(client)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org", "slug": f"autre-org-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['accessToken']}"},
    )
    assert res.status_code in (200, 201), res.text
    return {"id": res.json()["id"], "proprietaire": proprietaire}


async def _nombre_de_jobs(organization_id: str) -> int:
    from app.exports.models import ExportJob

    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(ExportJob).where(ExportJob.organizationId == uuid.UUID(organization_id))
            )
        ).scalar_one()


async def _demander(client: AsyncClient, utilisateur: dict, organization_id: str, perimetre: dict) -> "httpx.Response":
    return await client.post(
        ROUTE, json={"perimetre": perimetre}, headers=_entetes(utilisateur["accessToken"], organization_id)
    )


async def _creer_export_tenant(client: AsyncClient, utilisateur: dict, organization_id: str) -> str:
    res = await _demander(client, utilisateur, organization_id, {"type": "tenant"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _expirer(export_id: str) -> None:
    from app.exports.models import ExportJob

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ExportJob)
            .where(ExportJob.id == uuid.UUID(export_id))
            .values(expireAt=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await db.commit()


async def test_be243_ca1_export_sujet_ne_contient_que_le_sujet(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-1 : un export de périmètre `sujet` ne contient que ce sujet, pas les autres membres."""
    _configurer_expiration(monkeypatch)
    sujet = await _inscrire_et_connecter(client)
    await _rattacher(sujet, organization["id"])

    res = await _demander(client, registered_user, organization["id"], {"type": "sujet", "sujetId": sujet["id"]})
    assert res.status_code == 201, res.text

    telechargement = await client.get(
        f"{ROUTE}/{res.json()['id']}/download", headers=_entetes(registered_user["accessToken"], organization["id"])
    )
    assert telechargement.status_code == 200, telechargement.text
    courriels = [enregistrement["email"] for enregistrement in telechargement.json()["contenu"]]
    assert sujet["email"] in courriels
    assert registered_user["email"] not in courriels


async def test_be243_ca1_sujet_hors_tenant_renvoie_404_sans_job(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-1 (validation de portée) : un sujet qui n'est pas membre de l'organisation est refusé en 404."""
    _configurer_expiration(monkeypatch)
    etranger = await _inscrire_et_connecter(client)
    avant = await _nombre_de_jobs(organization["id"])

    res = await _demander(client, registered_user, organization["id"], {"type": "sujet", "sujetId": etranger["id"]})

    assert res.status_code == 404, res.text
    assert await _nombre_de_jobs(organization["id"]) == avant


async def test_be243_ca2_telechargement_expire_renvoie_410(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-2 : un export dont l'expiration est passée n'est plus téléchargeable (410) et son statut vaut `expire`."""
    _configurer_expiration(monkeypatch)
    export_id = await _creer_export_tenant(client, registered_user, organization["id"])
    await _expirer(export_id)
    entetes = _entetes(registered_user["accessToken"], organization["id"])

    telechargement = await client.get(f"{ROUTE}/{export_id}/download", headers=entetes)
    statut = await client.get(f"{ROUTE}/{export_id}", headers=entetes)

    assert telechargement.status_code == 410, telechargement.text
    assert statut.status_code == 200, statut.text
    assert statut.json()["statut"] == "expire"


async def test_be243_ca2_telechargement_valide_renvoie_contenu_et_empreinte(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-2 (empreinte) : avant expiration, le contenu est livré et son empreinte SHA-256 correspond.

    Forme canonique retenue : JSON trié par clés, séparateurs compacts, UTF-8 (voir app/exports/service.py)."""
    _configurer_expiration(monkeypatch)
    export_id = await _creer_export_tenant(client, registered_user, organization["id"])
    entetes = _entetes(registered_user["accessToken"], organization["id"])

    statut = await client.get(f"{ROUTE}/{export_id}", headers=entetes)
    telechargement = await client.get(f"{ROUTE}/{export_id}/download", headers=entetes)

    assert statut.status_code == 200, statut.text
    assert telechargement.status_code == 200, telechargement.text
    corps = telechargement.json()
    canonique = json.dumps(corps["contenu"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert statut.json()["empreinte"] == hashlib.sha256(canonique.encode("utf-8")).hexdigest()


async def test_be243_ca3_sans_permission_renvoie_403_journalise_sans_job(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-3 : un membre sans `donnees.export.creer` reçoit 403, aucun job n'est créé et le refus est journalisé."""
    from app.audit.models import AuditEvent

    _configurer_expiration(monkeypatch)
    membre = await _inscrire_et_connecter(client)
    await _rattacher(membre, organization["id"])
    avant = await _nombre_de_jobs(organization["id"])

    res = await _demander(client, membre, organization["id"], {"type": "tenant"})

    assert res.status_code == 403, res.text
    assert await _nombre_de_jobs(organization["id"]) == avant
    async with AsyncSessionLocal() as db:
        refus = (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.organizationId == uuid.UUID(organization["id"]),
                    AuditEvent.action == ACTION_REFUS,
                )
            )
        ).scalars().all()
    assert len(refus) == 1
    assert str(refus[0].actorUserId) == membre["id"]


async def test_be243_ca4_export_tenant_ne_contient_aucune_donnee_d_un_autre_tenant(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-4 : le membre d'un autre tenant n'apparaît jamais dans l'export du tenant courant."""
    _configurer_expiration(monkeypatch)
    autre = await _creer_organisation_autre(client)

    export_id = await _creer_export_tenant(client, registered_user, organization["id"])
    telechargement = await client.get(
        f"{ROUTE}/{export_id}/download", headers=_entetes(registered_user["accessToken"], organization["id"])
    )

    assert telechargement.status_code == 200, telechargement.text
    courriels = [enregistrement["email"] for enregistrement in telechargement.json()["contenu"]]
    assert autre["proprietaire"]["email"] not in courriels
    assert registered_user["email"] in courriels


async def test_be243_ca4_job_ou_tenant_d_un_autre_tenant_renvoie_404(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-4 : un job d'un autre tenant est introuvable (404), et une demande visant un autre tenant aussi."""
    _configurer_expiration(monkeypatch)
    autre = await _creer_organisation_autre(client)
    export_autre = await _creer_export_tenant(client, autre["proprietaire"], autre["id"])

    lecture = await client.get(
        f"{ROUTE}/{export_autre}", headers=_entetes(registered_user["accessToken"], organization["id"])
    )
    demande = await client.post(
        ROUTE,
        json={"perimetre": {"type": "tenant", "tenantId": autre["id"]}},
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert lecture.status_code == 404, lecture.text
    assert demande.status_code == 404, demande.text


async def test_be243_ca4_contenu_sans_secret(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    """CA-4 (données sensibles) : le contenu ne contient ni mot de passe haché ni champ de secret."""
    _configurer_expiration(monkeypatch)
    export_id = await _creer_export_tenant(client, registered_user, organization["id"])

    telechargement = await client.get(
        f"{ROUTE}/{export_id}/download", headers=_entetes(registered_user["accessToken"], organization["id"])
    )

    assert telechargement.status_code == 200, telechargement.text
    texte = json.dumps(telechargement.json()["contenu"])
    assert "hashedPassword" not in texte
    assert "$argon" not in texte and "$2b$" not in texte


async def test_be243_ca5_purge_efface_le_contenu_expire(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-5 : la purge efface le contenu d'un export expiré ; aucune copie ne reste au-delà de l'expiration."""
    from app.exports.models import ExportJob
    from app.exports.service import purger_exports_expires

    _configurer_expiration(monkeypatch)
    export_id = await _creer_export_tenant(client, registered_user, organization["id"])
    await _expirer(export_id)

    async with AsyncSessionLocal() as db:
        await purger_exports_expires(db)
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(ExportJob).where(ExportJob.id == uuid.UUID(export_id)))).scalar_one()
    assert job.contenu is None


async def test_be243_sans_configuration_renvoie_503_sans_ligne(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """Sans durée d'expiration configurée (pas de valeur par défaut), la demande est refusée en 503 sans ligne."""
    monkeypatch.setattr(settings, "EXPORT_EXPIRATION_SECONDS", None, raising=False)
    avant = await _nombre_de_jobs(organization["id"])

    res = await _demander(client, registered_user, organization["id"], {"type": "tenant"})

    assert res.status_code == 503, res.text
    assert await _nombre_de_jobs(organization["id"]) == avant


async def test_be243_ca5_telechargement_sans_jeton_renvoie_401(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """CA-5 (lien public interdit) : le téléchargement exige une session authentifiée."""
    _configurer_expiration(monkeypatch)
    export_id = await _creer_export_tenant(client, registered_user, organization["id"])

    res = await client.get(f"{ROUTE}/{export_id}/download", headers={"X-Organization-Id": organization["id"]})

    assert res.status_code == 401, res.text
