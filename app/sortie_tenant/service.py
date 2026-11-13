"""Sortie d'un tenant : plan, hold, exécution et attestation (BE-246).

Ordre des contrôles d'une demande de sortie (`demander_sortie`) :
1. Le demandeur porte `donnees.sortie.decider` (sinon 403, refus journalisé, CA-4).
2. L'approbateur est une autre personne (sinon 403) et porte la même permission (sinon 403).
3. Holds : s'il existe un hold actif sur le tenant, rien n'est effacé ; la sortie est dite
   « tenue » et l'attestation le déclare (CA-1).
4. Sans hold : les lignes du tenant sont effacées dans l'ordre de dépendance (enfants avant
   parents), toute la sortie dans une seule transaction. Une dépendance non prise en charge
   fait échouer la transaction (409) : on préfère un refus à un effacement partiel.
5. La demande et l'attestation sont enregistrées, l'exécution est journalisée (CA-3).

Plan de suppression (`plan_de_suppression`) : il est lu dans la base migrée, pas dans les
modèles. Une table est couverte si elle porte une colonne `organizationId` (effacée directement),
ou si elle est enfant d'une telle table par une clé étrangère simple (effacée par le filtre sur
ses parents du tenant ; une table qui référence aussi une table globale, comme `permission`, reste
un enfant du tenant). Les tables de preuve (`TABLES_PROTEGEES`) et la racine `organization` sont
conservées avec leur motif (CONSERVEES_MOTIFS). Les catégories
index, fichiers, caches et logs ne sont pas encore branchées au socle : elles sont différées
avec un motif explicite, jamais passées sous silence (CA-2).

Isolation : toute requête est filtrée par l'organisation demandée ; une attestation n'est lue
que par ses parties (demandeur, approbateur) ou un titulaire de `donnees.sortie.lire` (CA-4).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.rbac.service import user_has_permission
from app.sortie_tenant.models import ETAT_TENUE, ETAT_TERMINEE, LegalHold, TenantExitRequest
from app.sortie_tenant.permissions import SORTIE_TENANT_DECIDER, SORTIE_TENANT_LIRE

ACTION_EXECUTEE = "donnees.sortie.executee"
ACTION_REFUS = "donnees.sortie.refus"

CATEGORIES = ("primaire", "index", "fichiers", "caches", "logs")

# Tables de preuve : une sortie ne les efface jamais, même si elles portent `organizationId`.
# `audit_event` est le journal d'audit réel (app/audit/service.py) : la sortie y écrit sa propre trace.
TABLES_PROTEGEES = frozenset({"audit_event", "export_audit", "tenant_exit_requests", "legal_holds"})

# Racine et preuves conservées, avec leur motif (affichés dans l'attestation).
CONSERVEES_MOTIFS = {
    "organization": "racine du tenant conservée pour rattacher l'attestation",
    "audit_event": "journal d'audit conservé comme preuve de la sortie (QE-EXP-15)",
    "export_audit": "journal des exports conservé comme preuve (QE-EXP-15)",
    "tenant_exit_requests": "preuve de la sortie : demande, approbation et attestation",
    "legal_holds": "preuve des holds posés sur le tenant",
}

# Catégories qui ne disposent pas encore d'un stockage branché au socle : différées, motif écrit.
DIFFERES_PAR_CATEGORIE = {
    "index": {"cible": "index de recherche", "motif": "aucun index de recherche branché au socle ; purge à brancher"},
    "fichiers": {"cible": "objets de stockage", "motif": "lignes en base effacées ; suppression des objets à brancher"},
    "caches": {
        "cible": "cache mémoire de processus (app/shared/simple_cache.py)",
        "motif": "non persistant, vidé au redémarrage ; purge explicite à brancher",
    },
    "logs": {"cible": "journaux applicatifs hors base", "motif": "NON DÉFINI : durée de conservation (QE-EXP-12)"},
}

MOTIF_HOLD = "hold actif sur le tenant : suppression différée"


def _q(identifiant: str) -> str:
    """Met un identifiant SQL entre guillemets (tables camelCase, colonnes `organizationId`)."""
    return '"' + identifiant.replace('"', '""') + '"'


async def _tables_du_tenant(db: AsyncSession) -> list[str]:
    """Tables du schéma public portant une colonne `organizationId`, triées."""
    res = await db.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'organizationId' ORDER BY table_name"
        )
    )
    return list(res.scalars().all())


async def _cles_etrangeres(db: AsyncSession) -> list[dict]:
    """Clés étrangères simples du schéma public : enfant, colonne, parent, colonne du parent."""
    res = await db.execute(
        text(
            """
            SELECT cl.relname AS enfant, ca.attname AS col_enfant,
                   cp.relname AS parent, pa.attname AS col_parent
            FROM pg_constraint co
            JOIN pg_class cl ON cl.oid = co.conrelid
            JOIN pg_class cp ON cp.oid = co.confrelid
            JOIN pg_attribute ca ON ca.attrelid = co.conrelid AND ca.attnum = co.conkey[1]
            JOIN pg_attribute pa ON pa.attrelid = co.confrelid AND pa.attnum = co.confkey[1]
            WHERE co.contype = 'f' AND cardinality(co.conkey) = 1
              AND cl.relnamespace = 'public'::regnamespace
            """
        )
    )
    return [dict(ligne) for ligne in res.mappings().all()]


def _ordre_de_suppression(tables: set[str], fks: list[dict]) -> list[str]:
    """Ordre d'effacement : une table part quand plus aucune table restante ne la référence.

    Un cycle de clés étrangères n'a pas d'ordre valable ; dans ce cas l'ordre alphabétique est
    retenu et la base tranche (la transaction échoue, la sortie est refusée).
    """
    restantes = set(tables)
    ordre: list[str] = []
    while restantes:
        pointees = {
            fk["parent"]
            for fk in fks
            if fk["enfant"] in restantes and fk["parent"] in restantes and fk["enfant"] != fk["parent"]
        }
        candidates = sorted(restantes - pointees) or sorted(restantes)
        choisie = candidates[0]
        ordre.append(choisie)
        restantes.remove(choisie)
    return ordre


def _clause(etape: dict) -> str:
    """Clause WHERE qui sélectionne les lignes d'une étape pour l'organisation passée en `:org`.

    Une étape enfant sélectionne les lignes reliées à au moins une ligne du tenant par l'une de
    ses liaisons (ex. une alerte rattachée à une station ou à un camion du tenant).
    """
    if etape["mode"] == "direct":
        return f'{_q("organizationId")} = :org'
    morceaux = [
        f'{_q(liaison["colonne"])} IN (SELECT {_q(liaison["colonneParent"])} FROM {_q(liaison["parent"])} '
        f'WHERE {_q("organizationId")} = :org)'
        for liaison in etape["liaisons"]
    ]
    return "(" + " OR ".join(morceaux) + ")"


async def plan_de_suppression(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    """Calcule ce que la sortie efface, dans quel ordre, et ce qui est conservé ou différé.

    Args:
        db: session asynchrone sur la base migrée.
        organization_id: tenant à sortir.

    Returns:
        Dictionnaire avec :
        - `ordre` : étapes `{table, mode, colonne, parent, colonneParent}` dans l'ordre d'effacement ;
          `mode` vaut `direct` (colonne `organizationId`) ou `enfant` (clé vers une table du tenant) ;
        - `conservees` : table -> motif, pour la racine et les preuves ;
        - `categories` : catégorie -> liste de `{cible, motif, statut}` couvrant CATEGORIES.
    """
    tenant = await _tables_du_tenant(db)
    fks = await _cles_etrangeres(db)
    directes = {t for t in tenant if t not in TABLES_PROTEGEES}

    etapes = {t: {"table": t, "mode": "direct"} for t in directes}
    # Un enfant est retenu dès qu'une de ses clés pointe vers une table du tenant. Ses autres clés
    # (ex. vers `permission`, table globale) ne le font pas sortir du périmètre.
    liaisons: dict[str, list[dict]] = {}
    for fk in fks:
        enfant = fk["enfant"]
        if enfant in directes or enfant in tenant or enfant in TABLES_PROTEGEES or fk["parent"] not in directes:
            continue
        liaisons.setdefault(enfant, []).append(
            {"colonne": fk["col_enfant"], "parent": fk["parent"], "colonneParent": fk["col_parent"]}
        )
    for enfant, liste in liaisons.items():
        etapes[enfant] = {"table": enfant, "mode": "enfant", "liaisons": liste}

    ordre = [etapes[t] for t in _ordre_de_suppression(set(etapes), fks)]
    categories: dict[str, list[dict]] = {categorie: [] for categorie in CATEGORIES}
    categories["primaire"] = [{"cible": e["table"], "motif": "effacement par le plan", "statut": "efface"} for e in ordre]
    for categorie, entree in DIFFERES_PAR_CATEGORIE.items():
        categories[categorie].append({**entree, "statut": "differe"})
    categories["logs"].extend(
        {"cible": t, "motif": CONSERVEES_MOTIFS[t], "statut": "conserve"} for t in ("audit_event", "export_audit")
    )
    return {
        "ordre": ordre,
        "conservees": {"organization": CONSERVEES_MOTIFS["organization"], **{t: CONSERVEES_MOTIFS[t] for t in TABLES_PROTEGEES}},
        "categories": categories,
    }


async def holds_actifs(db: AsyncSession, organization_id: uuid.UUID) -> list[LegalHold]:
    """Holds posés sur le tenant. Il n'existe pas de levée de hold dans ce lot : tout hold est actif."""
    res = await db.execute(select(LegalHold).where(LegalHold.organizationId == organization_id))
    return list(res.scalars().all())


