"""BE-043 : consultation du catalogue avec visibilité.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-043) avant le code. Routes publiques, sans authentification ni tenant :
`GET /api/v1/catalog/modules` (liste) et `GET /api/v1/catalog/modules/{slug}` (fiche).

Décisions de test :
- le `slug` du catalogue est la colonne `module.code` (BE-040) ;
- aucune route ne fixe `visibility` ni `publicationState` d'un module : les fixtures les posent
  directement en base (quelques lignes par test, pas de jeu de données massif) ;
- le code d'erreur d'une fiche absente ou masquée est `MODULE_NOT_FOUND` (réutilisé de BE-042) ;
  la comparaison « même corps » ignore `request_id`, propre à chaque requête.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.modules_registry.models import Module, ModuleVersion

URL_LISTE = "/api/v1/catalog/modules"
URL_FICHE = "/api/v1/catalog/modules/{slug}"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


async def _inserer_module(
    code: str,
    *,
    publication: str,
    visibilite: str,
    versions: list[tuple[str, str]] = (),
) -> uuid.UUID:
    """Insère un module et ses versions `(numéro, état)` directement en base."""
    async with AsyncSessionLocal() as db:
        module = Module(
            code=code,
            name=f"Module {code}",
            description=f"Description {code}",
            publicationState=publication,
            visibility=visibilite,
        )
        db.add(module)
        await db.flush()
        for numero, etat in versions:
            db.add(
                ModuleVersion(
                    moduleId=module.id,
                    version=numero,
                    digest=f"sha256:{numero}",
                    provenance="origine-test",
                    licence="proprietary",
                    publicationState=etat,
                    publishedAt=datetime.now(timezone.utc) if etat == "published" else None,
                )
            )
        await db.commit()
        return module.id


def _code_unique(prefixe: str) -> str:
    return f"{prefixe}-be043-{uuid.uuid4().hex[:10]}"


def _erreur(res) -> dict:
    """Partie `error` d'une réponse d'erreur (sans `request_id`, propre à chaque requête)."""
    return res.json()["error"]


async def test_liste_anonyme_ne_renvoie_que_published_et_visible(client: AsyncClient):
    """CA-1 : sur un jeu mixte, un visiteur anonyme ne voit que les modules published ET visible."""
    attendu = _code_unique("ok")
    await _inserer_module(attendu, publication="published", visibilite="visible", versions=[("1.0.0", "published")])
    masque_publie = _code_unique("masque")
    await _inserer_module(masque_publie, publication="published", visibilite="hidden")
    visible_brouillon = _code_unique("brouillon")
    await _inserer_module(visible_brouillon, publication="draft", visibilite="visible")
    restreint_publie = _code_unique("restreint")
    await _inserer_module(restreint_publie, publication="published", visibilite="restricted")
    visible_retire = _code_unique("retire")
    await _inserer_module(visible_retire, publication="withdrawn", visibilite="visible")

    res = await client.get(URL_LISTE, params={"limit": 200})

    assert res.status_code == 200, res.text
    codes_renvoyes = {module["code"] for module in res.json()["data"]}
    nos_modules = {attendu, masque_publie, visible_brouillon, restreint_publie, visible_retire}
    assert codes_renvoyes & nos_modules == {attendu}


async def test_fiche_visible_et_publiee_renvoie_200_sans_authentification(client: AsyncClient):
    """Cas nominal : la fiche d'un module published et visible est lisible sans jeton."""
    slug = _code_unique("fiche")
    await _inserer_module(slug, publication="published", visibilite="visible", versions=[("1.0.0", "published")])

    res = await client.get(URL_FICHE.format(slug=slug))

    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["code"] == slug
    assert corps["name"] == f"Module {slug}"


async def test_fiche_masquee_et_inconnue_renvoient_404_identique(client: AsyncClient):
    """CA-2 : une fiche `hidden` renvoie le même statut et le même corps d'erreur qu'une fiche inexistante."""
    masque = _code_unique("masque")
    await _inserer_module(masque, publication="published", visibilite="hidden")

    res_masque = await client.get(URL_FICHE.format(slug=masque))
    res_inconnu = await client.get(URL_FICHE.format(slug=_code_unique("inexistant")))

    assert res_masque.status_code == 404, res_masque.text
    assert res_inconnu.status_code == 404, res_inconnu.text
    assert _erreur(res_masque)["code"] == "MODULE_NOT_FOUND"
    assert _erreur(res_masque) == _erreur(res_inconnu)


async def test_fiche_visible_mais_non_publiee_renvoie_404(client: AsyncClient):
    """La fiche suit la même règle que la liste : un module visible mais en `draft` reste introuvable."""
    slug = _code_unique("brouillon")
    await _inserer_module(slug, publication="draft", visibilite="visible")

    res = await client.get(URL_FICHE.format(slug=slug))

    assert res.status_code == 404, res.text
    assert _erreur(res)["code"] == "MODULE_NOT_FOUND"


async def test_fiche_restreinte_renvoie_403_audience_restreinte(client: AsyncClient):
    """CA-3 : un visiteur sans audience reçoit 403 `MODULE_AUDIENCE_RESTRICTED` (règle d'audience NON DÉFINIE, QE-MOD-12).

    Ne pas remplacer par un 404 : la règle de la définition est un refus explicite, pas une absence.
    """
    slug = _code_unique("restreint")
    await _inserer_module(slug, publication="published", visibilite="restricted", versions=[("1.0.0", "published")])

    res = await client.get(URL_FICHE.format(slug=slug))

    assert res.status_code == 403, res.text
    assert _erreur(res)["code"] == "MODULE_AUDIENCE_RESTRICTED"


async def test_fiche_n_expose_aucune_version_non_publiee(client: AsyncClient):
    """CA-4 : la fiche d'un module visible ne contient aucune version draft ni review (test de non-fuite)."""
    slug = _code_unique("versions")
    await _inserer_module(
        slug,
        publication="published",
        visibilite="visible",
        versions=[("1.0.0", "published"), ("1.1.0", "draft"), ("1.2.0", "review")],
    )

    res = await client.get(URL_FICHE.format(slug=slug))

    assert res.status_code == 200, res.text
    numeros = [version["version"] for version in res.json()["versions"]]
    assert numeros == ["1.0.0"]
    corps_brut = res.text
    assert "1.1.0" not in corps_brut
    assert "1.2.0" not in corps_brut
