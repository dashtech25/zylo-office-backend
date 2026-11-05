"""Flux réseau autorisés et isolement des plans (BE-254, SEC-06).

Intention : rendre explicite, versionné et testable ce qui peut communiquer avec quoi.
Une matrice unique liste les flux autorisés (source, destination, port, protocole) ;
tout ce qui n'y figure pas est refusé (refus par défaut, CA-4).

Par-dessus la matrice, trois règles sont évaluées AVANT elle, et ne peuvent pas être
levées par une ligne de matrice :
- le plan opérateur n'est jamais joignable depuis Internet, le point d'entrée public
  ou une intégration externe (CA-2) ;
- les données d'un tenant ne sont jamais joignables par un autre tenant (CA-2) ;
- l'endpoint de métadonnées cloud (169.254.0.0/16, `fd00:ec2::254`, nom
  `metadata.google.internal`) est refusé quelle que soit la source (CA-3). Il
  est exposé aux VM et permet de voler les identifiants du compte cloud.

Ce module ne fait aucune connexion réseau : il décide. Son usage réel (règles de
pare-feu, politique de sortie du conteneur) reste à brancher par l'exploitation ;
la matrice est la source de vérité qu'elles doivent reproduire. La documentation
lisible est dans `docs/securite/flux.md`, qui doit citer `VERSION_MATRICE`.

Décisions non définies (QE-EXP-19 et suivantes, voir la définition BE-254) :
- `SORTIES_AUTORISEES` est vide : aucun fournisseur externe n'est encore listé.
  Toute sortie vers un hôte est donc refusée tant que la liste n'est pas renseignée
  et revue par la sécurité.
- Les segments réseau concrets (VPC, sous-réseaux) ne sont pas décrits ici.
"""

import ipaddress
from dataclasses import dataclass

# Version de la matrice, au format AAAA-MM-JJ.n. Toute modification de MATRICE_FLUX
# ou de SORTIES_AUTORISEES doit l'incrémenter et mettre à jour docs/securite/flux.md.
VERSION_MATRICE = "2026-11-05.1"

# Zones réseau. Une zone est un ensemble de composants de même niveau de confiance.
ZONES = (
    "internet",
    "entree_publique",
    "application",
    "plan_operateur",
    "donnees_tenant",
    "integration_externe",
    "observabilite",
    "metadonnees_cloud",
)

# Zones qui ne reçoivent aucun flux par construction. Une zone n'apparaît dans aucun
# flux seulement si elle est listée ici avec sa raison.
ZONES_ISOLEES = frozenset({"metadonnees_cloud"})

# Zones dont le trafic ne doit jamais atteindre le plan opérateur, même via une
# ligne de matrice (CA-2).
ZONES_NON_CONFIANCE_VERS_PLAN = frozenset({"internet", "entree_publique", "integration_externe"})

# Hôtes de sortie contrôlée. Vide par décision provisoire : rien n'est autorisé
# sans revue de sécurité.
SORTIES_AUTORISEES: frozenset[str] = frozenset()

# Noms d'hôtes réservés aux métadonnées cloud.
HOTES_METADONNEES = frozenset({"metadata.google.internal"})

# Adresses IP des métadonnées : lien local 169.254.0.0/16 (AWS, Azure, GCP) et
# l'adresse IPv6 AWS `fd00:ec2::254`.
RESEAUX_METADONNEES = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)


@dataclass(frozen=True)
class Flux:
    """Une ligne de la matrice : un flux autorisé et son motif.

    Un flux est unidirectionnel. Le port est le port de destination.
    """

    identifiant: str
    source: str
    destination: str
    port: int
    protocole: str
    motif: str


@dataclass(frozen=True)
class DecisionFlux:
    """Résultat d'une évaluation : autorisation, motif de refus ou de passage, flux cité."""

    autorise: bool
    motif: str
    flux_id: str | None = None


