"""Registre provisoire des signaux d'exploitation et de leurs routes (BE-241).

Source de configuration livrée : `appliquer_routes_provisoires` (alertes_service)
recopie ces valeurs dans la table `alert_routes`. Elles sont PROVISOIRES : le
propriétaire est l'équipe d'exploitation générique, faute d'équipe nominative
décidée, et la couverture horaire reste NON DÉFINI (QE-EXP-11). Aucune valeur de
sévérité ou de délai n'est inventée au-delà de ce qui est listé ici.

Chaque runbook pointe vers une ancre de `docs/exploitation/alertes.md`, qui décrit
la première action à mener pour le signal.

Les métriques de supervision sont toutes de portée plateforme : aucun score de
santé par tenant n'est calculé (CA-4 de BE-241).
"""

PROPRIETAIRE_EXPLOITATION = "exploitation-plateforme"
ESCALADE_PROVISOIRE = "niveau 2 de l'exploitation ; délai NON DÉFINI (QE-EXP-11)"

SIGNAUX_EXPLOITATION: tuple[str, ...] = (
    "sauvegarde.echec",
    "integrite.echec",
    "securite.incident",
    "supervision.composant_indisponible",
)
"""Signaux d'exploitation qui doivent toujours être routés (CA-1, CA-3)."""

ROUTES_PROVISOIRES: dict[str, dict[str, str]] = {
    "sauvegarde.echec": {
        "signal": "sauvegarde.echec",
        "owner": PROPRIETAIRE_EXPLOITATION,
        "severity": "high",
        "runbook": "docs/exploitation/alertes.md#sauvegarde.echec",
        "escalation": ESCALADE_PROVISOIRE,
    },
    "integrite.echec": {
        "signal": "integrite.echec",
        "owner": PROPRIETAIRE_EXPLOITATION,
        "severity": "critical",
        "runbook": "docs/exploitation/alertes.md#integrite.echec",
        "escalation": ESCALADE_PROVISOIRE,
    },
    "securite.incident": {
        "signal": "securite.incident",
        "owner": PROPRIETAIRE_EXPLOITATION,
        "severity": "critical",
        "runbook": "docs/exploitation/alertes.md#securite.incident",
        "escalation": ESCALADE_PROVISOIRE,
    },
    "supervision.composant_indisponible": {
        "signal": "supervision.composant_indisponible",
        "owner": PROPRIETAIRE_EXPLOITATION,
        "severity": "high",
        "runbook": "docs/exploitation/alertes.md#supervision.composant_indisponible",
        "escalation": ESCALADE_PROVISOIRE,
    },
}
"""Une route par signal de SIGNAUX_EXPLOITATION, avec propriétaire et runbook."""

METRIQUES_SUPERVISEES: tuple[dict[str, str], ...] = (
    {"nom": "sante.composant.statut", "portee": "plateforme"},
    {"nom": "sauvegarde.derniere_reussite", "portee": "plateforme"},
    {"nom": "integrite.controle.resultat", "portee": "plateforme"},
)
"""Inventaire des métriques de supervision (CA-4) : toutes de portée plateforme."""
