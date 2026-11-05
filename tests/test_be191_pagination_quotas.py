"""BE-191 : pagination par curseur, quotas et bornes de `limit`.

Tests écrits d'après la définition `### BE-191` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Périmètre : socle API, sans route propre. Les paramètres `cursor` et `limit`
sont testés par leurs fonctions publiques (`PaginationCurseur`,
`paginate_curseur`, `ControleQuota`, `exiger_quota`), montées sur une
application FastAPI minimale : la réponse HTTP (statut, code, en-têtes) suit
le gestionnaire d'erreurs commun de app/core/errors.py.

Couverture :
- CA-1 : une liste renvoie un curseur opaque et un ordre déterministe ;
- CA-2 : un curseur d'un tenant présenté par un autre tenant renvoie 404 ;
- CA-3 : dépassement de quota = 429 avec `retryAfter` et `retryable` à vrai ;
- CA-4 : quotas produit et limites techniques configurés séparément ;
- CA-5 : `limit` hors bornes (défaut 20, maximum 100) renvoie 400.
"""

import uuid

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.audit.service import record_audit_event
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError, register_exception_handlers
from app.identity.models import User
from app.shared.pagination import PaginationCurseur, paginate_curseur
from app.shared.quotas import ControleQuota, PolitiqueQuota, exiger_quota, politique_produit, politique_technique


class ResumeEntree(BaseModel):
    """Schéma de sortie minimal pour les lignes de `audit_event`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


COLONNES_TRI = (AuditEvent.createdAt, AuditEvent.id)


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one().id


async def _inserer_entrees(organization_id: uuid.UUID, actor_user_id: uuid.UUID, nombre: int) -> None:
    """Écrit des entrées d'audit réelles de l'organisation (table audit_event)."""
    for index in range(nombre):
        async with AsyncSessionLocal() as db:
            await record_audit_event(
                db,
                organization_id,
                actor_user_id,
                action="test.be191.entree",
                entity_type="TestBe191",
                entity_id=None,
                summary=f"entrée {index}",
                changes=None,
            )
            await db.commit()


async def _parcourir(stmt, tenant_id: uuid.UUID, limit: int) -> list[uuid.UUID]:
    """Lit toutes les pages par curseur et renvoie les identifiants dans l'ordre."""
    vus: list[uuid.UUID] = []
    curseur = None
    async with AsyncSessionLocal() as db:
        while True:
            page = await paginate_curseur(
                db, stmt, PaginationCurseur(limit=limit, cursor=curseur), ResumeEntree, tenant_id, COLONNES_TRI
            )
            vus.extend(entree.id for entree in page.data)
            curseur = page.meta.next_cursor
            if curseur is None:
                return vus


# --- CA-1 : curseur opaque et ordre déterministe -----------------------------


async def test_ca1_liste_par_curseur_ordre_deterministe_et_curseur_opaque(organization, registered_user):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    await _inserer_entrees(organisation, acteur, 5)

    stmt = select(AuditEvent).where(AuditEvent.organizationId == organisation)

    async with AsyncSessionLocal() as db:
        attendu = [
            entree.id
            for entree in (await db.execute(stmt.order_by(AuditEvent.createdAt, AuditEvent.id))).scalars().all()
        ]
        premiere = await paginate_curseur(db, stmt, PaginationCurseur(limit=2, cursor=None), ResumeEntree, organisation, COLONNES_TRI)

    assert len(attendu) >= 5
    assert len(premiere.data) == 2
    curseur = premiere.meta.next_cursor
    assert isinstance(curseur, str) and curseur
    # Opaque : le curseur ne révèle ni l'identifiant du tenant ni celui d'une ligne en clair.
    assert str(organisation) not in curseur
    assert str(premiere.data[-1].id) not in curseur

    # Ordre déterministe : deux parcours complets donnent la même suite, égale à l'ordre SQL.
    premier_parcours = await _parcourir(stmt, organisation, limit=2)
    second_parcours = await _parcourir(stmt, organisation, limit=2)
    assert premier_parcours == attendu
    assert second_parcours == attendu
    assert len(set(premier_parcours)) == len(premier_parcours)

    # Un curseur altéré est refusé (signature), pas ignoré.
    remplacement = "A" if curseur[-1] != "A" else "B"
    curseur_altere = curseur[:-1] + remplacement
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await paginate_curseur(db, stmt, PaginationCurseur(limit=2, cursor=curseur_altere), ResumeEntree, organisation, COLONNES_TRI)
    assert erreur.value.status_code == 400


# --- CA-2 : isolation par tenant ---------------------------------------------


async def test_ca2_curseur_d_un_autre_tenant_renvoie_404(organization, registered_user):
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = uuid.uuid4()
    acteur = await _id_utilisateur(registered_user["email"])
    await _inserer_entrees(tenant_a, acteur, 3)
    stmt = select(AuditEvent).where(AuditEvent.organizationId == tenant_a)

    async with AsyncSessionLocal() as db:
        page_a = await paginate_curseur(db, stmt, PaginationCurseur(limit=1, cursor=None), ResumeEntree, tenant_a, COLONNES_TRI)
        curseur_a = page_a.meta.next_cursor
        assert curseur_a is not None

        with pytest.raises(AppError) as erreur:
            await paginate_curseur(db, stmt, PaginationCurseur(limit=1, cursor=curseur_a), ResumeEntree, tenant_b, COLONNES_TRI)

    assert erreur.value.status_code == 404
    assert erreur.value.code


