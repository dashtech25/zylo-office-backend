"""BE-157 : application, défaut et restauration atomiques d'une valeur de paramètre.

Tests écrits d'après la définition `### BE-157` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : une application crée une nouvelle version, marque la précédente comme non
  appliquée, et journalise `EVT-SET-01` dans la même transaction (BE-153) ;
- CA-2 : si l'écriture d'audit échoue, la version précédente reste active et aucune
  version partielle n'est persistée (injection d'erreur) ;
- CA-3 : restaurer une version antérieure crée une nouvelle version, sans réécrire
  l'ancienne, et journalise l'action ;
- CA-4 (refus) : sans permission d'application, `403` PERMISSION_DENIED et aucune
  version créée ;
- CA-5 : isolation tenant : une restauration sur le tenant A ne modifie aucune ligne
  du tenant B, et une identité de A visant B est refusée en `404` TENANT_MISMATCH ;
- défaut : rétablir le défaut crée une nouvelle version dont la valeur est `defaultValue`.

Hypothèses de test (points NON DÉFINI, à confirmer en QE) :
- qui peut appliquer (QE-PAR-03) : la permission `parametres.setting.apply`, accordée
  dans les tests au rôle propriétaire par un helper local ;
- l'action d'audit `parametre.valeur.appliquer` et la clé `evenement` = `EVT-SET-01`
  dans `changes` (nom de l'action non tranché par la définition) ;
- l'ordre : identité et tenant d'abord (404), puis permission (403).
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.ecriture import IdentiteEmettrice
from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import ErreurCatalogue
from app.identity.models import Organization, User
from app.parametres.application import appliquer_valeur, restaurer_version, retablir_defaut
from app.parametres.models import SettingDefinition, SettingValue
from app.parametres.permissions import PARAMETRE_APPLIQUER
from app.parametres.service import ecrire_version
from app.rbac.models import Role, RolePermission
from app.rbac.service import get_or_create_permission


async def _identite_et_organisation(registered_user: dict, organization: dict) -> tuple[IdentiteEmettrice, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return IdentiteEmettrice(user_id=user.id, organization_id=uuid.UUID(organization["id"])), uuid.UUID(organization["id"])


async def _accorder_application(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Accorde la permission d'application au rôle propriétaire de l'organisation (helper local)."""
    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.organizationId == org_id, Role.code == "owner"))).scalar_one()
        permission = await get_or_create_permission(db, PARAMETRE_APPLIQUER, "parametres", "Appliquer une valeur de paramètre (BE-157).")
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.commit()


async def _creer_organisation(nom: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=nom, slug=f"be157-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _definition(defaut: str = "defaut") -> str:
    cle = f"be157.{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        db.add(
            SettingDefinition(
                key=cle, scopeKind="organisation", owner="test", valueType="texte", defaultValue=defaut, sensitive=False
            )
        )
        await db.commit()
    return cle


async def _version_initiale(cle: str, org_id: uuid.UUID, user_id: uuid.UUID, valeur: str) -> None:
    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, "organisation", org_id, 1, valeur, user_id, "initial", applied=True)


async def _versions(cle: str, org_id: uuid.UUID) -> list[tuple[int, bool, object]]:
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(SettingValue.version, SettingValue.applied, SettingValue.value)
                .where(SettingValue.definitionKey == cle, SettingValue.scopeId == org_id)
                .order_by(SettingValue.version)
            )
        ).all()
    return [tuple(ligne) for ligne in lignes]


async def _audits_pour_version(cle: str, org_id: uuid.UUID) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(AuditEvent).where(AuditEvent.entityType == "setting_value", AuditEvent.organizationId == org_id)
                )
            ).scalars()
        )


