"""BE-246 : suppression, hold et attestation de sortie de tenant.

Tests écrits d'après la définition `### BE-246 — Suppression, hold et attestation de sortie de tenant`
de implementation-backend/tasks-exploitation-architecture.md, avant le code.

Routes cibles :
- `POST /api/v1/organizations/{organization_id}/exit` : demande de sortie (201) ;
- `GET /api/v1/organizations/{organization_id}/exit/attestation` : attestation de la dernière sortie.

Tables cibles (migration de BE-246) : `tenant_exit_requests` et `legal_holds`.

Écarts et choix consignés dans app/sortie_tenant/ :
- l'approbation est une seconde personne désignée dans la demande (`approbateurId`), distincte du
  demandeur et titulaire de la permission (QE-EXP-15, recommandation appliquée) ;
- la permission de décision `donnees.sortie.decider` n'est accordée à aucun rôle par défaut ;
- un hold est posé par le service (`poser_hold`) : la définition ne prévoit pas de route de pose ;
- un hold actif vise tout le tenant : la sortie n'efface rien et l'attestation le déclare.

Couverture :
- CA-1 : sortie avec hold actif, aucune ligne du tenant n'est supprimée ;
- CA-2 : chaque table à `organizationId` est couverte par le plan (effacée ou conservée avec motif),
  les cinq catégories (primaire, index, fichiers, caches, logs) sont présentes ; l'exécution vide les
  tables effacées du tenant ;
- CA-3 : l'attestation liste ce qui est effacé, différé et conservé ;
- CA-4 : sortie sans droit (ou approbation par le demandeur) donne 403, refus journalisé ;
- CA-5 : la suspension seule ne supprime aucune donnée.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.rbac.models import Permission, Role, RolePermission, UserRole
from app.sortie_tenant.models import LegalHold, TenantExitRequest
from app.sortie_tenant.permissions import SORTIE_TENANT_DECIDER
from app.sortie_tenant.service import CATEGORIES, TABLES_PROTEGEES, plan_de_suppression, poser_hold
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
ROUTE = "/api/v1/organizations"


def _entetes(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _inscrire_et_connecter(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE246"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return {"id": str(user.id), "accessToken": login.json()["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    res = await client.post(
        ROUTE,
        json={"name": "Org BE246", "slug": f"org-be246-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire["accessToken"]),
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _rattacher(utilisateur: dict, organization_id: str, permissions: list[str]) -> None:
    """Membre actif de l'organisation ; si `permissions` est non vide, rôle transverse qui les porte."""
    org = uuid.UUID(organization_id)
    user = uuid.UUID(utilisateur["id"])
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if permissions:
            role = Role(organizationId=org, code=f"be246-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-246")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await db.scalar(select(Permission).where(Permission.code == code))
                if permission is None:
                    permission = Permission(code=code, moduleCode="donnees", description="Permission de test BE-246")
                    db.add(permission)
                    await db.flush()
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _scenario(client: AsyncClient) -> dict:
    """Un tenant avec un propriétaire, un demandeur et un approbateur, tous deux titulaires de la décision."""
    proprietaire = await _inscrire_et_connecter(client)
    org_id = await _organisation(client, proprietaire)
    demandeur = await _inscrire_et_connecter(client)
    approbateur = await _inscrire_et_connecter(client)
    await _rattacher(demandeur, org_id, [SORTIE_TENANT_DECIDER])
    await _rattacher(approbateur, org_id, [SORTIE_TENANT_DECIDER])
    return {"org": org_id, "demandeur": demandeur, "approbateur": approbateur, "proprietaire": proprietaire}


async def _tables_du_tenant() -> list[str]:
    """Tables du schéma migré portant une colonne `organizationId` (lu en base, pas dans les modèles)."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'organizationId' ORDER BY table_name"
            )
        )
        return list(res.scalars().all())


async def _compter(organization_id: str) -> dict[str, int]:
    """Nombre de lignes par table à `organizationId`, pour le tenant donné."""
    compte = {}
    async with AsyncSessionLocal() as db:
        for table in await _tables_du_tenant():
            res = await db.execute(
                text(f'SELECT count(*) FROM "{table}" WHERE "organizationId" = :org'),
                {"org": uuid.UUID(organization_id)},
            )
            compte[table] = res.scalar_one()
    return compte


async def _demander_sortie(client: AsyncClient, demandeur: dict, org_id: str, approbateur: dict) -> "httpx.Response":
    return await client.post(
        f"{ROUTE}/{org_id}/exit",
        json={"motif": "Fin de contrat", "approbateurId": approbateur["id"]},
        headers=_entetes(demandeur["accessToken"]),
    )


async def test_ca1_sortie_avec_hold_actif_ne_supprime_rien(client: AsyncClient):
    """CA-1 : un hold actif tient tout le tenant, la sortie n'efface aucune ligne (hors preuves)."""
    scenario = await _scenario(client)
    async with AsyncSessionLocal() as db:
        await poser_hold(db, uuid.UUID(scenario["org"]), "Litige en cours", uuid.UUID(scenario["proprietaire"]["id"]))
    avant = await _compter(scenario["org"])

    res = await _demander_sortie(client, scenario["demandeur"], scenario["org"], scenario["approbateur"])

    assert res.status_code == 201, res.text
    assert res.json()["etat"] == "tenue"
    apres = await _compter(scenario["org"])
    for table in set(avant) - set(TABLES_PROTEGEES):
        assert apres[table] == avant[table], f"ligne supprimée malgré le hold : {table}"
    assert res.json()["attestation"]["efface"] == []


