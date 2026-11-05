"""BE-163 : webhook entrant, signature, tenant et idempotence.

Tests écrits d'après la définition `### BE-163` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : signature valide et schéma valide -> `202`, une ligne `webhook_recu` ;
- CA-2 : doublon d'`idExterne` pour un même connecteur -> `200` avec `REPLAY_DUPLICATE`,
  pas de seconde ligne ; le même `idExterne` sur un autre connecteur n'est pas un doublon ;
- CA-3 (refus) : signature invalide -> `401` SIGNATURE_INVALID, rien écrit ; schéma invalide
  (signature valide) -> `422` SCHEMA_INVALID ;
- CA-4 : webhook hors fenêtre anti-rejeu -> `REPLAY_DUPLICATE` (`409`, catalogue), rien écrit ;
- CA-5 (isolation tenant) : webhook signé pour le connecteur du tenant A mais adressant le
  tenant B -> `404` TENANT_MISMATCH, rien écrit.

Conventions du test : la signature est recalculée ici, indépendamment du code, à partir de la
spécification `t=<unix>,v1=HMAC-SHA256(secret, "<t>." + corps brut)`. Le coffre est un
`SecretStore` injecté par `dependency_overrides` ; la fenêtre anti-rejeu est fixée par
monkeypatch (QE-PAR-09 : pas de valeur par défaut codée).
"""

import datetime as dt
import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select, text

from app.audit.ecriture import IdentiteEmettrice
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.secrets import SecretStore
from app.identity.models import Organization, User
from app.integrations.registre import creer_connecteur
from app.integrations.secrets import enregistrer_secret

SECRET = "secret-webhook-be163"
FENETRE_SECONDES = 300


@pytest.fixture(autouse=True)
def fenetre_anti_rejeu(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_FENETRE_ANTI_REJEU_SECONDS", FENETRE_SECONDES)


async def _utilisateur_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant BE-163", slug=f"be163-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _connecteur_avec_secret(user_id: uuid.UUID, org_id: uuid.UUID, store: SecretStore) -> uuid.UUID:
    """Crée un connecteur tenant et enregistre son secret de signature dans le coffre de test."""
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)
    async with AsyncSessionLocal() as db:
        connecteur = await creer_connecteur(
            db, identite, portee="tenant", nom="Connecteur webhook BE-163", organization_id=org_id
        )
        await enregistrer_secret(db, store, identite, connecteur.id, SECRET)
        await db.commit()
        return connecteur.id


async def _nombre_lignes(connecteur_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            text('SELECT count(*) FROM webhook_recu WHERE "connecteurId" = :c'), {"c": connecteur_id}
        )
        return resultat.scalar_one()


@pytest.fixture
async def contexte(client, registered_user):
    from app.integrations.webhooks import get_coffre
    from app.main import app

    user_id = await _utilisateur_id(registered_user["email"])
    org_a = await _organisation()
    org_b = await _organisation()
    store = SecretStore()
    connecteur_a = await _connecteur_avec_secret(user_id, org_a, store)
    connecteur_a_bis = await _connecteur_avec_secret(user_id, org_a, store)
    app.dependency_overrides[get_coffre] = lambda: store
    try:
        yield {
            "org_a": org_a,
            "org_b": org_b,
            "connecteur_a": connecteur_a,
            "connecteur_a_bis": connecteur_a_bis,
        }
    finally:
        app.dependency_overrides.pop(get_coffre, None)


def _signature(corps: bytes, horodatage: int, secret: str = SECRET) -> str:
    message = f"{horodatage}.".encode("utf-8") + corps
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _requete(corps_dict: dict, horodatage: int | None = None, secret: str = SECRET):
    """Corps brut, en-tête de signature et horodatage, prêts pour l'appel HTTP."""
    corps = json.dumps(corps_dict, separators=(",", ":")).encode("utf-8")
    t = horodatage if horodatage is not None else int(dt.datetime.now(dt.UTC).timestamp())
    entetes = {
        "Content-Type": "application/json",
        "X-Zylo-Signature": f"t={t},v1={_signature(corps, t, secret)}",
    }
    return corps, entetes


def _url(connecteur_id: uuid.UUID) -> str:
    return f"/api/v1/integrations/webhooks/{connecteur_id}"


