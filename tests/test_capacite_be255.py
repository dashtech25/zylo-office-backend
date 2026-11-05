"""BE-255 : performance, capacité et coûts par tenant.

Tests écrits d'après la définition `### BE-255` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Table : `capacity_samples` (service, tenantId, latence, concurrence, taille, coût attribué).
Les noms de colonnes anglais suivent la convention du dépôt (camelCase, anglais).

Couverture :
- CA-1 (présence) : p50, p95 et p99 sont mesurés par service et par tenant ;
- CA-2 (tenant bruyant) : un tenant bruyant est signalé sans être bloqué ;
- CA-3 (inventaire) : aucun budget ni seuil n'est codé en dur ;
- CA-4 (refus) : lecture sans droit d'exploitation = 403 `operator_access_denied`.

Les imports sont faits à l'intérieur de chaque test : chaque test échoue donc pour
sa seule raison tant que le code n'existe pas, sans faire échouer la collecte.
Aucune fixture massive : les échantillons sont insérés par le service lui-même.
"""

import ast
import pathlib
import uuid

import pytest

from app.core.database import AsyncSessionLocal

MODULE_CAPACITE = pathlib.Path(__file__).resolve().parents[1] / "app" / "operator" / "capacite.py"
MODULE_CAPACITE_MODELS = pathlib.Path(__file__).resolve().parents[1] / "app" / "operator" / "capacite_models.py"


@pytest.fixture
def operateur(monkeypatch):
    """Identifiant d'un compte présent dans l'allowlist d'exploitation (process-level)."""
    identifiant = uuid.uuid4()
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(identifiant))
    return identifiant


async def test_latences_p50_p95_p99_presentes_par_service_et_tenant(operateur):
    """CA-1 : chaque couple (service, tenant) porte p50, p95 et p99 cohérents (p50 <= p95 <= p99)."""
    from app.operator.capacite import enregistrer_mesure, mesurer_latences

    service = f"be255.api.{uuid.uuid4().hex[:8]}"
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        for latence in range(1, 101):
            await enregistrer_mesure(
                db, service=service, tenantId=tenant_a, latencyMs=float(latence),
                concurrency=1, sizeBytes=10, attributedCostCents=1,
            )
        for latence in (5.0, 7.0, 9.0):
            await enregistrer_mesure(
                db, service=service, tenantId=tenant_b, latencyMs=latence,
                concurrency=2, sizeBytes=20, attributedCostCents=2,
            )
        await db.commit()

        lignes = await mesurer_latences(db, acteur_user_id=operateur, service=service)

    par_couple = {(ligne["service"], ligne["tenantId"]): ligne for ligne in lignes}
    for tenant in (tenant_a, tenant_b):
        cle = (service, str(tenant))
        assert cle in par_couple, f"couple absent : {cle}"
        ligne = par_couple[cle]
        for champ in ("p50Ms", "p95Ms", "p99Ms"):
            assert isinstance(ligne[champ], (int, float)), champ
        assert ligne["p50Ms"] <= ligne["p95Ms"] <= ligne["p99Ms"]


def test_percentiles_methode_du_rang_le_plus_proche():
    """CA-1 (calcul) : méthode du rang le plus proche, sur un échantillon connu."""
    from app.operator.capacite import calculer_percentiles

    valeurs = [float(v) for v in range(1, 101)]
    resultat = calculer_percentiles(valeurs)
    assert resultat == {"p50Ms": 50.0, "p95Ms": 95.0, "p99Ms": 99.0}


async def test_tenant_bruyant_signale_sans_etre_bloque(operateur):
    """CA-2 : le tenant bruyant est signalé ; il reste capable d'écrire (aucun blocage)."""
    from app.operator.capacite import enregistrer_mesure, signaler_tenants_bruyants

    service = f"be255.worker.{uuid.uuid4().hex[:8]}"
    bruyant, calme = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        for _ in range(50):
            await enregistrer_mesure(
                db, service=service, tenantId=bruyant, latencyMs=120.0,
                concurrency=40, sizeBytes=5000, attributedCostCents=900,
            )
        await enregistrer_mesure(
            db, service=service, tenantId=calme, latencyMs=20.0,
            concurrency=1, sizeBytes=100, attributedCostCents=10,
        )
        await db.commit()

        signales = await signaler_tenants_bruyants(
            db, acteur_user_id=operateur, seuil_part=0.5, service=service,
        )
        assert str(bruyant) in signales
        assert str(calme) not in signales

        # Le signalement ne bloque pas : une nouvelle mesure du tenant bruyant est acceptée.
        ligne = await enregistrer_mesure(
            db, service=service, tenantId=bruyant, latencyMs=130.0,
            concurrency=41, sizeBytes=5000, attributedCostCents=900,
        )
        await db.commit()
        assert ligne is not None


def test_signalement_tenant_bruyant_sans_seuil_par_defaut():
    """CA-2 / CA-3 : le seuil de part est un paramètre obligatoire, sans valeur par défaut."""
    import inspect

    from app.operator.capacite import signaler_tenants_bruyants

    parametre = inspect.signature(signaler_tenants_bruyants).parameters["seuil_part"]
    assert parametre.default is inspect.Parameter.empty


def test_aucun_budget_ni_seuil_code_en_dur():
    """CA-3 (inventaire) : aucune constante numérique de seuil ou de budget dans le module."""
    mots_interdits = ("seuil", "budget", "threshold", "limite", "limit", "quota", "plafond")
    for chemin in (MODULE_CAPACITE, MODULE_CAPACITE_MODELS):
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        for noeud in arbre.body:
            cibles = []
            if isinstance(noeud, ast.Assign):
                cibles = [c.id for c in noeud.targets if isinstance(c, ast.Name)]
                valeur = noeud.value
            elif isinstance(noeud, ast.AnnAssign) and isinstance(noeud.target, ast.Name):
                cibles = [noeud.target.id]
                valeur = noeud.value
            else:
                continue
            for nom in cibles:
                assert not any(mot in nom.lower() for mot in mots_interdits), f"{chemin.name}:{nom}"
                if valeur is not None:
                    assert not (
                        isinstance(valeur, ast.Constant) and isinstance(valeur.value, (int, float))
                    ) or nom.startswith("p"), f"{chemin.name}:{nom} porte une valeur numérique"
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.FunctionDef | ast.AsyncFunctionDef):
                for argument, defaut in zip(
                    reversed(noeud.args.args), reversed(noeud.args.defaults), strict=False
                ):
                    if any(mot in argument.arg.lower() for mot in mots_interdits):
                        assert not isinstance(defaut, ast.Constant), f"{chemin.name}:{argument.arg}"


def test_table_capacity_samples_colonnes_attendues():
    """Schéma : la table porte service, tenant, latence, concurrence, taille et coût attribué."""
    from app.operator import capacite_models  # noqa: F401  (enregistre la table dans Base.metadata)
    from app.core.database import Base

    table = Base.metadata.tables["capacity_samples"]
    colonnes = set(table.columns.keys())
    assert {"service", "tenantId", "latencyMs", "concurrency", "sizeBytes", "attributedCostCents"} <= colonnes


async def test_lecture_sans_droit_d_exploitation_refusee(monkeypatch):
    """CA-4 : un compte hors allowlist reçoit 403 `operator_access_denied`."""
    from app.core.errors import AppError
    from app.operator.capacite import mesurer_latences

    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await mesurer_latences(db, acteur_user_id=uuid.uuid4())
    assert erreur.value.status_code == 403
    assert erreur.value.code == "operator_access_denied"
