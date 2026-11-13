"""BE-099 : historique commercial consultable par portée (GET /api/v1/billing/history).

Intention : prouver les critères d'acceptation de BE-099
(implementation-backend/tasks-abonnements-facturation.md, section BE-099), écrits
d'après la définition avant le code :
- CA-1 : la liste ne retourne que les entrées du scope de l'appelant, avec pagination ;
- CA-2 : un appelant sans permission reçoit `FORBIDDEN` (403) ;
- CA-3 : isolation tenant : aucune entrée du tenant A pour le tenant B, même avec un filtre forgé ;
- CA-4 : la réponse n'expose aucun secret de paiement (test de payload).

Source de l'historique : la table `audit_event` (BE-007), alimentée par BE-073 (préfixe
`billing.`). Aucune table nouvelle. Les champs de visibilité et de rétention sont NON DÉFINIS
(QE-FAC-13) : les tests fixent le contrat retenu (permission `billing.history.read`,
réponse sans le détail `changes`).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select, text

from app.billing.audit import record_audit_entry
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User

MOT_DE_PASSE = "TestPassword123!"
URL_HISTORIQUE = "/api/v1/billing/history"
PAN_FACTICE = "4111111111111111"
SECRET_FACTICE = "secret-checkout-token-be099"


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation, sans permission d'historique ; retourne son jeton."""
    cree = await client.post("/api/v1/auth/register", json={
        "email": f"be099-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-099",
    })
    login = await client.post("/api/v1/auth/login", json={"email": cree.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(cree.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _autre_organisation(client: AsyncClient) -> tuple[str, str]:
    """Second tenant avec son propre propriétaire ; retourne (identifiant de l'organisation, jeton du propriétaire)."""
    email = f"be099-tenant-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Autre tenant"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jeton = login.json()["accessToken"]
    cree = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre org BE-099", "slug": f"be099-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return cree.json()["id"], jeton


async def _ecrire_entrees(tenant_id: uuid.UUID, acteur_id: uuid.UUID, nombre: int, marque: str, apres: dict | None = None) -> list[uuid.UUID]:
    """Écrit `nombre` entrées d'audit `billing.consent.record` dans le tenant ; retourne leurs identifiants."""
    identifiants = []
    async with AsyncSessionLocal() as db:
        for numero in range(nombre):
            cible = uuid.uuid4()
            entree = await record_audit_entry(
                db, tenant_id, acteur_id,
                action="billing.consent.record",
                scope="payeur",
                target_type="consent_record",
                target_id=cible,
                before_json=None,
                after_json=apres or {"marque": marque, "numero": numero},
                summary=f"Entrée d'historique BE-099 {marque} {numero}.",
            )
            await db.flush()
            identifiants.append(entree.id)
        await db.commit()
    return identifiants


async def _nombre_entrees_billing(tenant_id: uuid.UUID) -> int:
    """Nombre d'entrées `billing.*` du tenant en base : référence calculée, pas une valeur figée."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(text(
            "SELECT count(*) FROM audit_event WHERE \"organizationId\" = :tenant AND action LIKE 'billing.%'"
        ), {"tenant": tenant_id})


async def test_ca1_liste_limitee_au_scope_et_paginee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : seules les entrées `billing.*` du tenant courant sont listées ; la pagination est honorée."""
    org_id = uuid.UUID(organization["id"])
    acteur = uuid.UUID(await _id_utilisateur_depuis_jeton(client, registered_user))
    ecrites = await _ecrire_entrees(org_id, acteur, 3, "ca1")
    attendu_total = await _nombre_entrees_billing(org_id)

    reponse = await client.get(
        URL_HISTORIQUE,
        params={"limit": 2, "offset": 0},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["meta"]["total"] == attendu_total
    assert corps["meta"]["limit"] == 2
    assert corps["meta"]["offset"] == 0
    assert len(corps["data"]) == 2
    assert all(entree["action"].startswith("billing.") for entree in corps["data"])

    # Page complète : les trois entrées écrites ici figurent bien dans le tenant.
    complete = await client.get(
        URL_HISTORIQUE,
        params={"limit": 100},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )
    ids = {uuid.UUID(entree["id"]) for entree in complete.json()["data"]}
    assert set(ecrites) <= ids
    assert complete.json()["meta"]["total"] == attendu_total


async def test_ca2_sans_permission_renvoie_forbidden(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : un membre sans `billing.history.read` reçoit 403 FORBIDDEN."""
    org_id = uuid.UUID(organization["id"])
    jeton_sans_droit = await _membre_sans_droit(client, org_id)

    reponse = await client.get(URL_HISTORIQUE, headers=_entete(jeton_sans_droit, organization["id"]))

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"


async def test_ca3_isolation_tenant_meme_avec_filtre_forge(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : aucune entrée du tenant A ne sort pour le tenant B, même avec un `organizationId` forgé en paramètre."""
    org_a = uuid.UUID(organization["id"])
    acteur_a = uuid.UUID(await _id_utilisateur_depuis_jeton(client, registered_user))
    entrees_a = await _ecrire_entrees(org_a, acteur_a, 2, "tenant-a")

    org_b_id, jeton_b = await _autre_organisation(client)
    acteur_b = uuid.UUID(await _id_utilisateur_depuis_jeton(client, {"accessToken": jeton_b}))
    entrees_b = await _ecrire_entrees(uuid.UUID(org_b_id), acteur_b, 1, "tenant-b")

    reponse = await client.get(
        URL_HISTORIQUE,
        params={"limit": 100, "organizationId": str(org_a), "organization_id": str(org_a)},
        headers=_entete(jeton_b, org_b_id),
    )

    assert reponse.status_code == 200, reponse.text
    ids = {uuid.UUID(entree["id"]) for entree in reponse.json()["data"]}
    assert not (set(entrees_a) & ids)
    assert set(entrees_b) <= ids
    assert str(org_a) not in reponse.text


async def test_ca3_organisation_etrangere_sans_appartenance_renvoie_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (complément) : un appelant qui n'est pas membre du tenant demandé reçoit 404, sans donnée."""
    org_b_id, _ = await _autre_organisation(client)

    reponse = await client.get(URL_HISTORIQUE, headers=_entete(registered_user["accessToken"], org_b_id))

    assert reponse.status_code == 404, reponse.text
    assert "billing." not in reponse.text


async def test_ca4_reponse_sans_secret_de_paiement(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : même si une entrée porte un PAN et un secret dans son détail, la réponse ne les expose pas.

    Le détail `changes` (états avant et après) n'est pas renvoyé : seules les colonnes de
    résumé sont exposées.
    """
    org_id = uuid.UUID(organization["id"])
    acteur = uuid.UUID(await _id_utilisateur_depuis_jeton(client, registered_user))
    await _ecrire_entrees(org_id, acteur, 1, "secret", apres={
        "carte": PAN_FACTICE, "checkoutUrl": f"https://pay.example.test/{SECRET_FACTICE}",
    })

    reponse = await client.get(
        URL_HISTORIQUE,
        params={"limit": 100},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    texte = reponse.text
    assert PAN_FACTICE not in texte
    assert SECRET_FACTICE not in texte
    assert "checkoutUrl" not in texte
    for entree in reponse.json()["data"]:
        assert "changes" not in entree
        assert "ipAddress" not in entree
        assert "userAgent" not in entree


async def _id_utilisateur_depuis_jeton(client: AsyncClient, utilisateur: dict) -> str:
    """Identifiant de l'utilisateur authentifié par son jeton (route de profil du socle)."""
    reponse = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {utilisateur['accessToken']}"})
    return reponse.json()["id"]
