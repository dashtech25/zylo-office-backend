"""Performance, capacité et coûts par tenant (BE-255).

Source des règles : implementation-backend/tasks-exploitation-architecture.md, section BE-255,
et exigences QUA-05 / OPS-08. Documentation de module : docs/exploitation/capacite.md.

Ce module fait trois choses, et seulement celles-là :
1. `enregistrer_mesure` écrit un échantillon (latence, concurrence, taille, coût attribué)
   dans `capacity_samples`, par service et par tenant. Il n'interdit jamais l'écriture :
   un tenant bruyant reste mesuré et continue d'être servi (CA-2).
2. `mesurer_latences` calcule p50, p95 et p99 par couple (service, tenant) (CA-1).
3. `signaler_tenants_bruyants` renvoie les tenants dont la part du coût attribué atteint
   un seuil fourni par l'appelant (CA-2). Le signalement est informatif : aucun blocage.

Règles de conception :
- Aucun seuil, budget ni quota n'est codé ici (CA-3, QE-EXP-13 : seuils NON DÉFINIS).
  Le seuil de part de `signaler_tenants_bruyants` est un paramètre obligatoire, sans défaut.
- Lecture réservée à l'exploitation : chaque fonction de lecture appelle
  `assert_operator_user` avant toute requête ; un compte hors allowlist reçoit 403
  `operator_access_denied` (CA-4). La même règle sert aux services hors routes (BE-230).
- Aucune route HTTP dans cette tâche (définition : « Routes : aucune »).
- Pas de consommation de module métier : ce module ne lit que `capacity_samples`.

Piège évité : une moyenne masque les queues de latence. C'est pourquoi on publie p95 et p99,
et non une seule moyenne.

Méthode des percentiles : rang le plus proche (nearest-rank). Pour n valeurs triées, le
percentile p est la valeur de rang ceil(p * n / 100). Elle est exacte, sans interpolation,
et reproductible d'une base à l'autre.
"""

import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operator.capacite_models import CapacitySample
from app.operator.permissions import assert_operator_user


def calculer_percentiles(valeurs: list[float]) -> dict[str, float | None]:
    """Renvoie p50, p95 et p99 par la méthode du rang le plus proche.

    Liste vide : chaque percentile vaut `None`. Un percentile absent n'est jamais
    présenté comme 0, pour qu'une absence de mesure ne ressemble pas à une latence nulle.
    """
    if not valeurs:
        return {"p50Ms": None, "p95Ms": None, "p99Ms": None}
    triees = sorted(valeurs)
    n = len(triees)

    def rang(p: int) -> float:
        return triees[math.ceil(p * n / 100) - 1]

    return {"p50Ms": rang(50), "p95Ms": rang(95), "p99Ms": rang(99)}


async def enregistrer_mesure(
    db: AsyncSession,
    *,
    service: str,
    tenantId: uuid.UUID,
    latencyMs: float,
    concurrency: int,
    sizeBytes: int,
    attributedCostCents: int,
    measuredAt: datetime | None = None,
) -> CapacitySample:
    """Ajoute un échantillon à la session et le vide en base, sans le valider seul.

    Le commit reste à l'appelant, pour que plusieurs mesures d'une même requête
    soient écrites ensemble. Aucune règle de quota : un tenant bruyant n'est jamais
    refusé ici (CA-2).
    """
    ligne = CapacitySample(
        service=service,
        tenantId=tenantId,
        latencyMs=latencyMs,
        concurrency=concurrency,
        sizeBytes=sizeBytes,
        attributedCostCents=attributedCostCents,
        measuredAt=measuredAt or datetime.now(timezone.utc),
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def _lire_echantillons(db: AsyncSession, service: str | None) -> list[CapacitySample]:
    """Lit les échantillons, filtrés par service si demandé. Appelée après le contrôle de droit."""
    requete = select(CapacitySample)
    if service is not None:
        requete = requete.where(CapacitySample.service == service)
    return list((await db.execute(requete)).scalars().all())


async def mesurer_latences(
    db: AsyncSession,
    *,
    acteur_user_id: uuid.UUID,
    service: str | None = None,
) -> list[dict]:
    """Renvoie p50, p95 et p99 par couple (service, tenant), réservé à l'exploitation (CA-1, CA-4).

    Chaque entrée porte `service`, `tenantId` (chaîne), `p50Ms`, `p95Ms`, `p99Ms` et
    `echantillons` (nombre de mesures du couple). L'agrégation est faite en Python :
    volume modéré, et le contrat reste simple à vérifier. À passer en SQL si le volume croît.
    """
    assert_operator_user(acteur_user_id)
    groupes: dict[tuple[str, str], list[float]] = defaultdict(list)
    for ligne in await _lire_echantillons(db, service):
        groupes[(ligne.service, str(ligne.tenantId))].append(ligne.latencyMs)
    resultat = []
    for (nom_service, tenant), latences in sorted(groupes.items()):
        resultat.append(
            {
                "service": nom_service,
                "tenantId": tenant,
                **calculer_percentiles(latences),
                "echantillons": len(latences),
            }
        )
    return resultat


async def signaler_tenants_bruyants(
    db: AsyncSession,
    *,
    acteur_user_id: uuid.UUID,
    seuil_part: float,
    service: str | None = None,
) -> list[str]:
    """Renvoie les tenants dont la part du coût attribué atteint `seuil_part` (CA-2).

    `seuil_part` est une fraction entre 0 et 1, fournie par l'appelant : elle n'est
    jamais codée ici (CA-3). Le résultat est un signalement d'exploitation. La
    fonction ne modifie rien et ne bloque aucune écriture.
    Si le coût total est nul, aucun tenant n'est signalé (pas de division par zéro).
    """
    assert_operator_user(acteur_user_id)
    cout_par_tenant: dict[str, int] = defaultdict(int)
    for ligne in await _lire_echantillons(db, service):
        cout_par_tenant[str(ligne.tenantId)] += ligne.attributedCostCents
    total = sum(cout_par_tenant.values())
    if total <= 0:
        return []
    return sorted(t for t, cout in cout_par_tenant.items() if cout / total >= seuil_part)
