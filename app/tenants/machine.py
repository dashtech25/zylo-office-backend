"""Graphe des états du tenant (BE-185, CA-1).

Six états : requested, provisioning, active, suspended, closing, closed.
Une transition absente du graphe est refusée (422) par le service ; `closed`
n'a aucune sortie, donc un tenant fermé ne se rouvre jamais.

Ce module ne fait aucune écriture : il dit seulement si un déplacement est
permis. Le service décide ensuite de la version, du droit et de l'audit.
"""

ETATS_TENANT: tuple[str, ...] = (
    "requested",
    "provisioning",
    "active",
    "suspended",
    "closing",
    "closed",
)

TRANSITIONS_AUTORISEES: dict[str, frozenset[str]] = {
    "requested": frozenset({"provisioning"}),
    "provisioning": frozenset({"active"}),
    "active": frozenset({"suspended", "closing"}),
    "suspended": frozenset({"active", "closing"}),
    "closing": frozenset({"closed"}),
    "closed": frozenset(),
}


def transition_autorisee(de: str, vers: str) -> bool:
    """Vrai si le graphe permet de passer de `de` à `vers`. Un état inconnu est refusé."""
    return vers in TRANSITIONS_AUTORISEES.get(de, frozenset())
