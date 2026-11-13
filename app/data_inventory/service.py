"""Contrôles et lecture de l'inventaire des données (BE-242).

Trois règles de gouvernance y sont appliquées :

1. Chaque table du schéma migré figure dans le registre (`tables_sans_inventaire`) :
   une table nouvelle sans entrée fait échouer le contrôle de couverture.
2. Chaque champ déclare une classe et un propriétaire (`valider_champ`).
3. Une classe sans durée de rétention décidée vaut NON DÉFINI et bloque la
   suppression automatique (`suppression_automatique_autorisee`). Aucune
   durée n'est codée ici : elle vient de la décision du responsable données.

La lecture du registre (`lire_inventaire`) passe par la permission
`donnees.inventaire.lire` ; sans elle, AppError 403 est levée. Le module
n'expose aucune route HTTP : BE-242 ne déclare aucune route.
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.data_inventory.models import DataInventory
from app.data_inventory.permissions import DONNEES_INVENTAIRE_LIRE
from app.data_inventory.registre import ENTREES_TABLES_PROVISOIRES
from app.rbac.service import user_has_permission

# Référence de la valeur « non décidée » affichée dans l'inventaire.
NON_DEFINI = "NON DÉFINI"

# Registre des tables (re-exporté pour les tests et la documentation).
ENTREES_TABLES = ENTREES_TABLES_PROVISOIRES

# Champs qu'un champ inventorié doit obligatoirement renseigner.
CHAMPS_OBLIGATOIRES = ("classe", "proprietaire")

# Table Alembic : jamais une donnée applicative, donc hors inventaire.
TABLE_ALEMBIC = "alembic_version"


def valider_champ(champ: dict) -> list[str]:
    """Liste les champs obligatoires absents ou vides d'une entrée d'inventaire.

    Une entrée sans `classe` ou sans `proprietaire` ne peut pas être gouvernée :
    l'appelant doit la rejeter (CA-2). La liste renvoyée est vide quand l'entrée
    est conforme. Les autres champs (finalité, lecteurs, rétention...) restent
    facultatifs ici : leur absence se traduit par NON DÉFINI, pas par une erreur.

    Args:
        champ: dictionnaire d'une entrée, clés `classe` et `proprietaire` attendues.

    Returns:
        Les noms des champs obligatoires manquants, dans l'ordre de CHAMPS_OBLIGATOIRES.
    """
    return [cle for cle in CHAMPS_OBLIGATOIRES if not str(champ.get(cle) or "").strip()]


def retention_decidee(retention_jours: int | None) -> bool:
    """Indique si une durée de rétention a été décidée.

    Une durée absente (None) ou non strictement positive n'est pas une décision :
    elle équivaut à NON DÉFINI. Zéro n'est pas admis comme durée, car il effacerait
    la donnée immédiatement sans décision explicite.

    Args:
        retention_jours: durée en jours, ou None si non décidée.

    Returns:
        True seulement si une durée positive est décidée.
    """
    return retention_jours is not None and retention_jours > 0


def suppression_automatique_autorisee(classe: str | None, retention_jours: int | None) -> bool:
    """Indique si la suppression automatique d'une classe est permise.

    Elle exige à la fois une classe renseignée et une rétention décidée. Sans
    l'une ou l'autre, la suppression reste manuelle et tracée (CA-3).

    Args:
        classe: classe de données de l'entrée.
        retention_jours: durée de rétention décidée, ou None (NON DÉFINI).

    Returns:
        True si la suppression automatique est autorisée pour ce couple.
    """
    return bool(classe and str(classe).strip()) and retention_decidee(retention_jours)


async def tables_du_schema(db: AsyncSession) -> set[str]:
    """Liste les tables applicatives réellement présentes dans le schéma public.

    La source est la base migrée, et non les modèles importés : une table créée
    par migration sans modèle reste ainsi couverte par le contrôle (CA-1).

    Args:
        db: session asynchrone sur la base de l'environnement.

    Returns:
        Les noms de tables du schéma `public`, sans la table Alembic.
    """
    resultat = await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    return {nom for nom in resultat.scalars().all() if nom != TABLE_ALEMBIC}


async def tables_sans_inventaire(db: AsyncSession) -> list[str]:
    """Liste les tables du schéma absentes du registre d'inventaire.

    Une liste non vide signifie qu'une table existe sans gouvernance : le contrôle
    de couverture doit alors échouer (CA-1).

    Args:
        db: session asynchrone sur la base de l'environnement.

    Returns:
        Les noms des tables sans entrée, triés.
    """
    return sorted(await tables_du_schema(db) - set(ENTREES_TABLES))


async def lire_inventaire(db: AsyncSession, utilisateur_id: uuid.UUID, organisation_id: uuid.UUID) -> list[DataInventory]:
    """Renvoie les entrées de l'inventaire à un utilisateur qui en a le droit.

    La décision passe par `user_has_permission` (fonction unique du socle) : aucun
    contournement par rôle implicite. Sans la permission `donnees.inventaire.lire`,
    la lecture est refusée en 403 avant toute requête sur le registre (CA-4).

    Args:
        db: session asynchrone sur la base de l'environnement.
        utilisateur_id: identifiant de l'utilisateur demandeur.
        organisation_id: organisation dans laquelle la permission est évaluée.

    Returns:
        Les entrées du registre, triées par objet puis par champ.

    Raises:
        AppError: code `permission_denied`, statut 403, si la permission manque.
    """
    if not await user_has_permission(db, utilisateur_id, organisation_id, DONNEES_INVENTAIRE_LIRE):
        raise AppError(
            code="permission_denied",
            message=f"Permission manquante : {DONNEES_INVENTAIRE_LIRE}.",
            status_code=403,
        )
    resultat = await db.execute(select(DataInventory).order_by(DataInventory.objet, DataInventory.champ))
    return list(resultat.scalars().all())