# --- CA-3 : dépassement de quota -> 429 avec retryAfter ----------------------


def _app_quota(controle: ControleQuota) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/quota", dependencies=[Depends(exiger_quota(controle, lambda requete: requete.headers.get("x-tenant", "")))])
    async def route() -> dict:
        return {"ok": True}

    return app


async def test_ca3_depassement_de_quota_renvoie_429_avec_retry_after_et_retryable():
    horloge = {"t": 1000.0}
    controle = ControleQuota(
        PolitiqueQuota(nom="test-be191", categorie="produit", max_requetes=2, fenetre_secondes=60),
        horloge=lambda: horloge["t"],
    )
    async with AsyncClient(transport=ASGITransport(app=_app_quota(controle)), base_url="http://test") as client:
        entete = {"x-tenant": "tenant-a"}
        assert (await client.get("/quota", headers=entete)).status_code == 200
        assert (await client.get("/quota", headers=entete)).status_code == 200

        # 15 secondes plus tard, la fenêtre de 60 secondes a encore 45 secondes à courir.
        horloge["t"] += 15
        reponse = await client.get("/quota", headers=entete)

    assert reponse.status_code == 429
    erreur = reponse.json()["error"]
    assert erreur["code"] == "quota_depasse"
    assert erreur["details"][0]["retryAfter"] == 45
    assert erreur["details"][0]["retryable"] is True
    assert reponse.headers["Retry-After"] == "45"


async def test_ca3_quota_par_cle_un_autre_tenant_n_est_pas_bloque():
    controle = ControleQuota(
        PolitiqueQuota(nom="test-be191", categorie="produit", max_requetes=1, fenetre_secondes=60),
        horloge=lambda: 1000.0,
    )
    async with AsyncClient(transport=ASGITransport(app=_app_quota(controle)), base_url="http://test") as client:
        assert (await client.get("/quota", headers={"x-tenant": "a"})).status_code == 200
        assert (await client.get("/quota", headers={"x-tenant": "a"})).status_code == 429
        assert (await client.get("/quota", headers={"x-tenant": "b"})).status_code == 200


# --- CA-4 : quotas produit et limites techniques séparées --------------------


def test_ca4_quotas_produit_et_limites_techniques_configurees_separement(monkeypatch):
    monkeypatch.setattr(settings, "QUOTA_PRODUIT_MAX_REQUETES", 3)
    monkeypatch.setattr(settings, "QUOTA_PRODUIT_FENETRE_SECONDES", 60)
    monkeypatch.setattr(settings, "LIMITE_TECHNIQUE_MAX_REQUETES", 100)
    monkeypatch.setattr(settings, "LIMITE_TECHNIQUE_FENETRE_SECONDES", 10)

    produit = politique_produit()
    technique = politique_technique()
    assert (produit.categorie, produit.max_requetes, produit.fenetre_secondes) == ("produit", 3, 60)
    assert (technique.categorie, technique.max_requetes, technique.fenetre_secondes) == ("technique", 100, 10)

    # Seconde configuration : changer le quota produit ne change pas la limite technique.
    monkeypatch.setattr(settings, "QUOTA_PRODUIT_MAX_REQUETES", 500)
    assert politique_produit().max_requetes == 500
    assert politique_technique().max_requetes == 100


def test_ca4_epuisement_d_une_limite_technique_ne_touche_pas_le_quota_produit():
    technique = ControleQuota(
        PolitiqueQuota(nom="technique", categorie="technique", max_requetes=1, fenetre_secondes=60),
        horloge=lambda: 1000.0,
    )
    produit = ControleQuota(
        PolitiqueQuota(nom="produit", categorie="produit", max_requetes=5, fenetre_secondes=60),
        horloge=lambda: 1000.0,
    )
    technique.verifier("cle")
    with pytest.raises(AppError) as erreur:
        technique.verifier("cle")
    assert erreur.value.status_code == 429

    # Le compteur produit est indépendant : il accepte encore des requêtes.
    for _ in range(5):
        produit.verifier("cle")
    with pytest.raises(AppError):
        produit.verifier("cle")


# --- CA-5 : bornes de limit ---------------------------------------------------


def _app_pagination() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/pagination")
    async def route(params: PaginationCurseur = Depends()) -> dict:
        return {"limit": params.limit}

    return app


async def test_ca5_limit_par_defaut_20_et_bornes_1_a_100():
    async with AsyncClient(transport=ASGITransport(app=_app_pagination()), base_url="http://test") as client:
        assert (await client.get("/pagination")).json() == {"limit": 20}
        assert (await client.get("/pagination?limit=1")).status_code == 200
        assert (await client.get("/pagination?limit=100")).json() == {"limit": 100}


async def test_ca5_limit_superieur_au_maximum_renvoie_400():
    async with AsyncClient(transport=ASGITransport(app=_app_pagination()), base_url="http://test") as client:
        reponse = await client.get("/pagination?limit=101")
        assert reponse.status_code == 400
        assert reponse.json()["error"]["code"]
        assert (await client.get("/pagination?limit=0")).status_code == 400
