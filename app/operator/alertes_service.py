"""Service de routage des signaux d'exploitation vers le propriétaire (BE-241).

Fonctions publiques :
- `valider_route` : contrôle pur d'une route (propriétaire et runbook non vides).
- `controler_routage` : contrôle de la table ; signale tout signal attendu sans
  route valide. Un échec ici doit bloquer la livraison, jamais être contourné.
- `appliquer_routes_provisoires` : upsert de la configuration livrée
  (alertes_registre) dans `alert_routes`.
- `acheminer` : retourne la route d'un signal ; lève `alert_unrouted` si elle
  manque, pour qu'un signal ne soit jamais ignoré en silence.
- `anomalies_metriques` : refuse toute métrique de portée tenant ou dont le nom
  évoque un score (CA-4).

Pas d'import de `app.modules` : routage de plateforme uniquement.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operator.alertes_models import AlertRoute
from app.operator.alertes_registre import ROUTES_PROVISOIRES, SIGNAUX_EXPLOITATION

SEVERITES = ("critical", "high", "medium", "low")


def valider_route(route: dict) -> list[str]:
    """Retourne la liste des anomalies d'une route ; vide si elle est valide.

    Un propriétaire ou un runbook absent, vide ou blanc est une anomalie
    (CA-2), car une alerte sans personne ni procédure n'est pas routée.
    """
    anomalies: list[str] = []
    for champ in ("owner", "runbook"):
        valeur = route.get(champ)
        if not isinstance(valeur, str) or not valeur.strip():
            anomalies.append(champ)
    if route.get("severity") not in SEVERITES:
        anomalies.append("severity")
    return anomalies


async def appliquer_routes_provisoires(db: AsyncSession) -> None:
    """Insère ou met à jour la configuration livrée. L'appelant valide la transaction."""
    existantes = {r.signal: r for r in (await db.scalars(select(AlertRoute))).all()}
    for signal, valeurs in ROUTES_PROVISOIRES.items():
        ligne = existantes.get(signal)
        if ligne is None:
            db.add(AlertRoute(**valeurs))
        else:
            for champ, valeur in valeurs.items():
                setattr(ligne, champ, valeur)


async def controler_routage(db: AsyncSession) -> list[str]:
    """Contrôle la table : chaque signal attendu doit avoir une route valide.

    Retourne des messages d'anomalie nommant le signal concerné.
    """
    routes = {r.signal: r for r in (await db.scalars(select(AlertRoute))).all()}
    anomalies: list[str] = []
    for signal in SIGNAUX_EXPLOITATION:
        route = routes.get(signal)
        if route is None:
            anomalies.append(f"{signal} : aucune route")
            continue
        for champ in valider_route({"owner": route.owner, "severity": route.severity, "runbook": route.runbook}):
            anomalies.append(f"{signal} : {champ} invalide")
    return anomalies


async def acheminer(db: AsyncSession, signal: str) -> dict[str, str | None]:
    """Retourne la route du signal. Lève `alert_unrouted` si elle est absente ou invalide."""
    route = (await db.scalars(select(AlertRoute).where(AlertRoute.signal == signal))).first()
    if route is None or valider_route({"owner": route.owner, "severity": route.severity, "runbook": route.runbook}):
        raise AppError(
            code="alert_unrouted",
            message="Aucune route valide pour ce signal d'exploitation.",
            status_code=500,
        )
    return {
        "signal": route.signal,
        "owner": route.owner,
        "severity": route.severity,
        "runbook": route.runbook,
        "escalation": route.escalation,
    }


def anomalies_metriques(metriques) -> list[str]:
    """Refuse toute métrique de portée tenant ou dont le nom évoque un score (CA-4)."""
    anomalies: list[str] = []
    for metrique in metriques:
        nom = str(metrique.get("nom", ""))
        if metrique.get("portee") != "plateforme":
            anomalies.append(f"{nom} : portée {metrique.get('portee')!r} interdite")
        if "score" in nom.lower():
            anomalies.append(f"{nom} : score interdit")
    return anomalies