MATRICE_FLUX: tuple[Flux, ...] = (
    Flux("F-01", "internet", "entree_publique", 443, "tcp", "HTTPS public vers le point d'entrée"),
    Flux("F-02", "entree_publique", "application", 8000, "tcp", "relais du point d'entrée vers l'application"),
    Flux("F-03", "application", "donnees_tenant", 5432, "tcp", "accès PostgreSQL de l'application"),
    Flux("F-04", "application", "plan_operateur", 8000, "tcp", "console d'exploitation, allowlist opérateur"),
    Flux("F-05", "application", "observabilite", 4318, "tcp", "export OTLP des traces et métriques"),
    Flux("F-06", "integration_externe", "entree_publique", 443, "tcp", "webhooks entrants signés"),
)


def est_adresse_metadonnees(hote: str) -> bool:
    """Vrai si `hote` désigne l'endpoint de métadonnées cloud (CA-3).

    Accepte un nom d'hôte ou une adresse IP. Une adresse qui ne se lit pas comme IP
    et n'est pas un nom réservé est considérée comme NON métadonnée : la décision de
    refus par défaut reste à `evaluer_sortie_vers_hote`.
    """
    nettoye = hote.strip().lower()
    if nettoye in HOTES_METADONNEES:
        return True
    try:
        adresse = ipaddress.ip_address(nettoye)
    except ValueError:
        return False
    return any(adresse in reseau for reseau in RESEAUX_METADONNEES)


def evaluer_flux(
    source: str,
    destination: str,
    port: int,
    protocole: str = "tcp",
    *,
    tenant_source: str | None = None,
    tenant_cible: str | None = None,
) -> DecisionFlux:
    """Décide si la communication zone-à-zone est autorisée.

    Ordre d'évaluation (le premier refus l'emporte) :
    1. zone inconnue -> refus `zone_inconnue` ;
    2. destination métadonnées -> refus `metadonnees_interdites` (CA-3) ;
    3. source non fiable vers plan opérateur -> refus `plan_operateur_inaccessible` (CA-2) ;
    4. tenant source différent du tenant cible sur les données -> refus `tenant_croise`
       (CA-2). Les deux tenants doivent être renseignés pour que la règle s'applique ;
    5. paire (source, destination, port, protocole) présente dans MATRICE_FLUX -> autorisé
       avec l'identifiant du flux ;
    6. sinon -> refus `flux_non_liste` (CA-4, refus par défaut).

    Les règles 2 à 4 passent avant la matrice : aucune ligne de matrice ne peut
    ouvrir un de ces chemins.
    """
    if source not in ZONES or destination not in ZONES:
        return DecisionFlux(False, "zone_inconnue")
    if destination == "metadonnees_cloud":
        return DecisionFlux(False, "metadonnees_interdites")
    if destination == "plan_operateur" and source in ZONES_NON_CONFIANCE_VERS_PLAN:
        return DecisionFlux(False, "plan_operateur_inaccessible")
    if (
        destination == "donnees_tenant"
        and tenant_source is not None
        and tenant_cible is not None
        and tenant_source != tenant_cible
    ):
        return DecisionFlux(False, "tenant_croise")
    for flux in MATRICE_FLUX:
        if (flux.source, flux.destination, flux.port, flux.protocole) == (
            source,
            destination,
            port,
            protocole,
        ):
            return DecisionFlux(True, "flux_listé", flux.identifiant)
    return DecisionFlux(False, "flux_non_liste")


def evaluer_sortie_vers_hote(hote: str, port: int, protocole: str = "tcp") -> DecisionFlux:
    """Décide si l'application peut sortir vers un hôte externe (CA-3, CA-4).

    Les métadonnées sont refusées en premier, puis tout hôte absent de
    `SORTIES_AUTORISEES` est refusé. Le port et le protocole sont fournis pour
    que la décision soit tracée, mais la liste ne les contrôle pas encore
    (QE-EXP-19 : ports par fournisseur à décider).
    """
    if est_adresse_metadonnees(hote):
        return DecisionFlux(False, "metadonnees_interdites")
    if hote.strip().lower() in SORTIES_AUTORISEES:
        return DecisionFlux(True, "sortie_listee")
    return DecisionFlux(False, "sortie_non_listee")
