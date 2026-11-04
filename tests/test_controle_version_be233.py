"""BE-233 : contrôle de version et détection de conflit.

Mécanisme retenu : un numéro de version entier, porté par l'agrégat (colonne
`version`) et renvoyé dans la réponse. Le client le renvoie dans le corps de la
mutation (`version`). Une version obsolète donne 409 `version_conflict`, avec la
version courante et l'horodatage de fraîcheur dans `details`. Le test porte sur
`PATCH /api/v1/organizations/{id}`, premier agrégat versionné.
"""

import asyncio
import uuid
from datetime import datetime

from httpx import AsyncClient


def _entetes(token: str, organization_id: str | None = None) -> dict[str, str]:
    entetes = {"Authorization": f"Bearer {token}"}
    if organization_id is not None:
        entetes["X-Organization-Id"] = organization_id
    return entetes


async def _autre_utilisateur(client: AsyncClient) -> dict:
    """Crée un second compte avec sa propre organisation (tenant distinct)."""
    email = f"be233-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre Test"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login.json()["accessToken"]
    created = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org", "slug": f"be233-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(token),
    )
    return {"token": token, "organization": created.json()}


async def test_mutation_avec_version_obsolete_renvoie_409_sans_ecraser(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : une version obsolète ne modifie ni le nom ni la version."""
    headers = _entetes(registered_user["accessToken"])
    url = f"/api/v1/organizations/{organization['id']}"
    assert organization["version"] == 1

    premiere = await client.patch(url, json={"name": "Nouveau nom", "version": 1}, headers=headers)
    assert premiere.status_code == 200, premiere.text
    assert premiere.json()["version"] == 2

    obsolete = await client.patch(url, json={"name": "Écrasement", "version": 1}, headers=headers)
    assert obsolete.status_code == 409, obsolete.text
    assert obsolete.json()["error"]["code"] == "version_conflict"

    courante = await client.get("/api/v1/organizations/current", headers=_entetes(registered_user["accessToken"], organization["id"]))
    assert courante.json()["name"] == "Nouveau nom"
    assert courante.json()["version"] == 2


async def test_reponse_409_contient_version_courante_et_horodatage(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : contrat de la réponse 409 : enveloppe standard, version courante et horodatage dans details."""
    headers = _entetes(registered_user["accessToken"])
    url = f"/api/v1/organizations/{organization['id']}"
    await client.patch(url, json={"name": "Deuxième", "version": 1}, headers=headers)

    res = await client.patch(url, json={"name": "Obsolète", "version": 1}, headers=headers)

    assert res.status_code == 409
    corps = res.json()
    assert set(corps) == {"error", "request_id"}
    assert set(corps["error"]) == {"code", "message", "field_errors", "details"}
    assert corps["error"]["code"] == "version_conflict"
    assert len(corps["error"]["details"]) == 1
    detail = corps["error"]["details"][0]
    assert detail["versionCourante"] == 2
    horodatage = datetime.fromisoformat(detail["horodatageFraicheur"])
    assert horodatage.tzinfo is not None


async def test_deux_mutations_concurrentes_une_seule_reussit(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : deux mutations partant de la même version ; une seule est appliquée."""
    headers = _entetes(registered_user["accessToken"])
    url = f"/api/v1/organizations/{organization['id']}"

    reponses = await asyncio.gather(
        client.patch(url, json={"name": "Alpha", "version": 1}, headers=headers),
        client.patch(url, json={"name": "Beta", "version": 1}, headers=headers),
    )

    assert sorted(r.status_code for r in reponses) == [200, 409]
    courante = await client.get("/api/v1/organizations/current", headers=_entetes(registered_user["accessToken"], organization["id"]))
    assert courante.json()["version"] == 2
    assert courante.json()["name"] in {"Alpha", "Beta"}


async def test_version_d_un_tenant_invisible_d_un_autre_tenant(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : la version d'un tenant n'apparaît pas dans un autre tenant."""
    autre = await _autre_utilisateur(client)
    # Le tenant A passe en version 2 ; le tenant B doit rester en version 1.
    await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Tenant A modifié", "version": 1},
        headers=_entetes(registered_user["accessToken"]),
    )

    courante_b = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(autre["token"], autre["organization"]["id"]),
    )
    assert courante_b.status_code == 200
    assert courante_b.json()["version"] == 1

    # L'utilisateur B ne lit pas le tenant A, et la réponse ne livre pas sa version.
    lecture_croisee = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(autre["token"], organization["id"]),
    )
    assert lecture_croisee.status_code in (403, 404)
    assert "versionCourante" not in lecture_croisee.text

    # Une mutation croisée avec une version obsolète n'est ni appliquée ni signalée
    # comme conflit avec la version du tenant A.
    ecriture_croisee = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Intrusion", "version": 1},
        headers=_entetes(autre["token"]),
    )
    assert ecriture_croisee.status_code in (403, 404)
    assert "versionCourante" not in ecriture_croisee.text


async def test_mutation_sans_version_reste_acceptee_et_incremente_la_version(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Sans champ `version`, la mutation n'a pas de contrôle de conflit, mais la version avance."""
    headers = _entetes(registered_user["accessToken"])
    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}", json={"name": "Sans version"}, headers=headers
    )
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 2