async def test_ca2_chaque_table_du_tenant_est_couverte_par_le_plan(client: AsyncClient):
    """CA-2 : toute table à `organizationId` est effacée ou conservée avec motif ; cinq catégories."""
    scenario = await _scenario(client)
    async with AsyncSessionLocal() as db:
        plan = await plan_de_suppression(db, uuid.UUID(scenario["org"]))

    couvertes = {etape["table"] for etape in plan["ordre"]} | set(plan["conservees"])
    assert set(await _tables_du_tenant()) <= couvertes
    assert set(plan["categories"]) == set(CATEGORIES) == {"primaire", "index", "fichiers", "caches", "logs"}
    for categorie in CATEGORIES:
        assert plan["categories"][categorie], f"catégorie sans cible : {categorie}"
    assert all(motif.strip() for motif in plan["conservees"].values())


async def test_ca2_la_sortie_efface_le_tenant_et_garde_les_preuves(client: AsyncClient):
    """CA-2 : sans hold, les lignes du tenant hors preuves sont supprimées ; l'organisation reste."""
    scenario = await _scenario(client)
    avant = await _compter(scenario["org"])
    assert avant["organizationUser"] >= 3

    res = await _demander_sortie(client, scenario["demandeur"], scenario["org"], scenario["approbateur"])

    assert res.status_code == 201, res.text
    assert res.json()["etat"] == "terminee"
    apres = await _compter(scenario["org"])
    for table in set(apres) - set(TABLES_PROTEGEES):
        assert apres[table] == 0, f"ligne restante après sortie : {table}"
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text('SELECT count(*) FROM organization WHERE id = :org'), {"org": uuid.UUID(scenario["org"])})).scalar_one() == 1


async def test_ca3_attestation_liste_efface_differe_et_conserve(client: AsyncClient):
    """CA-3 : l'attestation contient les trois listes, avec motifs pour le différé et le conservé."""
    scenario = await _scenario(client)
    await _demander_sortie(client, scenario["demandeur"], scenario["org"], scenario["approbateur"])

    res = await client.get(
        f"{ROUTE}/{scenario['org']}/exit/attestation", headers=_entetes(scenario["demandeur"]["accessToken"])
    )

    assert res.status_code == 200, res.text
    attestation = res.json()
    assert {"efface", "differe", "conserve"} <= set(attestation)
    assert any(ligne["table"] == "organizationUser" and ligne["lignes"] >= 1 for ligne in attestation["efface"])
    assert any(ligne["categorie"] == "index" and ligne["motif"] for ligne in attestation["differe"])
    assert any(ligne["cible"] == "tenant_exit_requests" and ligne["motif"] for ligne in attestation["conserve"])


async def test_ca4_sortie_sans_droit_donne_403_et_est_journalisee(client: AsyncClient):
    """CA-4 : sans permission, 403 et aucune suppression ; le refus est tracé."""
    scenario = await _scenario(client)
    sans_droit = await _inscrire_et_connecter(client)
    await _rattacher(sans_droit, scenario["org"], [])
    avant = await _compter(scenario["org"])

    res = await _demander_sortie(client, sans_droit, scenario["org"], scenario["approbateur"])

    assert res.status_code == 403, res.text
    assert await _compter(scenario["org"]) == avant
    async with AsyncSessionLocal() as db:
        refus = (
            await db.execute(text("SELECT count(*) FROM auditLog WHERE \"organizationId\" = :org AND action = 'donnees.sortie.refus'"), {"org": uuid.UUID(scenario["org"])})
        ).scalar_one()
    assert refus >= 1


async def test_ca4_approbation_par_le_demandeur_donne_403(client: AsyncClient):
    """CA-4 : le demandeur ne peut pas être son propre approbateur."""
    scenario = await _scenario(client)

    res = await _demander_sortie(client, scenario["demandeur"], scenario["org"], scenario["demandeur"])

    assert res.status_code == 403, res.text
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(TenantExitRequest).where(TenantExitRequest.organizationId == uuid.UUID(scenario["org"])))).first() is None


async def test_ca4_attestation_refusee_a_un_tiers(client: AsyncClient):
    """CA-4 : l'attestation n'est lisible que par les parties de la sortie ou un titulaire de la décision."""
    scenario = await _scenario(client)
    await _demander_sortie(client, scenario["demandeur"], scenario["org"], scenario["approbateur"])
    tiers = await _inscrire_et_connecter(client)

    res = await client.get(f"{ROUTE}/{scenario['org']}/exit/attestation", headers=_entetes(tiers["accessToken"]))

    assert res.status_code == 403, res.text


async def test_ca5_suspension_seule_ne_supprime_aucune_donnee(client: AsyncClient):
    """CA-5 : passer le tenant en suspension ne déclenche aucune suppression ni demande de sortie."""
    scenario = await _scenario(client)
    avant = await _compter(scenario["org"])

    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE organization SET status = 'suspended' WHERE id = :org"), {"org": uuid.UUID(scenario["org"])})
        await db.commit()

    assert await _compter(scenario["org"]) == avant
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(TenantExitRequest).where(TenantExitRequest.organizationId == uuid.UUID(scenario["org"])))).first() is None
        assert (await db.execute(select(LegalHold).where(LegalHold.organizationId == uuid.UUID(scenario["org"])))).first() is None
