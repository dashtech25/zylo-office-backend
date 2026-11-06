"""BE-213 : jobs d'import et d'export (création, statut, annulation, téléchargement).

Tests écrits d'après la définition `### BE-213` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Dépendance non fusionnée : BE-190 (RBAC serveur). Les permissions de test sont posées
avec les tables RBAC de develop (Role, Permission, RolePermission, UserRole), comme dans
test_be017_grants_membres.py. À réaligner sur la table `grant` et les routes de rôles de
BE-190 quand celle-ci sera fusionnée.

Formes non définies par la fiche, retenues ici (à valider, QE-API-01 et QE-API-27) :
- corps de POST /api/v1/jobs : {"type", "manifestSchemaVersion", "idempotencyKey"} ;
  réponse : objet portant `jobId` et `state` ;
- types de job : "export.clients" (permission `jobs.export.create`) et "import.clients"
  (permission `jobs.import.create`) ;
- table `job` : modèle `app.jobs.models.Job`, champs de la fiche (`jobId`, `tenantId`,
  `actorId`, `type`, `manifestSchemaVersion`, `state`, `idempotencyKey`, `filePointer`,
  `expiresAt`) ;
- worker : fonction `app.jobs.worker.traiter_job(db, job_id, interrompre_apres=None)` ;
  `interrompre_apres=n` arrête le worker après n lots, sans état terminal.

Couverture (critères d'acceptation de BE-213) :
- CA-1 : téléchargement par un autre tenant renvoie 404 (test d'isolation) ;
- CA-2 : un doublon d'import avec la même `idempotencyKey` ne réimporte rien ;
- CA-3 : un fichier expiré renvoie 404 `EXPORT_EXPIRED` ;
- CA-4 : CreateJob sans permission du type renvoie 403 (test de refus) ;
- CA-5 : un job interrompu reprend et aboutit au même résultat qu'un job non interrompu ;
- CA-6 : un téléchargement pendant la génération renvoie 409 `DOCUMENT_NOT_READY`.

Point ouvert : la reprise (CA-5) exige que le type "export.clients" produise au moins
deux lots ; les données sources de ce type ne sont pas définies. Le jeu de données de test
reste à compléter quand le type sera défini.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
TYPE_EXPORT = "export.clients"
TYPE_IMPORT = "import.clients"
PERMISSION_EXPORT = "jobs.export.create"
PERMISSION_IMPORT = "jobs.import.create"


def _modele_job():
    """Modèle de la table `job` (à créer par BE-213). Import tardif : chaque test échoue sur son propre point."""
    from app.jobs.models import Job

    return Job


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be213-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    assert me.status_code == 200, me.text
    return {"authorization": f"Bearer {jetons['accessToken']}", "userId": me.json()["id"]}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    """Crée une organisation ; son créateur en devient propriétaire et membre."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be213-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _entetes(acteur: dict, organisation_id: str) -> dict:
    return {"Authorization": acteur["authorization"], "X-Organization-Id": organisation_id}


async def _permission(db, code: str) -> Permission:
    """Permission par code ; créée si elle n'existe pas encore dans la base de test."""
    permission = await db.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        permission = Permission(code=code, moduleCode="jobs", description="Permission de test BE-213")
        db.add(permission)
        await db.flush()
    return permission


async def _membre(organisation_id: str, utilisateur_id: str) -> None:
    """Rattache l'utilisateur à l'organisation, sans rôle."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _donner_permissions(organisation_id: str, utilisateur_id: str, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle transverse ne contenant que ces permissions."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org, code=f"be213-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-213")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await _permission(db, code)
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _job_en_base(
    organisation_id: str,
    acteur_id: str,
    *,
    etat: str,
    type_job: str = TYPE_EXPORT,
    expire_le: datetime | None = None,
    pointeur: str | None = None,
    cle: str | None = None,
) -> str:
    """Insère directement un job dans la table `job`, dans l'état demandé."""
    Job = _modele_job()
    async with AsyncSessionLocal() as db:
        tenant_id = (
            await db.execute(select(Organization.tenantId).where(Organization.id == uuid.UUID(organisation_id)))
        ).scalar_one()
        job = Job(
            tenantId=tenant_id,
            actorId=uuid.UUID(acteur_id),
            type=type_job,
            manifestSchemaVersion=1,
            state=etat,
            idempotencyKey=cle,
            filePointer=pointeur,
            expiresAt=expire_le,
        )
        db.add(job)
        await db.commit()
        return str(job.jobId)