def _evenement(id_externe: str) -> dict:
    return {"idExterne": id_externe, "typeEvenement": "commande.creee"}


async def test_ca1_signature_et_schema_valides_renvoient_202_et_creent_une_ligne(client, contexte):
    connecteur = contexte["connecteur_a"]
    corps, entetes = _requete(_evenement("evt-ca1"))
    entetes["X-Organization-Id"] = str(contexte["org_a"])

    res = await client.post(_url(connecteur), content=corps, headers=entetes)

    assert res.status_code == 202, res.text
    assert await _nombre_lignes(connecteur) == 1
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(
                text('SELECT "idExterne", "organizationId" FROM webhook_recu WHERE "connecteurId" = :c'),
                {"c": connecteur},
            )
        ).one()
    assert ligne.idExterne == "evt-ca1"
    assert ligne.organizationId == contexte["org_a"]


async def test_ca2_doublon_idexterne_renvoie_200_replay_sans_seconde_ligne(client, contexte):
    connecteur = contexte["connecteur_a"]
    entetes_org = {"X-Organization-Id": str(contexte["org_a"])}
    corps, entetes = _requete(_evenement("evt-ca2"))
    premiere = await client.post(_url(connecteur), content=corps, headers={**entetes, **entetes_org})
    assert premiere.status_code == 202, premiere.text

    corps, entetes = _requete(_evenement("evt-ca2"))
    seconde = await client.post(_url(connecteur), content=corps, headers={**entetes, **entetes_org})

    assert seconde.status_code == 200, seconde.text
    assert "REPLAY_DUPLICATE" in seconde.text
    assert await _nombre_lignes(connecteur) == 1


async def test_ca2_meme_idexterne_sur_un_autre_connecteur_nest_pas_un_doublon(client, contexte):
    entetes_org = {"X-Organization-Id": str(contexte["org_a"])}
    for connecteur in (contexte["connecteur_a"], contexte["connecteur_a_bis"]):
        corps, entetes = _requete(_evenement("evt-partage"))
        res = await client.post(_url(connecteur), content=corps, headers={**entetes, **entetes_org})
        assert res.status_code == 202, res.text
        assert await _nombre_lignes(connecteur) == 1


async def test_ca3_signature_invalide_renvoie_401_et_necrit_rien(client, contexte):
    connecteur = contexte["connecteur_a"]
    corps, entetes = _requete(_evenement("evt-ca3-sig"), secret="mauvais-secret")
    entetes["X-Organization-Id"] = str(contexte["org_a"])

    res = await client.post(_url(connecteur), content=corps, headers=entetes)

    assert res.status_code == 401, res.text
    assert res.json()["error"]["code"] == "SIGNATURE_INVALID"
    assert await _nombre_lignes(connecteur) == 0


async def test_ca3_schema_invalide_renvoie_422_schema_invalid(client, contexte):
    connecteur = contexte["connecteur_a"]
    corps, entetes = _requete({"typeEvenement": "commande.creee"})
    entetes["X-Organization-Id"] = str(contexte["org_a"])

    res = await client.post(_url(connecteur), content=corps, headers=entetes)

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "SCHEMA_INVALID"
    assert await _nombre_lignes(connecteur) == 0


async def test_ca4_hors_fenetre_anti_rejeu_renvoie_replay_duplicate_et_necrit_rien(client, contexte):
    connecteur = contexte["connecteur_a"]
    ancien = int(dt.datetime.now(dt.UTC).timestamp()) - FENETRE_SECONDES - 60
    corps, entetes = _requete(_evenement("evt-ca4"), horodatage=ancien)
    entetes["X-Organization-Id"] = str(contexte["org_a"])

    res = await client.post(_url(connecteur), content=corps, headers=entetes)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "REPLAY_DUPLICATE"
    assert await _nombre_lignes(connecteur) == 0


async def test_ca5_tenant_mismatch_renvoie_404_et_necrit_rien(client, contexte):
    connecteur_tenant_a = contexte["connecteur_a"]
    corps, entetes = _requete(_evenement("evt-ca5"))
    entetes["X-Organization-Id"] = str(contexte["org_b"])

    res = await client.post(_url(connecteur_tenant_a), content=corps, headers=entetes)

    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "TENANT_MISMATCH"
    assert await _nombre_lignes(connecteur_tenant_a) == 0
