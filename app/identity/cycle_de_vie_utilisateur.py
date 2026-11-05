"""Cycle de vie de l'utilisateur : états et transitions (BE-187).

Module de domaine `identity`. Un utilisateur global (table `user`, BE-003) porte
son statut dans `user.status`. Ce module est la seule porte d'entrée qui modifie
ce statut après la création : aucune autre route ni service ne doit écrire la
colonne directement. Aucune route publique (BE-187) : l'appel est programmatique.

Décision de structure (QE-API-07, appliquée) : la définition prévoit une table
`user_identity`. La table `user` existe déjà et porte le courriel unique (index
`uq_user_email_lower`) et le condensat du mot de passe ; en créer une seconde
dupliquerait l'identité. Le verrou `version` est donc ajouté à `user`.

États (vocabulaire stocké) :

- `pending`     : compte créé, pas encore activé.
- `active`      : état normal.
- `locked`      : verrouillé. Aucune session ouverte (401 à la connexion, CA-4).
- `deactivated` : désactivé, réactivable.
- `suspended`   : valeur existante (BE-049/creation utilisateurs), conservée telle quelle :
                  connexion refusée en 403 `account_inactive`, non changée ici.
- `deleted`     : état terminal. Les données personnelles sont effacées (CA-5).

Toute transition hors de la table ci-dessous renvoie 422 `user_transition_invalide`,
sans écriture. Une mise à jour concurrente (le statut a changé entre la lecture et
l'écriture) renvoie 409 `user_transition_concurrente`.

La suppression n'efface pas la ligne : elle remplace le courriel par une adresse
inutilisable, le nom par un libellé neutre, vide les champs personnels et remplace
le condensat par une valeur aléatoire jamais communiquée. Ainsi aucune réponse ne
peut plus révéler une donnée personnelle, et la connexion avec l'ancien courriel
échoue (401).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.models import User

STATUT_PENDING = "pending"
STATUT_ACTIVE = "active"
STATUT_LOCKED = "locked"
STATUT_DEACTIVATED = "deactivated"
STATUT_SUSPENDED = "suspended"
STATUT_DELETED = "deleted"

CODE_TRANSITION_INVALIDE = "user_transition_invalide"
CODE_TRANSITION_CONCURRENTE = "user_transition_concurrente"
CODE_UTILISATEUR_INTROUVABLE = "user_not_found"


@dataclass(frozen=True)
class Transition:
    """Une arête de la table d'états : depuis quels statuts, vers lequel, et son libellé."""

    depuis: frozenset[str]
    cible: str
    resume: str


# Table unique des transitions. Ajouter une arête ici suffit à l'accepter.
TRANSITIONS: dict[str, Transition] = {
    "activer": Transition(frozenset({STATUT_PENDING}), STATUT_ACTIVE, "Activation du compte"),
    "verrouiller": Transition(frozenset({STATUT_ACTIVE}), STATUT_LOCKED, "Verrouillage du compte"),
    "deverrouiller": Transition(frozenset({STATUT_LOCKED}), STATUT_ACTIVE, "Déverrouillage du compte"),
    "desactiver": Transition(frozenset({STATUT_ACTIVE, STATUT_LOCKED}), STATUT_DEACTIVATED, "Désactivation du compte"),
    "reactiver": Transition(frozenset({STATUT_DEACTIVATED}), STATUT_ACTIVE, "Réactivation du compte"),
    "suspendre": Transition(frozenset({STATUT_ACTIVE}), STATUT_SUSPENDED, "Suspension du compte"),
    "retablir": Transition(frozenset({STATUT_SUSPENDED}), STATUT_ACTIVE, "Rétablissement du compte"),
    "supprimer": Transition(
        frozenset({STATUT_PENDING, STATUT_ACTIVE, STATUT_LOCKED, STATUT_DEACTIVATED, STATUT_SUSPENDED}),
        STATUT_DELETED,
        "Suppression du compte",
    ),
}


def _valeurs_d_effacement(maintenant: datetime) -> dict:
    """Valeurs qui remplacent les données personnelles lors de la suppression (CA-5).

    Le courriel de remplacement contient l'identifiant de la ligne : il reste unique
    même si plusieurs comptes sont supprimés. Le condensat aléatoire rend la connexion
    impossible sans jamais stocker de secret connu.
    """
    return {
        "email": f"supprime-{secrets.token_hex(8)}@suppression.invalid",
        "hashedPassword": hash_password(secrets.token_urlsafe(48)),
        "fullName": "Utilisateur supprimé",
        "firstName": None,
        "lastName": None,
        "phone": None,
        "photoStorageReference": None,
        "deletedAt": maintenant,
    }


async def transitionner_utilisateur(db: AsyncSession, user_id: uuid.UUID, transition: str) -> User:
    """Applique la transition `transition` (clé de `TRANSITIONS`) à l'utilisateur `user_id`.

    Contrat :
    - `transition` inconnue : erreur de programmation (KeyError), pas une réponse HTTP.
    - Utilisateur absent : 404 `user_not_found`.
    - Statut courant hors de `Transition.depuis` : 422 `user_transition_invalide`,
      aucune écriture.
    - La mise à jour est conditionnée au statut source (`WHERE status IN depuis`) : si
      deux requêtes concurrentes tentent la même transition, une seule réussit et l'autre
      reçoit 409 `user_transition_concurrente`.
    - Chaque transition réussie incrémente `version`.

    Renvoie l'utilisateur relu après commit.
    """
    regle = TRANSITIONS[transition]
    utilisateur = await db.get(User, user_id)
    if utilisateur is None:
        raise AppError(code=CODE_UTILISATEUR_INTROUVABLE, message="Utilisateur introuvable.", status_code=404)
    statut_avant = utilisateur.status
    if statut_avant not in regle.depuis:
        raise AppError(
            code=CODE_TRANSITION_INVALIDE,
            message=f"Transition « {transition} » impossible depuis le statut « {statut_avant} ».",
            status_code=422,
        )

    valeurs: dict = {"status": regle.cible, "version": User.version + 1}
    if regle.cible == STATUT_DELETED:
        valeurs.update(_valeurs_d_effacement(datetime.now(timezone.utc)))

    resultat = await db.execute(
        update(User)
        .where(User.id == user_id, User.status.in_(regle.depuis))
        .values(**valeurs)
        .execution_options(synchronize_session=False)
    )
    if resultat.rowcount != 1:
        # Une autre requête a changé le statut entre la lecture et l'écriture.
        await db.rollback()
        raise AppError(
            code=CODE_TRANSITION_CONCURRENTE,
            message=f"Transition « {transition} » impossible : le statut a changé entre-temps.",
            status_code=409,
        )

    await db.commit()
    await db.refresh(utilisateur)
    return utilisateur