async def test_be157_ca1_nouvelle_version_active_et_evenement_journalise(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    await _accorder_application(identite.user_id, org_id)
    cle = await _definition()
    await _version_initiale(cle, org_id, identite.user_id, "v1")

    async with AsyncSessionLocal() as db:
        nouvelle = await appliquer_valeur(
            db, identite, org_id, definition_key=cle, scope_kind="organisation", scope_id=org_id, value="v2", reason="essai"
        )
        nouvelle_id, nouvelle_version = nouvelle.id, nouvelle.version
        await db.commit()

    versions = await _versions(cle, org_id)
    assert versions == [(1, False, "v1"), (2, True, "v2")], "la précédente est désactivée, la nouvelle est appliquée"
    assert nouvelle_version == 2

    audits = await _audits_pour_version(cle, org_id)
    evenements = [a for a in audits if a.entityId == nouvelle_id]
    assert len(evenements) == 1, "une application produit exactement une entrée EVT-SET-01"
    changes = evenements[0].changes
    assert changes["evenement"] == "EVT-SET-01"
    assert changes["cle"] == cle
    assert changes["version"] == 2
    assert changes["portee"] == "organisation"
    assert "diff" in changes, "le diff expurgé est journalisé"


async def test_be157_ca2_echec_audit_garde_la_version_precedente(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    await _accorder_application(identite.user_id, org_id)
    cle = await _definition()
    await _version_initiale(cle, org_id, identite.user_id, "v1")

    injection = AsyncMock(side_effect=SQLAlchemyError("échec d'écriture d'audit injecté"))
    async with AsyncSessionLocal() as db:
        with patch("app.audit.ecriture.record_audit_event", injection):
            with pytest.raises(ErreurCatalogue) as info:
                await appliquer_valeur(
                    db, identite, org_id, definition_key=cle, scope_kind="organisation", scope_id=org_id, value="v2", reason="essai"
                )
            await db.rollback()

    assert info.value.code == "AUDIT_WRITE_FAILED"
    assert await _versions(cle, org_id) == [(1, True, "v1")], "aucune version partielle, la précédente reste active"


async def test_be157_ca3_restauration_cree_une_nouvelle_version(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    await _accorder_application(identite.user_id, org_id)
    cle = await _definition()
    await _version_initiale(cle, org_id, identite.user_id, "v1")
    async with AsyncSessionLocal() as db:
        await appliquer_valeur(
            db, identite, org_id, definition_key=cle, scope_kind="organisation", scope_id=org_id, value="v2", reason="essai"
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        restauree = await restaurer_version(
            db, identite, org_id, definition_key=cle, scope_kind="organisation", scope_id=org_id, version=1, reason="retour"
        )
        restauree_id, restauree_version = restauree.id, restauree.version
        await db.commit()

    versions = await _versions(cle, org_id)
    assert versions == [(1, False, "v1"), (2, False, "v2"), (3, True, "v1")], "pas de réécriture : la version 1 est intacte"
    assert restauree_version == 3
    audits = await _audits_pour_version(cle, org_id)
    assert any(a.entityId == restauree_id and a.action == "parametre.valeur.appliquer" for a in audits), "restauration journalisée"


async def test_be157_ca4_sans_permission_403_et_aucune_version(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    cle = await _definition()
    await _version_initiale(cle, org_id, identite.user_id, "v1")
    # Aucune permission accordée : le propriétaire n'a pas de droit d'application par défaut.

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as info:
            await appliquer_valeur(
                db, identite, org_id, definition_key=cle, scope_kind="organisation", scope_id=org_id, value="v2", reason="refus"
            )
        await db.rollback()

    assert info.value.code == "PERMISSION_DENIED"
    assert info.value.status_code == 403
    assert await _versions(cle, org_id) == [(1, True, "v1")], "un refus n'écrit aucune version"


async def test_be157_ca5_isolation_tenant_restauration(registered_user: dict, organization: dict):
    identite, org_a = await _identite_et_organisation(registered_user, organization)
    await _accorder_application(identite.user_id, org_a)
    org_b = await _creer_organisation("Tenant B BE-157")
    cle = await _definition()
    await _version_initiale(cle, org_a, identite.user_id, "a1")
    await _version_initiale(cle, org_b, identite.user_id, "b1")
    async with AsyncSessionLocal() as db:
        await appliquer_valeur(
            db, identite, org_a, definition_key=cle, scope_kind="organisation", scope_id=org_a, value="a2", reason="essai"
        )
        await db.commit()
    avant_b = await _versions(cle, org_b)

    async with AsyncSessionLocal() as db:
        await restaurer_version(
            db, identite, org_a, definition_key=cle, scope_kind="organisation", scope_id=org_a, version=1, reason="retour"
        )
        await db.commit()

    assert await _versions(cle, org_b) == avant_b, "une restauration sur le tenant A ne touche aucune ligne du tenant B"

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as info:
            await restaurer_version(
                db, identite, org_b, definition_key=cle, scope_kind="organisation", scope_id=org_b, version=1, reason="intrusion"
            )
        await db.rollback()
    assert info.value.code == "TENANT_MISMATCH"
    assert info.value.status_code == 404
    assert await _versions(cle, org_b) == avant_b


async def test_be157_defaut_recree_la_valeur_par_defaut(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    await _accorder_application(identite.user_id, org_id)
    cle = await _definition(defaut="valeur-par-defaut")
    await _version_initiale(cle, org_id, identite.user_id, "v1")

    async with AsyncSessionLocal() as db:
        await retablir_defaut(
            db, identite, org_id, definition_key=cle, scope_kind="organisation", scope_id=org_id, reason="remise a zero"
        )
        await db.commit()

    assert await _versions(cle, org_id) == [(1, False, "v1"), (2, True, "valeur-par-defaut")]
