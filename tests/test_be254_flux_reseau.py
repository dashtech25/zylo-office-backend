"""BE-254 : flux réseau autorisés et isolement des plans.

Intention : prouver par des tests que
- la matrice source-destination-port est complète, versionnée et documentée (CA-1) ;
- un tenant ou une intégration ne peut joindre ni le plan opérateur ni les données
  d'un autre tenant (CA-2) ;
- l'endpoint de métadonnées cloud n'est jamais joignable depuis l'application (CA-3) ;
- toute sortie ou tout flux non listé est refusé (CA-4).

Les tests n'ouvrent aucune connexion réseau : ils évaluent la matrice et les règles
pures de `app/securite/flux_reseau.py`. Les imports sont faits dans chaque test, pour
qu'un test échoue pour sa seule raison tant que le code n'existe pas.
Documentation attendue : `docs/securite/flux.md`.
"""

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DOC_FLUX = BACKEND_ROOT / "docs" / "securite" / "flux.md"


def test_matrice_versionnee_et_reprise_par_la_documentation():
    """CA-1 : la matrice porte une version au format AAAA-MM-JJ.n, et la doc la cite."""
    from app.securite.flux_reseau import VERSION_MATRICE

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", VERSION_MATRICE), VERSION_MATRICE
    assert DOC_FLUX.exists(), "docs/securite/flux.md manquant"
    assert VERSION_MATRICE in DOC_FLUX.read_text(encoding="utf-8")


def test_matrice_complete_chaque_flux_est_decrit_sans_trou():
    """CA-1 : chaque flux a source, destination, port, protocole et motif ; identifiants uniques.

    Toute zone déclarée est soit source/destination d'un flux, soit isolée explicitement.
    """
    from app.securite.flux_reseau import MATRICE_FLUX, ZONES, ZONES_ISOLEES

    assert MATRICE_FLUX, "la matrice ne doit pas être vide"
    identifiants = [flux.identifiant for flux in MATRICE_FLUX]
    assert len(identifiants) == len(set(identifiants)), "identifiants de flux en double"
    for flux in MATRICE_FLUX:
        assert flux.source in ZONES, flux.identifiant
        assert flux.destination in ZONES, flux.identifiant
        assert flux.source != flux.destination, flux.identifiant
        assert 1 <= flux.port <= 65535, flux.identifiant
        assert flux.protocole in {"tcp", "udp"}, flux.identifiant
        assert flux.motif.strip(), flux.identifiant

    zones_utilisees = {flux.source for flux in MATRICE_FLUX} | {
        flux.destination for flux in MATRICE_FLUX
    }
    for zone in ZONES:
        assert zone in zones_utilisees or zone in ZONES_ISOLEES, zone


def test_documentation_liste_chaque_flux_de_la_matrice():
    """CA-1 : chaque identifiant de flux apparaît dans docs/securite/flux.md."""
    from app.securite.flux_reseau import MATRICE_FLUX

    texte = DOC_FLUX.read_text(encoding="utf-8")
    for flux in MATRICE_FLUX:
        assert flux.identifiant in texte, flux.identifiant


def test_plan_operateur_inaccessible_depuis_un_tenant_ou_une_integration():
    """CA-2 : tenant et intégration ne joignent jamais le plan opérateur, même sur un port listé."""
    from app.securite.flux_reseau import evaluer_flux

    for source in ("internet", "entree_publique", "integration_externe"):
        decision = evaluer_flux(source, "plan_operateur", 443)
        assert decision.autorise is False, source
        assert decision.motif == "plan_operateur_inaccessible", source


def test_donnees_d_un_autre_tenant_refusees():
    """CA-2 : un tenant ne joint pas les données d'un autre tenant ; le même tenant est autorisé."""
    from app.securite.flux_reseau import evaluer_flux

    croise = evaluer_flux(
        "application", "donnees_tenant", 5432,
        tenant_source="tenant-a", tenant_cible="tenant-b",
    )
    assert croise.autorise is False
    assert croise.motif == "tenant_croise"

    meme_tenant = evaluer_flux(
        "application", "donnees_tenant", 5432,
        tenant_source="tenant-a", tenant_cible="tenant-a",
    )
    assert meme_tenant.autorise is True


def test_endpoint_de_metadonnees_inaccessible_depuis_l_application():
    """CA-3 : la zone métadonnées, l'adresse IP et le nom d'hôte sont refusés depuis l'application."""
    from app.securite.flux_reseau import evaluer_flux, evaluer_sortie_vers_hote

    par_zone = evaluer_flux("application", "metadonnees_cloud", 80)
    assert par_zone.autorise is False
    assert par_zone.motif == "metadonnees_interdites"

    for hote in ("169.254.169.254", "fd00:ec2::254", "metadata.google.internal"):
        decision = evaluer_sortie_vers_hote(hote, 80)
        assert decision.autorise is False, hote
        assert decision.motif == "metadonnees_interdites", hote


def test_adresses_de_metadonnees_reconnues_sans_faux_positif():
    """CA-3 : les adresses de métadonnées sont reconnues, une adresse publique ne l'est pas."""
    from app.securite.flux_reseau import est_adresse_metadonnees

    assert est_adresse_metadonnees("169.254.169.254") is True
    assert est_adresse_metadonnees("169.254.170.2") is True
    assert est_adresse_metadonnees("fd00:ec2::254") is True
    assert est_adresse_metadonnees("metadata.google.internal") is True
    assert est_adresse_metadonnees("203.0.113.10") is False


def test_flux_non_liste_refuse_par_defaut():
    """CA-4 : une paire de zones présente mais sur un port non listé est refusée."""
    from app.securite.flux_reseau import evaluer_flux

    decision = evaluer_flux("entree_publique", "application", 22)
    assert decision.autorise is False
    assert decision.motif == "flux_non_liste"


def test_sortie_non_listee_refusee():
    """CA-4 : une sortie vers un hôte qui n'est pas dans la liste de sorties contrôlées est refusée."""
    from app.securite.flux_reseau import evaluer_sortie_vers_hote

    decision = evaluer_sortie_vers_hote("203.0.113.10", 443)
    assert decision.autorise is False
    assert decision.motif == "sortie_non_listee"


def test_flux_liste_autorise_avec_son_identifiant():
    """CA-4 (contrepartie) : un flux listé est autorisé et la décision cite son identifiant."""
    from app.securite.flux_reseau import MATRICE_FLUX, evaluer_flux

    flux = MATRICE_FLUX[0]
    decision = evaluer_flux(flux.source, flux.destination, flux.port, flux.protocole)
    assert decision.autorise is True
    assert decision.flux_id == flux.identifiant
