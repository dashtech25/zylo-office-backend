"""BE-156 : résolution d'héritage et de priorité des paramètres.

Tests écrits d'après la définition `### BE-156` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : la valeur résolue suit l'ordre utilisateur > module > organisation >
  plateforme > défaut, vérifié en ajoutant un niveau après l'autre ;
- CA-2 : sans valeur à aucun niveau, le défaut déclaré est renvoyé ; sans défaut,
  la résolution renvoie « absent » ;
- CA-3 : deux niveaux incompatibles sont signalés par une erreur, jamais résolus
  silencieusement ;
- CA-4 : isolation tenant : la résolution pour l'organisation A n'utilise jamais une
  valeur de l'organisation B.

Hypothèses de test (points NON DÉFINI de la définition, à confirmer en QE) :
- l'ordre de priorité est celui recommandé par la définition (QE-PAR-06) ;
- la valeur de `scopeId` pour la portée plateforme est la constante
  `PLATEFORME_SCOPE_ID` et, pour la portée module, l'identifiant du module (point
  ouvert de BE-154) ;
- « incompatible » est pris au sens : deux niveaux renseignés dont les valeurs JSON
  n'ont pas la même nature (texte, nombre, booléen, etc.) ;
- le code d'erreur du conflit est `PARAMETRE_CONFLIT` (409), code provisoire ;
- la valeur « courante » d'un niveau est sa dernière version écrite (comme
  `lire_valeur_courante` de BE-154), la règle d'application étant portée par BE-157.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Organization, User
from app.parametres.models import SettingDefinition
from app.parametres.resolution import PLATEFORME_SCOPE_ID, resoudre_parametre
from app.parametres.service import ecrire_version


async def _utilisateur_id(registered_user: dict) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id


async def _creer_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="BE156", slug=f"be156-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _creer_definition(defaut: object = None) -> str:
    cle = f"be156.{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        db.add(SettingDefinition(
            key=cle, scopeKind="organisation", owner="test", valueType="texte",
            defaultValue=defaut, sensitive=False,
        ))
        await db.commit()
    return cle


async def _ecrire(cle: str, portee: str, scope_id: uuid.UUID, valeur: object, auteur: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, portee, scope_id, 1, valeur, auteur, "test BE-156")


async def _resoudre(cle: str, organisation_id: uuid.UUID, utilisateur_id: uuid.UUID, module_id: uuid.UUID):
    async with AsyncSessionLocal() as db:
        return await resoudre_parametre(
            db, cle, organisation_id=organisation_id, utilisateur_id=utilisateur_id, module_id=module_id
        )


async def test_be156_ca1_priorite_utilisateur_module_organisation_plateforme_defaut(registered_user: dict):
    auteur = await _utilisateur_id(registered_user)
    organisation_id = await _creer_organisation()
    module_id = uuid.uuid4()
    cle = await _creer_definition(defaut="valeur-defaut")

    # Niveau par niveau, du plus bas au plus haut : à chaque ajout, le niveau ajouté
    # doit devenir la valeur résolue, sans que les niveaux inférieurs ne l'emportent.
    attendu = [
        ("plateforme", PLATEFORME_SCOPE_ID, "plateforme", "valeur-plateforme"),
        ("organisation", organisation_id, "organisation", "valeur-organisation"),
        ("module", module_id, "module", "valeur-module"),
        ("utilisateur", auteur, "utilisateur", "valeur-utilisateur"),
    ]
    for portee, scope_id, niveau_attendu, valeur_attendue in attendu:
        await _ecrire(cle, portee, scope_id, valeur_attendue, auteur)
        resultat = await _resoudre(cle, organisation_id, auteur, module_id)
        assert resultat.valeur == valeur_attendue, f"niveau {portee} ajouté, valeur résolue incorrecte"
        assert resultat.niveau == niveau_attendu
        assert resultat.absent is False


async def test_be156_ca2_defaut_declare_renvoye_sans_valeur(registered_user: dict):
    auteur = await _utilisateur_id(registered_user)
    organisation_id = await _creer_organisation()
    cle = await _creer_definition(defaut="valeur-defaut")

    resultat = await _resoudre(cle, organisation_id, auteur, uuid.uuid4())

    assert resultat.valeur == "valeur-defaut"
    assert resultat.niveau == "defaut"
    assert resultat.absent is False


async def test_be156_ca2_sans_defaut_la_resolution_renvoie_absent(registered_user: dict):
    auteur = await _utilisateur_id(registered_user)
    organisation_id = await _creer_organisation()
    cle = await _creer_definition(defaut=None)

    resultat = await _resoudre(cle, organisation_id, auteur, uuid.uuid4())

    assert resultat.absent is True
    assert resultat.valeur is None
    assert resultat.niveau is None


async def test_be156_ca3_niveaux_incompatibles_signales_sans_resolution_silencieuse(registered_user: dict):
    auteur = await _utilisateur_id(registered_user)
    organisation_id = await _creer_organisation()
    module_id = uuid.uuid4()
    cle = await _creer_definition(defaut=None)

    # Niveau utilisateur en texte, niveau organisation en nombre : incompatibles.
    await _ecrire(cle, "organisation", organisation_id, 3, auteur)
    await _ecrire(cle, "utilisateur", auteur, "texte", auteur)

    with pytest.raises(AppError) as erreur:
        await _resoudre(cle, organisation_id, auteur, module_id)

    assert erreur.value.code == "PARAMETRE_CONFLIT"
    assert erreur.value.status_code == 409


async def test_be156_ca4_isolation_tenant_pas_de_valeur_d_une_autre_organisation(registered_user: dict):
    auteur = await _utilisateur_id(registered_user)
    organisation_a = await _creer_organisation()
    organisation_b = await _creer_organisation()
    cle = await _creer_definition(defaut="valeur-defaut")

    await _ecrire(cle, "organisation", organisation_b, "valeur-de-b", auteur)

    resultat_a = await _resoudre(cle, organisation_a, auteur, uuid.uuid4())
    assert resultat_a.valeur == "valeur-defaut", "la valeur de l'organisation B fuit vers l'organisation A"
    assert resultat_a.niveau == "defaut"

    resultat_b = await _resoudre(cle, organisation_b, auteur, uuid.uuid4())
    assert resultat_b.valeur == "valeur-de-b"
    assert resultat_b.niveau == "organisation"
