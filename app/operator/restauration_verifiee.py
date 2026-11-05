"""Exercice de restauration vérifiée et ordre de restauration (BE-245).

Une sauvegarde qui n'a jamais été restaurée n'est pas une preuve de reprise. Ce module
restaure une sauvegarde (BE-244) dans une base jetable et vérifie le résultat.

Ordre de restauration (CA-2) : `ORDRE_RESTAURATION` = base, fichiers, secrets, files,
identités. La base vient en premier, car les autres étapes s'y rattachent. L'ordre est fixé
par ce module : l'appelant fournit des fonctions par étape, il ne choisit pas l'ordre.

Étapes : la base est restaurée par `restaurer_sauvegarde` (BE-175). Les quatre autres étapes
sont fournies par l'appelant (`etapes`). Une étape absente fait échouer l'exercice : on ne
déclare jamais « réussie » une restauration dont une partie n'a pas été exécutée.

Invariants vérifiés après restauration :
- `empreinte_intacte` : le fichier de sauvegarde a toujours l'empreinte de `backup_runs` ;
  sinon rien n'est restauré (un fichier altéré ne doit pas entrer dans une base).
- `tables_presentes` : la base restaurée a les mêmes tables `public` que la source.
- `isolement_tenant` (si `tenant_id` est fourni) : pour chaque table qui porte une colonne
  `organizationId`, le nombre de lignes du tenant est identique entre source et restauration.
  Limite : ce n'est pas une restauration sélective par tenant (non implémentée, la base
  entière est restaurée) ; l'invariant prouve seulement qu'aucune ligne du tenant n'a été
  perdue ni ajoutée.

Isolement (CA-1) : la base cible doit être distincte de la base source (422 sinon). Une base
en service recevrait le dump et écraserait ses données.

Droits : l'exercice est réservé au compte d'exploitation (`assert_operator_user`, 403). Ce
contrôle précède toute autre action, y compris la création de la ligne `restore_drills`.

Échec : une erreur pendant une étape ne propage pas d'exception. L'exercice est enregistré en
`echec` avec les étapes déjà exécutées. Le journal ne contient que le type de l'erreur, jamais
le contenu du dump ni un secret.
"""

import datetime as dt
import hashlib
import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import AppError
from app.operator.backup_models import BackupRun
from app.operator.permissions import assert_operator_user
from app.operator.restauration import restaurer_sauvegarde
from app.operator.restore_drill_models import RestoreDrill

logger = logging.getLogger(__name__)

# Ordre imposé par la définition BE-245 (CA-2). Ne pas réordonner sans nouvelle décision.
ORDRE_RESTAURATION: tuple[str, ...] = ("base", "fichiers", "secrets", "files", "identites")


def _url_source():
    """URL de la base en service, lue de `DATABASE_URL` comme le reste du module BE-175."""
    return make_url(os.environ["DATABASE_URL"])


async def _tables_public(moteur) -> set[str]:
    async with moteur.connect() as connexion:
        resultat = await connexion.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        return {ligne[0] for ligne in resultat.all()}


async def _lignes_par_tenant(moteur, tenant_id: uuid.UUID) -> dict[str, int]:
    """Nombre de lignes du tenant dans chaque table `public` qui porte `organizationId`."""
    async with moteur.connect() as connexion:
        colonnes = await connexion.execute(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'organizationId' ORDER BY table_name"
        ))
        comptes: dict[str, int] = {}
        for (table,) in colonnes.all():
            nombre = await connexion.scalar(
                text(f'SELECT count(*) FROM "{table}" WHERE "organizationId" = :org'), {"org": tenant_id}
            )
            comptes[table] = int(nombre)
        return comptes


async def _invariants_tenant(tenant_id: uuid.UUID, base_cible: str) -> bool:
    """Compare, table par table, les lignes du tenant entre la source et la base restaurée."""
    moteur_source = create_async_engine(_url_source(), poolclass=NullPool)
    moteur_cible = create_async_engine(_url_source().set(database=base_cible), poolclass=NullPool)
    try:
        return await _lignes_par_tenant(moteur_source, tenant_id) == await _lignes_par_tenant(moteur_cible, tenant_id)
    finally:
        await moteur_source.dispose()
        await moteur_cible.dispose()


async def _invariants_tables(base_cible: str) -> bool:
    moteur_source = create_async_engine(_url_source(), poolclass=NullPool)
    moteur_cible = create_async_engine(_url_source().set(database=base_cible), poolclass=NullPool)
    try:
        return await _tables_public(moteur_source) == await _tables_public(moteur_cible)
    finally:
        await moteur_source.dispose()
        await moteur_cible.dispose()


async def exercer_restauration(
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    sauvegarde: BackupRun,
    fichier: Path,
    base_cible: str,
    etapes: dict[str, Callable[[], Any]] | None = None,
    tenant_id: uuid.UUID | None = None,
) -> RestoreDrill:
    """Restaure `fichier` dans `base_cible`, vérifie les invariants et enregistre l'exercice.

    Ordre des contrôles : droit d'exploitation (403), isolement de la base cible (422), puis
    empreinte du fichier. Aucun de ces contrôles n'écrit dans la base cible.

    `etapes` associe chaque étape hors base (`fichiers`, `secrets`, `files`, `identites`) à une
    fonction sans argument. La base est toujours restaurée par `restaurer_sauvegarde`.

    Renvoie la ligne `RestoreDrill` ajoutée à la session. L'appelant doit committer.
    """
    assert_operator_user(actor_user_id)
    if base_cible == _url_source().database:
        raise AppError(
            code="RESTAURATION_BASE_SOURCE",
            message="La restauration ne peut pas viser la base en service.",
            status_code=422,
        )

    etapes = etapes or {}
    horodatage = dt.datetime.now(dt.timezone.utc)
    invariants: dict[str, bool] = {}
    durees: list[dict[str, Any]] = []
    etapes_reussies = True

    invariants["empreinte_intacte"] = hashlib.sha256(fichier.read_bytes()).hexdigest() == sauvegarde.empreinte
    if invariants["empreinte_intacte"]:
        for nom in ORDRE_RESTAURATION:
            debut = time.perf_counter()
            try:
                if nom == "base":
                    restaurer_sauvegarde(actor_user_id, fichier, base_cible)
                elif nom in etapes:
                    etapes[nom]()
                else:
                    raise RuntimeError("etape_absente")
            except Exception as erreur:
                # Journal sans contenu : seul le type de l'erreur sort du module.
                logger.error("exercice de restauration, étape %s en échec : %s", nom, type(erreur).__name__)
                etapes_reussies = False
            durees.append({"etape": nom, "duree_ms": int((time.perf_counter() - debut) * 1000)})
            if not etapes_reussies:
                break

        if etapes_reussies:
            invariants["tables_presentes"] = await _invariants_tables(base_cible)
            if tenant_id is not None:
                invariants["isolement_tenant"] = await _invariants_tenant(tenant_id, base_cible)

    reussi = etapes_reussies and invariants.get("empreinte_intacte", False) and all(invariants.values())
    exercice = RestoreDrill(
        horodatage=horodatage,
        sauvegarde_id=sauvegarde.id,
        acteur_user_id=actor_user_id,
        environnement=base_cible,
        invariants=invariants,
        durees=durees,
        resultat="reussie" if reussi else "echec",
    )
    db.add(exercice)
    return exercice
