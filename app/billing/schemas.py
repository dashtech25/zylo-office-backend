import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreatePlanRequest(BaseModel):
    moduleCode: str
    code: str
    name: str
    priceCents: int
    currency: str = "XAF"
    periodDays: int = 30


class PlanResponse(BaseModel):
    id: uuid.UUID
    moduleCode: str
    code: str
    name: str
    priceCents: int
    currency: str
    periodDays: int
    version: int = 1
    amountMinor: int | None = None
    entitlementCodes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CreateSubscriptionRequest(BaseModel):
    planCode: str


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    planId: uuid.UUID
    status: str
    startDate: datetime
    endDate: datetime
    planVersionId: uuid.UUID | None = None
    entitlementCodes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EntitlementResponse(BaseModel):
    """Entitlement d'une organisation, état calculé à la lecture (BE-026).

    Aucun champ fournisseur de paiement : la lecture ne renvoie que les droits
    métier et leur état (`etat`), jamais de référence de transaction ou de secret.
    """

    id: uuid.UUID
    organizationId: uuid.UUID | None = None
    subscriptionId: uuid.UUID
    moduleCode: str
    entitlementCode: str
    offreId: uuid.UUID | None = None
    capaciteId: uuid.UUID | None = None
    quotaLimite: int | None = None
    niveauApplication: str
    sourceAttribution: str
    etat: str

    model_config = {"from_attributes": True}


class OrganizationEntitlementResponse(BaseModel):
    """Entitlement d'une organisation vu par la route BE-045 (noms du contrat de la définition).

    Correspondances avec la table `subscription_entitlement` (BE-024) : `scope` =
    `niveauApplication`, `source` = `sourceAttribution`, `state` = état calculé (`etat`),
    `quotaLimit` = `quotaLimite`, `periodStart`/`periodEnd` = `startsAt`/`endsAt`.
    `quotaUnit` est lue sur la capacité ; nulle si elle n'en porte pas (aucune valeur inventée).
    Aucun champ fournisseur de paiement.
    """

    id: uuid.UUID
    moduleCode: str
    entitlementCode: str
    scope: str
    source: str
    state: str
    quotaLimit: int | None = None
    quotaUnit: str | None = None
    periodStart: datetime
    periodEnd: datetime | None = None
    stateVersion: int


class UsageOrganisationResponse(BaseModel):
    """Réponse de `GET /organizations/{organization_id}/usage` (BE-108).

    Dernier snapshot de l'organisation : date de mesure, granularité, agrégats et limites tels
    que publiés (sans clé imposée, QE-POR-23). Sans snapshot, les quatre champs valent nul ou vide.
    Aucun identifiant d'identité individuelle n'est exposé (CA-2).
    """
    measuredAt: datetime | None
    granularity: str | None
    aggregates: dict
    limits: dict


class EntitlementsOrganisationResponse(BaseModel):
    """Réponse de `GET /organizations/{organization_id}/entitlements` (BE-107).

    Deux groupes distincts, jamais mélangés : `included` regroupe les droits accordés par
    l'offre (`source` = `offre`), `addOns` tous les autres droits (achats additionnels,
    essais, allocations, usage). Chaque ligne a la même forme que `OrganizationEntitlementResponse`.
    """

    included: list[OrganizationEntitlementResponse]
    addOns: list[OrganizationEntitlementResponse]


class CreateInvoiceRequest(BaseModel):
    subscriptionId: uuid.UUID


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    subscriptionId: uuid.UUID
    amountMinor: int | None = None
    currency: str
    status: str
    issuedAt: datetime
    paidAt: datetime | None = None
    # BE-086 : renseignés à la finalisation (NULL sur un brouillon).
    total: int | None = None
    finalizedAt: datetime | None = None

    model_config = {"from_attributes": True}


class PaymentAttemptResponse(BaseModel):
    id: uuid.UUID
    invoiceId: uuid.UUID
    provider: str
    mode: str
    amountMinor: int
    currency: str
    status: str
    checkoutUrl: str | None = None
    requestedAt: datetime

    model_config = {"from_attributes": True}


class PaymentWebhookAck(BaseModel):
    received: bool = True
    duplicate: bool = False


class PaymentProviderStatus(BaseModel):
    provider: str
    mode: str
    configured: bool
    checkoutAvailable: bool
    message: str


class AllocationCreate(BaseModel):
    """Corps de `POST .../entitlements/{entitlementId}/allocations` (BE-046).

    `stateVersion` est la version de l'entitlement lue par le client : une version périmée
    renvoie 409 au lieu d'écraser une écriture concurrente.
    """

    userId: uuid.UUID
    stateVersion: int


class AllocationResponse(BaseModel):
    """Siège d'entitlement, tel que renvoyé après attribution ou révocation (BE-046)."""

    id: uuid.UUID
    entitlementId: uuid.UUID
    organizationId: uuid.UUID
    userId: uuid.UUID
    grantedBy: uuid.UUID
    grantedAt: datetime
    revokedAt: datetime | None = None

    model_config = {"from_attributes": True}


class ConsentCreate(BaseModel):
    """Corps de `POST /billing/consents` (BE-076). `correctionOfId` n'est renseigné que pour une correction."""

    accountId: uuid.UUID
    consentTextVersion: str = Field(min_length=1, max_length=64)
    scope: Literal["payeur", "tenant", "beneficiaire"]
    correctionOfId: uuid.UUID | None = None


class ConsentResponse(BaseModel):
    """Consentement enregistré (BE-076) : version du texte, personne, compte, heure, scope."""

    id: uuid.UUID
    personId: uuid.UUID
    accountId: uuid.UUID
    consentTextVersion: str
    scope: str
    recordedAt: datetime
    correctionOfId: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class DataExportCreate(BaseModel):
    """Corps de `POST /billing/data-exports` (BE-098) : compte payeur et périmètre demandé."""

    accountId: uuid.UUID
    scope: Literal["payeur"] = "payeur"


class DataExportResponse(BaseModel):
    """Demande d'export (BE-098) et son contenu. `fileRef` reste nul tant qu'aucun stockage n'est branché (QE-FAC-25)."""

    id: uuid.UUID
    scope: str
    status: str
    requestedAt: datetime
    fileRef: str | None
    content: dict