async def poser_hold(db: AsyncSession, organization_id: uuid.UUID, motif: str, decideur_id: uuid.UUID) -> LegalHold:
    """Pose un hold sur le tenant et le valide immédiatement.

    La définition ne prévoit pas de route de pose : cette fonction est l'interface du domaine.

    Args:
        db: session asynchrone.
        organization_id: tenant à tenir.
        motif: raison juridique du hold.
        decideur_id: personne qui pose le hold.

    Returns:
        Le hold créé.
    """
    hold = LegalHold(organizationId=organization_id, motif=motif, decideur=decideur_id)
    db.add(hold)
    await db.commit()
    return hold


async def _refuser(db: AsyncSession, organization_id: uuid.UUID, utilisateur_id: uuid.UUID, raison: str, permission: str | None) -> None:
    """Journalise le refus (commit avant la levée), puis lève 403 `permission_denied`."""
    await record_audit_event(
        db,
        organization_id,
        utilisateur_id,
        ACTION_REFUS,
        "tenant_exit_request",
        None,
        f"Sortie de tenant refusée : {raison}.",
        {"permission": permission} if permission else None,
        result="refused",
    )
    await db.commit()
    message = f"Permission manquante : {permission}." if permission else f"Sortie refusée : {raison}."
    raise AppError(code="permission_denied", message=message, status_code=403)