async def _nombre_jobs(organisation_id: str, cle: str | None = None) -> int:
    """Nombre de jobs du tenant de l'organisation, filtrable par `idempotencyKey`."""
    Job = _modele_job()
    async with AsyncSessionLocal() as db:
        tenant_id = (
            await db.execute(select(Organization.tenantId).where(Organization.id == uuid.UUID(organisation_id)))
        ).scalar_one()
        stmt = select(func.count(Job.jobId)).where(Job.tenantId == tenant_id)
        if cle is not None:
            stmt = stmt.where(Job.idempotencyKey == cle)
        return (await db.scalar(stmt)) or 0


async def _creer_job(client: AsyncClient, acteur: dict, organisation_id: str, type_job: str, cle: str):
    return await client.post(
        "/api/v1/jobs",
        json={"type": type_job, "manifestSchemaVersion": 1, "idempotencyKey": cle},
        headers=_entetes(acteur, organisation_id),
    )


async def test_ca1_telechargement_par_un_autre_tenant_renvoie_404(client: AsyncClient):
    emetteur = await _inscrire_et_connecter(client, "Émetteur")
    org_1 = await _creer_organisation(client, emetteur, "Tenant un")
    await _donner_permissions(org_1, emetteur["userId"], [PERMISSION_EXPORT])

    intrus = await _inscrire_et_connecter(client, "Intrus")
    org_2 = await _creer_organisation(client, intrus, "Tenant deux")
    await _donner_permissions(org_2, intrus["userId"], [PERMISSION_EXPORT])

    job_id = await _job_en_base(
        org_1, emetteur["userId"], etat="succeeded", pointeur="exports/tenant-un.csv", expire_le=_maintenant() + timedelta(days=7)
    )

    # Témoin : le tenant propriétaire télécharge bien son fichier.
    controle = await client.get(f"/api/v1/jobs/{job_id}/download", headers=_entetes(emetteur, org_1))
    assert controle.status_code == 200, controle.text

    download = await client.get(f"/api/v1/jobs/{job_id}/download", headers=_entetes(intrus, org_2))
    assert download.status_code == 404, download.text

    lecture = await client.get(f"/api/v1/jobs/{job_id}", headers=_entetes(intrus, org_2))
    assert lecture.status_code == 404, lecture.text


async def test_ca2_doublon_idempotency_key_ne_reimporte_rien(client: AsyncClient):
    acteur = await _inscrire_et_connecter(client, "Importeur")
    org = await _creer_organisation(client, acteur, "Import idempotent")
    await _donner_permissions(org, acteur["userId"], [PERMISSION_IMPORT])
    cle = f"imp-{uuid.uuid4().hex}"

    premier = await _creer_job(client, acteur, org, TYPE_IMPORT, cle)
    assert premier.status_code == 201, premier.text

    second = await _creer_job(client, acteur, org, TYPE_IMPORT, cle)
    assert second.status_code in (200, 201), second.text
    assert second.json()["jobId"] == premier.json()["jobId"]

    assert await _nombre_jobs(org, cle) == 1


async def test_ca3_fichier_expire_renvoie_404_export_expired(client: AsyncClient):
    acteur = await _inscrire_et_connecter(client, "Exportateur")
    org = await _creer_organisation(client, acteur, "Export expiré")
    await _donner_permissions(org, acteur["userId"], [PERMISSION_EXPORT])
    hier = _maintenant() - timedelta(days=1)

    expire = await _job_en_base(org, acteur["userId"], etat="expired", pointeur="exports/vieux.csv", expire_le=hier)
    reponse = await client.get(f"/api/v1/jobs/{expire}/download", headers=_entetes(acteur, org))
    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "EXPORT_EXPIRED"

    # Témoin : un fichier encore valide reste téléchargeable.
    valide = await _job_en_base(
        org, acteur["userId"], etat="succeeded", pointeur="exports/recent.csv", expire_le=_maintenant() + timedelta(days=7)
    )
    controle = await client.get(f"/api/v1/jobs/{valide}/download", headers=_entetes(acteur, org))
    assert controle.status_code == 200, controle.text


