"""BE-241 : supervision, alertes et routage vers le propriétaire.

Intention : prouver par des tests que
- chaque signal d'exploitation attendu possède un propriétaire et un runbook dans
  la configuration livrée et dans la table `alert_routes` (CA-1) ;
- une alerte sans propriétaire, ou sans route, fait échouer le contrôle (CA-2) ;
- un signal de sauvegarde en échec, d'intégrité ou de sécurité est routé vers son
  propriétaire, et un signal non configuré n'est jamais ignoré en silence (CA-3) ;
- aucun score de santé par tenant n'est calculé : l'inventaire des métriques ne
  contient que des métriques de plateforme, et la table de routage n'a pas de
  colonne de tenant (CA-4).

Les imports sont faits à l'intérieur de chaque test : chaque test échoue donc pour
sa seule raison tant que le code n'existe pas, sans faire échouer la collecte.
La base de test est celle de tests/conftest.py (zylo_t<NNN>_test).
"""

import pytest

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError


@pytest.fixture
async def pool_de_boucle_courante():
    """Repart d'un pool neuf lié à la boucle d'événements du test (engine singleton)."""
    await engine.dispose()
    yield


def _route_valide(**surcharges) -> dict:
    route = {
        "signal": "sauvegarde.echec",
        "owner": "exploitation-plateforme",
        "severity": "high",
        "runbook": "docs/exploitation/alertes.md#sauvegarde.echec",
        "escalation": "niveau 2 de l'exploitation ; délai NON DÉFINI (QE-EXP-11)",
    }
    route.update(surcharges)
    return route


def test_chaque_signal_d_exploitation_a_une_route_provisoire_complete():
    """CA-1 (configuration livrée) : chaque signal attendu a une route avec propriétaire et runbook."""
    from app.operator.alertes_registre import ROUTES_PROVISOIRES, SIGNAUX_EXPLOITATION
    from app.operator.alertes_service import valider_route

    assert SIGNAUX_EXPLOITATION, "le catalogue de signaux ne doit pas être vide"
    assert set(ROUTES_PROVISOIRES) == set(SIGNAUX_EXPLOITATION)
    for signal, route in ROUTES_PROVISOIRES.items():
        assert route["signal"] == signal
        assert valider_route(route) == [], signal
        assert route["owner"].strip(), signal
        assert route["runbook"].strip(), signal


async def test_controle_de_la_table_passe_apres_configuration(pool_de_boucle_courante):
    """CA-1 (base) : une fois la configuration appliquée, le contrôle de la table ne relève aucune anomalie."""
    from app.operator.alertes_service import appliquer_routes_provisoires, controler_routage

    async with AsyncSessionLocal() as db:
        await appliquer_routes_provisoires(db)
        await db.commit()
        anomalies = await controler_routage(db)
    assert anomalies == []


def test_alerte_sans_proprietaire_fait_echouer_le_controle():
    """CA-2 : propriétaire vide, absent ou blanc : le contrôle le signale."""
    from app.operator.alertes_service import valider_route

    assert "owner" in valider_route(_route_valide(owner=""))
    assert "owner" in valider_route(_route_valide(owner="   "))
    assert "owner" in valider_route(_route_valide(owner=None))
    assert valider_route(_route_valide()) == []


def test_alerte_sans_runbook_fait_echouer_le_controle():
    """CA-1 (contrôle unitaire) : un runbook vide est une anomalie, comme un propriétaire vide."""
    from app.operator.alertes_service import valider_route

    assert "runbook" in valider_route(_route_valide(runbook=""))


async def test_signal_sans_route_en_base_fait_echouer_le_controle(pool_de_boucle_courante):
    """CA-2 (base) : un signal attendu sans ligne dans `alert_routes` est une anomalie nommée."""
    from sqlalchemy import delete

    from app.operator.alertes_models import AlertRoute
    from app.operator.alertes_registre import SIGNAUX_EXPLOITATION
    from app.operator.alertes_service import appliquer_routes_provisoires, controler_routage

    signal_retire = SIGNAUX_EXPLOITATION[0]
    async with AsyncSessionLocal() as db:
        await appliquer_routes_provisoires(db)
        await db.execute(delete(AlertRoute).where(AlertRoute.signal == signal_retire))
        await db.commit()
        anomalies = await controler_routage(db)
        await appliquer_routes_provisoires(db)
        await db.commit()

    assert any(signal_retire in anomalie for anomalie in anomalies), anomalies


async def test_signaux_de_sauvegarde_integrite_et_securite_sont_routes(pool_de_boucle_courante):
    """CA-3 : sauvegarde en échec, intégrité et sécurité sont routés vers propriétaire et runbook."""
    from app.operator.alertes_service import acheminer, appliquer_routes_provisoires

    async with AsyncSessionLocal() as db:
        await appliquer_routes_provisoires(db)
        await db.commit()
        for signal in ("sauvegarde.echec", "integrite.echec", "securite.incident"):
            route = await acheminer(db, signal)
            assert route["signal"] == signal
            assert route["owner"].strip(), signal
            assert route["runbook"].strip(), signal


async def test_signal_non_configure_n_est_jamais_ignore_en_silence(pool_de_boucle_courante):
    """CA-3 : un signal sans route lève une erreur explicite, jamais un abandon silencieux."""
    from app.operator.alertes_service import acheminer, appliquer_routes_provisoires

    async with AsyncSessionLocal() as db:
        await appliquer_routes_provisoires(db)
        await db.commit()
        with pytest.raises(AppError) as erreur:
            await acheminer(db, "signal.inexistant")
    assert erreur.value.code == "alert_unrouted"


def test_inventaire_des_metriques_ne_contient_aucun_score_par_tenant():
    """CA-4 : aucune métrique de santé par tenant ; toutes les métriques sont de portée plateforme."""
    from app.operator.alertes_registre import METRIQUES_SUPERVISEES
    from app.operator.alertes_service import anomalies_metriques

    assert METRIQUES_SUPERVISEES, "l'inventaire des métriques ne doit pas être vide"
    assert anomalies_metriques(METRIQUES_SUPERVISEES) == []
    for metrique in METRIQUES_SUPERVISEES:
        assert "score" not in metrique["nom"].lower(), metrique["nom"]
        assert metrique["portee"] == "plateforme", metrique["nom"]


def test_metrique_par_tenant_fait_echouer_l_inventaire():
    """CA-4 (contrôle) : une métrique de portée tenant ou un score est signalé."""
    from app.operator.alertes_service import anomalies_metriques

    anomalies = anomalies_metriques([
        {"nom": "sante.tenant.score", "portee": "tenant"},
    ])
    assert anomalies, "un score par tenant doit être signalé"


def test_table_de_routage_n_a_aucune_colonne_de_tenant():
    """CA-4 (schéma) : `alert_routes` est une configuration de plateforme, sans colonne de tenant."""
    from app.operator.alertes_models import AlertRoute

    colonnes = {c.name.lower() for c in AlertRoute.__table__.columns}
    assert not {c for c in colonnes if "tenant" in c or "organization" in c}
    assert AlertRoute.__tablename__ == "alert_routes"