async def _verifier_permission(db: AsyncSession, organization_id: uuid.UUID, utilisateur_id: uuid.UUID, permission: str) -> None:
    """Refuse en 403 sans la permission, après journalisation du refus (CA-4)."""
    if await user_has_permission(db, utilisateur_id, organization_id, permission):
        return
    await _refuser(db, organization_id, utilisateur_id, "permission manquante", permission)


def _ligne_efface(etape: dict, lignes: int) -> dict:
    """Ligne de l'attestation : table effacée et nombre de lignes retirées."""
    return {"table": etape["table"], "lignes": lignes}


async def demander_sortie(
    db: AsyncSession,
    organization_id: uuid.UUID,
    demandeur_id: uuid.UUID,
    approbateur_id: uuid.UUID,
    motif: str,
) -> TenantExitRequest:
    """Exécute la sortie d'un tenant, ou la déclare tenue si un hold est actif.

    Voir l'en-tête du module pour l'ordre des contrôles. L'effacement, la demande et l'attestation
    forment une seule transaction : si une étape échoue, rien n'est effacé.

    Args:
        db: session asynchrone.
        organization_id: tenant à sortir.
        demandeur_id: personne qui demande la sortie.
        approbateur_id: seconde personne, distincte, qui approuve.
        motif: raison de la sortie.

    Returns:
        La demande enregistrée, avec son état et son attestation.

    Raises:
        AppError: 403 `permission_denied` si le demandeur ou l'approbateur n'a pas la permission,
            ou si l'approbateur est le demandeur ; 409 `sortie_dependance_bloquante` si une
            dépendance n'est pas prise en charge par le plan (rien n'est effacé).
    """
    await _verifier_permission(db, organization_id, demandeur_id, SORTIE_TENANT_DECIDER)
    if approbateur_id == demandeur_id:
        await _refuser(db, organization_id, demandeur_id, "l'approbateur est le demandeur", None)
    if not await user_has_permission(db, approbateur_id, organization_id, SORTIE_TENANT_DECIDER):
        await _refuser(db, organization_id, approbateur_id, "approbateur sans droit de décision", SORTIE_TENANT_DECIDER)

    maintenant = datetime.now(timezone.utc)
    plan = await plan_de_suppression(db, organization_id)
    holds = await holds_actifs(db, organization_id)
    ids_holds = [str(hold.id) for hold in holds]

    efface: list[dict] = []
    conserve = [{"cible": cible, "motif": motif_cible} for cible, motif_cible in plan["conservees"].items()]
    differe = [
        {"categorie": categorie, **entree}
        for categorie, entrees in plan["categories"].items()
        for entree in entrees
        if entree["statut"] == "differe"
    ]
    etat = ETAT_TENUE if holds else ETAT_TERMINEE
    etapes = [
        {"etape": "permission_demandeur", "resultat": "ok"},
        {"etape": "approbation", "resultat": "ok"},
        {"etape": "holds", "resultat": "tenue" if holds else "aucun"},
    ]

    if holds:
        conserve += [{"cible": etape["table"], "motif": MOTIF_HOLD} for etape in plan["ordre"]]
    else:
        comptes: list[dict] = []
        for etape in plan["ordre"]:
            lignes = await db.execute(
                text(f'SELECT count(*) FROM {_q(etape["table"])} WHERE {_clause(etape)}'), {"org": organization_id}
            )
            comptes.append(_ligne_efface(etape, lignes.scalar_one()))
        try:
            for etape in plan["ordre"]:
                await db.execute(text(f'DELETE FROM {_q(etape["table"])} WHERE {_clause(etape)}'), {"org": organization_id})
            await db.flush()
        except IntegrityError as erreur:
            await db.rollback()
            raise AppError(
                code="sortie_dependance_bloquante",
                message="Sortie impossible : une dépendance du tenant n'est pas prise en charge par le plan. Rien n'a été effacé.",
                status_code=409,
            ) from erreur
        efface = comptes
        etapes.append({"etape": "suppression", "resultat": "ok"})

    attestation = {
        "organizationId": str(organization_id),
        "etat": etat,
        "demandeur": str(demandeur_id),
        "approbateur": str(approbateur_id),
        "motif": motif,
        "decideLe": maintenant.isoformat(),
        "holds": ids_holds,
        "efface": efface,
        "differe": differe,
        "conserve": conserve,
    }
    demande = TenantExitRequest(
        organizationId=organization_id,
        demandeur=demandeur_id,
        approbateur=approbateur_id,
        motif=motif,
        etat=etat,
        holds=ids_holds,
        etapes=etapes,
        attestation=attestation,
        decideLe=maintenant,
    )
    db.add(demande)
    await db.flush()
    await record_audit_event(
        db,
        organization_id,
        demandeur_id,
        ACTION_EXECUTEE,
        "tenant_exit_request",
        demande.id,
        f"Sortie de tenant : état {etat}.",
        {"holds": ids_holds, "approbateur": str(approbateur_id)},
    )
    await db.commit()
    return demande


async def derniere_sortie(db: AsyncSession, organization_id: uuid.UUID) -> TenantExitRequest | None:
    """Dernière demande de sortie du tenant, ou None."""
    res = await db.execute(
        select(TenantExitRequest)
        .where(TenantExitRequest.organizationId == organization_id)
        .order_by(TenantExitRequest.decideLe.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def attestation_de(db: AsyncSession, organization_id: uuid.UUID, utilisateur_id: uuid.UUID) -> dict:
    """Attestation de la dernière sortie, lisible par ses parties ou un titulaire de `donnees.sortie.lire`.

    Un tiers sans permission reçoit 403, qu'une sortie existe ou non (pas de révélation).

    Raises:
        AppError: 403 `permission_denied` ; 404 `exit_not_found` si aucune sortie n'a eu lieu.
    """
    demande = await derniere_sortie(db, organization_id)
    parties = demande is not None and utilisateur_id in (demande.demandeur, demande.approbateur)
    if not parties:
        await _verifier_permission(db, organization_id, utilisateur_id, SORTIE_TENANT_LIRE)
    if demande is None:
        raise AppError(code="exit_not_found", message="Aucune sortie pour ce tenant.", status_code=404)
    return demande.attestation