async def test_ca4_createjob_sans_permission_du_type_renvoie_403(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    org = await _creer_organisation(client, proprietaire, "Refus de droits")
    membre = await _inscrire_et_connecter(client, "Membre sans droit")
    await _membre(org, membre["userId"])

    refus = await _creer_job(client, membre, org, TYPE_EXPORT, f"exp-{uuid.uuid4().hex}")
    assert refus.status_code == 403, refus.text
    assert await _nombre_jobs(org) == 0

    # Permission d'un autre type : ne suffit pas pour un export.
    await _donner_permissions(org, membre["userId"], [PERMISSION_IMPORT])
    autre_type = await _creer_job(client, membre, org, TYPE_EXPORT, f"exp-{uuid.uuid4().hex}")
    assert autre_type.status_code == 403, autre_type.text
    assert await _nombre_jobs(org) == 0

    # Témoin : la permission du type accordée, la même demande aboutit.
    await _donner_permissions(org, membre["userId"], [PERMISSION_EXPORT])
    ok = await _creer_job(client, membre, org, TYPE_EXPORT, f"exp-{uuid.uuid4().hex}")
    assert ok.status_code == 201, ok.text


async def test_ca5_job_interrompu_reprend_au_meme_resultat(client: AsyncClient):
    from app.jobs.worker import traiter_job

    acteur = await _inscrire_et_connecter(client, "Reprise")
    org = await _creer_organisation(client, acteur, "Reprise de job")
    await _donner_permissions(org, acteur["userId"], [PERMISSION_EXPORT])

    reference = await _creer_job(client, acteur, org, TYPE_EXPORT, f"ref-{uuid.uuid4().hex}")
    assert reference.status_code == 201, reference.text
    ref_id = reference.json()["jobId"]
    interrompu = await _creer_job(client, acteur, org, TYPE_EXPORT, f"int-{uuid.uuid4().hex}")
    assert interrompu.status_code == 201, interrompu.text
    int_id = interrompu.json()["jobId"]

    async with AsyncSessionLocal() as db:
        await traiter_job(db, uuid.UUID(ref_id))
        await db.commit()

    async with AsyncSessionLocal() as db:
        await traiter_job(db, uuid.UUID(int_id), interrompre_apres=1)
        await db.commit()

    milieu = await client.get(f"/api/v1/jobs/{int_id}", headers=_entetes(acteur, org))
    assert milieu.status_code == 200, milieu.text
    assert milieu.json()["state"] in ("queued", "running"), milieu.text

    async with AsyncSessionLocal() as db:
        await traiter_job(db, uuid.UUID(int_id))
        await db.commit()

    for job_id in (ref_id, int_id):
        statut = await client.get(f"/api/v1/jobs/{job_id}", headers=_entetes(acteur, org))
        assert statut.status_code == 200, statut.text
        assert statut.json()["state"] == "succeeded", statut.text

    fichier_ref = await client.get(f"/api/v1/jobs/{ref_id}/download", headers=_entetes(acteur, org))
    fichier_int = await client.get(f"/api/v1/jobs/{int_id}/download", headers=_entetes(acteur, org))
    assert fichier_ref.status_code == 200, fichier_ref.text
    assert fichier_int.status_code == 200, fichier_int.text
    assert fichier_int.content == fichier_ref.content


@pytest.mark.parametrize("etat", ["queued", "running"])
async def test_ca6_telechargement_pendant_generation_renvoie_409(client: AsyncClient, etat: str):
    acteur = await _inscrire_et_connecter(client, "Patience")
    org = await _creer_organisation(client, acteur, "Génération en cours")
    await _donner_permissions(org, acteur["userId"], [PERMISSION_EXPORT])

    job_id = await _job_en_base(org, acteur["userId"], etat=etat)
    reponse = await client.get(f"/api/v1/jobs/{job_id}/download", headers=_entetes(acteur, org))
    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "DOCUMENT_NOT_READY"
