"""BE-153 : service d'écriture d'audit fail-closed.

Tests écrits d'après la définition `### BE-153` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : mutation sensible et événement d'audit dans la même transaction ; échec
  d'audit injecté => mutation annulée et `AUDIT_WRITE_FAILED` renvoyé ;
- CA-2 : une lecture non sensible reste tolérante à l'échec d'audit ;
- CA-3 : sans identité authentifiée => 403 `PERMISSION_DENIED`, aucune ligne écrite ;
- CA-4 : `tenantId` différent de celui de l'identité => `TENANT_MISMATCH`, rien écrit.

La mutation de test renomme l'organisation créée par la fixture : une ligne réelle,
dont la valeur avant/après permet de vérifier l'annulation.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.ecriture import IdentiteEmettrice, executer_lecture_non_sensible, executer_mutation_sensible
from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import ErreurCatalogue
from app.identity.models import Organization, User


async def _identite_et_organisation(registered_user: dict, organization: dict) -> tuple[IdentiteEmettrice, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        org_id = uuid.UUID(organization["id"])
    return IdentiteEmettrice(user_id=user.id, organization_id=org_id), org_id


async def _nom_organisation(org_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Organization.name).where(Organization.id == org_id))).scalar_one()


async def _nombre_audits(action: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action))
        ).scalar_one()


def _renommer(org_id: uuid.UUID, nouveau_nom: str):
    async def mutation(db):
        organisation = await db.get(Organization, org_id)
        organisation.name = nouveau_nom
        await db.flush()
        return nouveau_nom

    return mutation


async def test_be153_ca1_mutation_et_audit_dans_la_meme_transaction(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    action = f"test.be153.ca1.{uuid.uuid4().hex[:8]}"
    nouveau_nom = f"Renommée {uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        await executer_mutation_sensible(
            db, identite, org_id, action, "Organization", org_id, "Renommage de l'organisation", _renommer(org_id, nouveau_nom)
        )
        await db.commit()

    assert await _nom_organisation(org_id) == nouveau_nom
    assert await _nombre_audits(action) == 1, "une mutation sensible produit exactement une entrée d'audit"


async def test_be153_ca1_echec_audit_annule_la_mutation(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    action = f"test.be153.ca1.echec.{uuid.uuid4().hex[:8]}"
    nom_avant = await _nom_organisation(org_id)
    nouveau_nom = f"Injection {uuid.uuid4().hex[:8]}"

    injection = AsyncMock(side_effect=SQLAlchemyError("échec d'écriture injecté"))
    async with AsyncSessionLocal() as db:
        with patch("app.audit.ecriture.record_audit_event", injection):
            with pytest.raises(ErreurCatalogue) as info:
                await executer_mutation_sensible(
                    db, identite, org_id, action, "Organization", org_id, "Renommage", _renommer(org_id, nouveau_nom)
                )
            await db.rollback()

    assert info.value.code == "AUDIT_WRITE_FAILED"
    assert info.value.status_code == 500
    assert await _nom_organisation(org_id) == nom_avant, "la mutation doit être annulée si l'audit échoue"
    assert await _nombre_audits(action) == 0


async def test_be153_ca2_lecture_non_sensible_tolerante_a_l_echec_d_audit(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    action = f"test.be153.ca2.{uuid.uuid4().hex[:8]}"
    nom_attendu = await _nom_organisation(org_id)

    async def lecture(db):
        return (await db.execute(select(Organization.name).where(Organization.id == org_id))).scalar_one()

    injection = AsyncMock(side_effect=SQLAlchemyError("échec d'écriture injecté"))
    async with AsyncSessionLocal() as db:
        with patch("app.audit.ecriture.record_audit_event", injection):
            resultat = await executer_lecture_non_sensible(
                db, identite, org_id, action, "Organization", org_id, "Lecture de l'organisation", lecture
            )

    assert resultat == nom_attendu, "une lecture non sensible doit rendre sa valeur même si l'audit échoue"
    assert await _nombre_audits(action) == 0


async def test_be153_ca3_sans_identite_refus_403_sans_ecriture(registered_user: dict, organization: dict):
    _, org_id = await _identite_et_organisation(registered_user, organization)
    action = f"test.be153.ca3.{uuid.uuid4().hex[:8]}"
    nom_avant = await _nom_organisation(org_id)
    mutation = AsyncMock(return_value=None)

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as info:
            await executer_mutation_sensible(db, None, org_id, action, "Organization", org_id, "Renommage", mutation)

    assert info.value.code == "PERMISSION_DENIED"
    assert info.value.status_code == 403
    mutation.assert_not_called()
    assert await _nom_organisation(org_id) == nom_avant
    assert await _nombre_audits(action) == 0


async def test_be153_ca3_lecture_sans_identite_refusee(registered_user: dict, organization: dict):
    _, org_id = await _identite_et_organisation(registered_user, organization)
    action = f"test.be153.ca3.lecture.{uuid.uuid4().hex[:8]}"
    lecture = AsyncMock(return_value="valeur")

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as info:
            await executer_lecture_non_sensible(db, None, org_id, action, "Organization", org_id, "Lecture", lecture)

    assert info.value.code == "PERMISSION_DENIED"
    assert info.value.status_code == 403
    lecture.assert_not_called()
    assert await _nombre_audits(action) == 0


async def test_be153_ca4_tenant_different_refus_tenant_mismatch(registered_user: dict, organization: dict):
    identite, org_id = await _identite_et_organisation(registered_user, organization)
    autre_tenant = uuid.uuid4()
    assert autre_tenant != org_id
    action = f"test.be153.ca4.{uuid.uuid4().hex[:8]}"
    nom_avant = await _nom_organisation(org_id)
    mutation = AsyncMock(return_value=None)

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as info:
            await executer_mutation_sensible(db, identite, autre_tenant, action, "Organization", org_id, "Renommage", mutation)

    assert info.value.code == "TENANT_MISMATCH"
    assert info.value.status_code == 404
    mutation.assert_not_called()
    assert await _nom_organisation(org_id) == nom_avant
    assert await _nombre_audits(action) == 0
