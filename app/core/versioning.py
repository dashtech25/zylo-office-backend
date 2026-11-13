"""Contrôle de version et détection de conflit (BE-233).

Mécanisme retenu : un numéro de version entier, stocké dans la colonne
`version` de chaque agrégat mutable (défaut 1, incrémenté de 1 à chaque
mutation réussie). Le client relit la version courante dans la réponse, puis
la renvoie dans le corps de sa mutation (champ `version`).

Règles :
- Une mutation qui porte une version s'applique seulement si la ligne a encore
  cette version. La vérification et l'écriture sont UNE SEULE instruction SQL
  (`UPDATE ... WHERE id = :id AND version = :version`). Deux mutations
  concurrentes partant de la même version ne peuvent donc pas réussir toutes
  les deux : la seconde attend le verrou de ligne, relit la version déjà
  incrémentée, et ne touche aucune ligne. Un test de contrat en fait foi
  (tests/test_controle_version_be233.py, CA-3).
- Une version obsolète lève `AppError` 409 `version_conflict`, sans écrire.
  `details` contient une entrée `{"versionCourante", "horodatageFraicheur"}`
  pour que le client puisse se recaler (horodatage = `updatedAt` de la ligne,
  en ISO 8601 avec fuseau).
- Sans version (`None`), la mutation n'est pas conditionnée : elle s'applique
  quand même et incrémente la version. Le champ reste facultatif pour ne pas
  casser les clients existants ; chaque route décide si elle l'exige.
- Le droit de la mutation est vérifié AVANT ce module, par la dépendance de
  route `require_permission`. Un refus reste donc un 403, jamais un 409.

Périmètre tenant : le module ne lit que la ligne désignée par l'identifiant
fourni par le service appelant. Ce module ne sait pas filtrer par tenant : le
service doit d'abord valider l'accès à l'agrégat (appartenance, portée), puis
passer son identifiant. Une version n'est donc jamais révélée à un autre
tenant : la réponse 409 ne concerne que la ligne que l'appelant a déjà le droit
de modifier.

Dépendance : `app.core` ne connaît aucun module métier (règle dure 4 de
CLAUDE.md). Le module ne dépend que de SQLAlchemy et de `AppError`.
"""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError

VERSION_INITIALE = 1
"""Version d'un agrégat fraîchement créé (valeur du server_default des colonnes `version`)."""

CODE_CONFLIT_VERSION = "version_conflict"
"""Code métier renvoyé en 409 quand la version fournie n'est plus la version courante."""


def _horodatage_fraicheur(valeur: datetime) -> str:
    """Formate l'horodatage de fraîcheur en ISO 8601. Une valeur naïve est
    refusée : sans fuseau, le client ne peut pas la comparer correctement."""
    if valeur.tzinfo is None:
        raise ValueError("L'horodatage de fraîcheur doit porter un fuseau horaire.")
    return valeur.isoformat()


def lever_conflit_de_version(version_courante: int, horodatage: datetime) -> None:
    """Lève le 409 `version_conflict` avec la version courante dans `details`.

    Le message reste en français et ne contient aucune valeur de ligne : seule
    la version et l'horodatage sont renvoyés."""
    raise AppError(
        code=CODE_CONFLIT_VERSION,
        message="Cette donnée a été modifiée entre-temps. Rechargez-la avant de réessayer.",
        status_code=409,
        details=[
            {
                "versionCourante": version_courante,
                "horodatageFraicheur": _horodatage_fraicheur(horodatage),
            }
        ],
    )


async def mutation_versionnee(
    db: AsyncSession,
    modele: type,
    objet_id,
    version_attendue: int | None,
    valeurs: dict,
    *,
    code_introuvable: str,
) -> None:
    """Applique `valeurs` à la ligne `objet_id` si sa version vaut `version_attendue`.

    - `version_attendue` est `None` : écriture sans condition, version incrémentée.
    - La ligne n'existe pas : `AppError` 404 avec `code_introuvable`.
    - La ligne existe avec une autre version : 409 `version_conflict`, rien n'est écrit.

    La fonction ne fait ni commit ni refresh : l'appelant garde la transaction,
    ajoute par exemple sa trace d'audit dans la même transaction, puis commit et
    recharge l'objet ORM. Le `synchronize_session=False` évite de mettre à jour
    l'objet en session : il est rechargé par l'appelant, pas réécrit ici."""
    requete = update(modele).where(modele.id == objet_id)
    if version_attendue is not None:
        requete = requete.where(modele.version == version_attendue)
    requete = requete.values(**valeurs, version=modele.version + 1).execution_options(
        synchronize_session=False
    )
    resultat = await db.execute(requete)
    if resultat.rowcount == 1:
        return

    # Zéro ligne modifiée : soit la ligne n'existe pas, soit sa version a changé.
    # La relecture ne sert qu'à produire l'erreur, jamais à écrire.
    courante = (
        await db.execute(select(modele.version, modele.updatedAt).where(modele.id == objet_id))
    ).one_or_none()
    if courante is None:
        raise AppError(code=code_introuvable, message="Élément introuvable.", status_code=404)
    version_courante, horodatage = courante
    lever_conflit_de_version(version_courante, horodatage)
