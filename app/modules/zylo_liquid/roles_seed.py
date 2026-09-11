import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zylo_liquid.permissions import (
    ALERT_ACKNOWLEDGE,
    ALERT_MANAGE,
    ALERT_READ,
    CARRIER_READ,
    CASH_READ,
    COMMERCIAL_ACCOUNT_MANAGE,
    COMMERCIAL_ACCOUNT_READ,
    DECLARATION_LOCK,
    DOCUMENT_CREATE,
    DOCUMENT_DELETE,
    DOCUMENT_MANAGE,
    DOCUMENT_READ,
    DOCUMENT_READ_SENSITIVE,
    EQUIPMENT_MANAGE,
    EQUIPMENT_READ,
    INTERVENTION_ASSIGN,
    INTERVENTION_CLOSE,
    INTERVENTION_CREATE,
    INTERVENTION_READ,
    PRODUCT_SALE_CANCEL,
    PRODUCT_SALE_CREATE,
    PRODUCT_SALE_READ,
    REGULATORY_DECLARATION_MANAGE,
    REGULATORY_DECLARATION_READ,
    REGULATORY_DOCUMENT_ARCHIVE,
    REGULATORY_DOCUMENT_CREATE,
    REGULATORY_DOCUMENT_MANAGE,
    REGULATORY_DOCUMENT_READ,
    RECONCILIATION_READ,
    RECONCILIATION_SETTINGS_MANAGE,
    SELLABLE_PRODUCT_MANAGE,
    SELLABLE_PRODUCT_READ,
    TECHNICIAN_MANAGE,
    TECHNICIAN_READ,
    DELIVERY_DECLARATION_CREATE,
    DELIVERY_DECLARATION_READ,
    DELIVERY_READ,
    FUEL_PRODUCT_READ,
    HOLYKELL_ACCOUNT_READ,
    INCIDENT_DECLARATION_CREATE,
    INCIDENT_DECLARATION_READ,
    LEAK_EVENT_READ,
    LEAK_TEST_DECLARATION_CREATE,
    LEAK_TEST_DECLARATION_READ,
    MANUAL_GAUGING_DECLARATION_CREATE,
    MANUAL_GAUGING_DECLARATION_READ,
    PAYMENT_CREATE,
    PAYMENT_READ,
    PRICE_HISTORY_CREATE,
    PRICE_HISTORY_READ,
    PURCHASE_ORDER_MANAGE,
    PURCHASE_ORDER_READ,
    QUALITY_CHECK_DECLARATION_CREATE,
    QUALITY_CHECK_DECLARATION_READ,
    RECEIVABLE_MANAGE,
    RECEIVABLE_READ,
    SALE_CREATE,
    SALE_READ,
    SHIFT_CASH_DECLARATION_CREATE,
    SHIFT_CASH_DECLARATION_READ,
    STATION_FUEL_PRODUCT_MANAGE,
    STATION_FUEL_PRODUCT_READ,
    STATION_MANAGE,
    STATION_READ,
    SUPPLIER_READ,
    TANK_CALIBRATION_MANAGE,
    TANK_CALIBRATION_READ,
    TANK_MANAGE,
    TANK_READ,
    TANK_SENSOR_MAPPING_MANAGE,
    TANK_SENSOR_MAPPING_READ,
    TRUCK_READ,
    SECURITY_EQUIPMENT_READ,
    SECURITY_EQUIPMENT_MANAGE,
    STATION_SUPPLIER_READ,
    STATION_SUPPLIER_MANAGE,
    STATION_STAFF_READ,
    STATION_STAFF_MANAGE,
    STATION_SERVICE_READ,
    STATION_SERVICE_MANAGE,
    PRICING_POLICY_READ,
    PRICING_POLICY_MANAGE,
)

# Les 6 permissions "create" de la couche déclarative, accordées ensemble au
# pompiste (Phase 4 §1 de processus-double-sources-verite/04-matrice-roles-actions.md :
# "Déclarer" est un comportement de base du pompiste, pour les 6 processus
# retenus en Phase 3 §12) — jamais SALE_CREATE, qui reste hors du périmètre
# de ce rôle (Phase 7 §2/§4 : la qualification commerciale est réservée au
# gérant/caissier).
_DECLARATION_CREATE_PERMISSIONS = [
    DELIVERY_DECLARATION_CREATE,
    SHIFT_CASH_DECLARATION_CREATE,
    MANUAL_GAUGING_DECLARATION_CREATE,
    QUALITY_CHECK_DECLARATION_CREATE,
    LEAK_TEST_DECLARATION_CREATE,
    INCIDENT_DECLARATION_CREATE,
]
_DECLARATION_READ_PERMISSIONS = [
    DELIVERY_DECLARATION_READ,
    SHIFT_CASH_DECLARATION_READ,
    MANUAL_GAUGING_DECLARATION_READ,
    QUALITY_CHECK_DECLARATION_READ,
    LEAK_TEST_DECLARATION_READ,
    INCIDENT_DECLARATION_READ,
]

# Couche Commercial (Phase 7 §2/§4) : jamais SALE_CREATE au pompiste — la
# qualification commerciale reste réservée au gérant/caissier.
_COMMERCIAL_GESTION_PERMISSIONS = [
    COMMERCIAL_ACCOUNT_READ,
    COMMERCIAL_ACCOUNT_MANAGE,
    SALE_READ,
    SALE_CREATE,
    RECEIVABLE_READ,
    RECEIVABLE_MANAGE,
    PAYMENT_READ,
    PAYMENT_CREATE,
]
_COMMERCIAL_SALE_PERMISSIONS = [SALE_READ, SALE_CREATE, PAYMENT_READ, PAYMENT_CREATE]
_DOCUMENT_PERMISSIONS = [DOCUMENT_READ, DOCUMENT_CREATE]

# Mission « vente-maintenant-reglementation » (06-permissions-par-domaine.md
# §2-5 de la mission) — regroupements par domaine, mêmes conventions que
# ci-dessus (jamais une permission qui ne protège concrètement aucune route).
_PRODUCT_SALE_PERMISSIONS = [SELLABLE_PRODUCT_READ, PRODUCT_SALE_READ, PRODUCT_SALE_CREATE]
_MAINTENANCE_READ_PERMISSIONS = [EQUIPMENT_READ, INTERVENTION_READ, TECHNICIAN_READ]
_REGULATORY_READ_PERMISSIONS = [REGULATORY_DOCUMENT_READ, REGULATORY_DECLARATION_READ]
_DOCUMENT_FULL_PERMISSIONS = [DOCUMENT_READ, DOCUMENT_CREATE, DOCUMENT_MANAGE, DOCUMENT_DELETE]

# Couche Approvisionnement (fusion prototype #/livraisons avec la couche
# réelle — décision commanditaire « créer toutes les tables nécessaires,
# même fournisseur ») : lecture des référentiels (fournisseur/transporteur/
# camion) et des commandes pour tout rôle qui lit déjà les livraisons
# déclarées. PURCHASE_ORDER_MANAGE (création/réception d'une commande, scopé
# station comme une déclaration) reste réservé au responsable de station.
# La gestion des référentiels eux-mêmes (SUPPLIER_MANAGE...) n'est accordée
# à aucun rôle par défaut : aucune vue réseau de gestion n'existe encore.
_APPRO_READ_PERMISSIONS = [SUPPLIER_READ, CARRIER_READ, TRUCK_READ, PURCHASE_ORDER_READ]

# Centre administratif et opérationnel de la station — domaines Sécurité
# (SecurityEquipment) et Fournisseurs par station (StationSupplier), tous
# deux scopés station comme Equipment/RegulatoryDocument. STATION_FINANCIAL_*
# volontairement absent de tout rôle par défaut (donnée sensible incl.
# bankAccountInfo — owner-only, même principe que les permissions *_MANAGE
# des référentiels réseau ci-dessus).
_SECURITY_READ_PERMISSIONS = [SECURITY_EQUIPMENT_READ]
_STATION_SUPPLIER_READ_PERMISSIONS = [STATION_SUPPLIER_READ]
_STATION_STAFF_READ_PERMISSIONS = [STATION_STAFF_READ]
_STATION_SERVICE_READ_PERMISSIONS = [STATION_SERVICE_READ]
_PRICING_POLICY_READ_PERMISSIONS = [PRICING_POLICY_READ]

from app.rbac.models import Role, RolePermission
from app.rbac.service import get_or_create_permission

# Transposition directe des rôles par défaut de `formation/role_permission.md`
# §2 sur le catalogue de permissions RÉELLEMENT appliqué aujourd'hui par
# `zylo_liquid/router.py` (voir « rôle et permissions global global et
# spécifique par module Zylo Office.md » §10.1) : le catalogue de
# `role_permission.md` est plus fin (station.create/close/delete distincts,
# etc.) que ce qui est aujourd'hui enforced au niveau des endpoints
# (uniquement STATION_MANAGE, coarse). On ne crée donc jamais une permission
# qui ne protège concrètement aucune route — la granularité fine reste un
# suivi explicite (§20 du document, point 5) une fois les endpoints
# eux-mêmes splittés, jamais une permission "décorative".
DEFAULT_ROLES: list[tuple[str, str, list[str]]] = [
    (
        # Découvert en générant un scénario de démo réel avec des gérants
        # scopés station (mission « vente-maintenant-reglementation ») :
        # certains endpoints de référentiel réseau exigeaient à tort
        # `require_permission()` non scopé (`_scope_covers` : un grant
        # "station" ne couvre jamais une demande org-wide) au lieu d'un
        # filtrage par portée réelle. Les listes concernées (stations,
        # cuves, alertes, livraisons, fuites) ont depuis été corrigées pour
        # filtrer par la portée réelle de l'utilisateur (comme
        # `list_stations` le faisait déjà) — retirées de ce rôle, sous peine
        # d'annuler ce filtrage (un grant org-wide couvre TOUJOURS une
        # demande, même scopée, cf. `_scope_covers`). Ce rôle ne couvre plus
        # que le véritable référentiel partagé (catalogue produits, compte
        # de synchronisation Holykell) — jamais des données par station.
        # Doit être assigné en portée organisation entière en complément
        # d'un rôle scopé station, jamais à sa place.
        "zylo_liquid_network_read",
        "Lecture réseau (référentiel partagé uniquement)",
        [
            FUEL_PRODUCT_READ, STATION_FUEL_PRODUCT_READ,
            TANK_SENSOR_MAPPING_READ, TANK_CALIBRATION_READ, HOLYKELL_ACCOUNT_READ,
            SUPPLIER_READ, CARRIER_READ, TRUCK_READ,
        ],
    ),
    (
        "zylo_liquid_station_admin",
        "Administrateur de station",
        [
            STATION_READ,
            STATION_MANAGE,
            STATION_FUEL_PRODUCT_READ,
            STATION_FUEL_PRODUCT_MANAGE,
            FUEL_PRODUCT_READ,
            TANK_READ,
            TANK_MANAGE,
            TANK_SENSOR_MAPPING_READ,
            TANK_SENSOR_MAPPING_MANAGE,
            TANK_CALIBRATION_READ,
            TANK_CALIBRATION_MANAGE,
            HOLYKELL_ACCOUNT_READ,
            DELIVERY_READ,
            LEAK_EVENT_READ,
            ALERT_READ,
            ALERT_ACKNOWLEDGE,
            ALERT_MANAGE,
            PRICE_HISTORY_READ,
            PRICE_HISTORY_CREATE,
            CASH_READ,
            *_DECLARATION_READ_PERMISSIONS,
            *_DECLARATION_CREATE_PERMISSIONS,
            DECLARATION_LOCK,
            *_COMMERCIAL_GESTION_PERMISSIONS,
            *_DOCUMENT_FULL_PERMISSIONS,
            DOCUMENT_READ_SENSITIVE,
            RECONCILIATION_READ,
            RECONCILIATION_SETTINGS_MANAGE,
            *_APPRO_READ_PERMISSIONS,
            PURCHASE_ORDER_MANAGE,
            # Mission « vente-maintenant-reglementation » — le responsable de
            # station gère l'intégralité des 3 nouveaux domaines sur sa station.
            SELLABLE_PRODUCT_READ,
            SELLABLE_PRODUCT_MANAGE,
            PRODUCT_SALE_READ,
            PRODUCT_SALE_CREATE,
            PRODUCT_SALE_CANCEL,
            EQUIPMENT_READ,
            EQUIPMENT_MANAGE,
            INTERVENTION_READ,
            INTERVENTION_CREATE,
            INTERVENTION_ASSIGN,
            INTERVENTION_CLOSE,
            TECHNICIAN_READ,
            TECHNICIAN_MANAGE,
            REGULATORY_DOCUMENT_READ,
            REGULATORY_DOCUMENT_CREATE,
            REGULATORY_DOCUMENT_MANAGE,
            REGULATORY_DOCUMENT_ARCHIVE,
            REGULATORY_DECLARATION_READ,
            REGULATORY_DECLARATION_MANAGE,
            # Centre administratif et opérationnel de la station — le
            # responsable de station gère l'intégralité de ces 2 domaines
            # sur sa station (même logique que EQUIPMENT_MANAGE ci-dessus).
            SECURITY_EQUIPMENT_READ,
            SECURITY_EQUIPMENT_MANAGE,
            STATION_SUPPLIER_READ,
            STATION_SUPPLIER_MANAGE,
            STATION_STAFF_READ,
            STATION_STAFF_MANAGE,
            STATION_SERVICE_READ,
            STATION_SERVICE_MANAGE,
            PRICING_POLICY_READ,
            PRICING_POLICY_MANAGE,
        ],
    ),
    (
        "zylo_liquid_team_lead",
        "Chef d'équipe",
        [
            STATION_READ,
            TANK_READ,
            ALERT_READ,
            ALERT_ACKNOWLEDGE,
            DELIVERY_READ,
            LEAK_EVENT_READ,
            CASH_READ,
            *_DECLARATION_READ_PERMISSIONS,
            *_APPRO_READ_PERMISSIONS,
            *_MAINTENANCE_READ_PERMISSIONS,
            INTERVENTION_CREATE,
            INTERVENTION_ASSIGN,
            *_REGULATORY_READ_PERMISSIONS,
            *_DOCUMENT_PERMISSIONS,
            *_SECURITY_READ_PERMISSIONS,
            *_STATION_SUPPLIER_READ_PERMISSIONS,
            *_STATION_STAFF_READ_PERMISSIONS,
            *_STATION_SERVICE_READ_PERMISSIONS,
            *_PRICING_POLICY_READ_PERMISSIONS,
        ],
    ),
    (
        "zylo_liquid_cashier",
        "Agent / Caissier",
        [
            STATION_READ,
            TANK_READ,
            ALERT_READ,
            CASH_READ,
            DELIVERY_READ,
            *_DECLARATION_READ_PERMISSIONS,
            *_APPRO_READ_PERMISSIONS,
            *_COMMERCIAL_SALE_PERMISSIONS,
            *_PRODUCT_SALE_PERMISSIONS,
            *_DOCUMENT_PERMISSIONS,
        ],
    ),
    (
        # Aligné strictement sur le prototype validé (prototype.html,
        # ROLES.POMP/MATRICE/PAGES, lignes ~2420-2454 et dashPompiste()
        # ligne ~3644) : le pompiste n'a AUCUNE vue de pilotage (Stations et
        # Cuves/ATG = null dans la matrice — jamais STATION_READ/TANK_READ),
        # ne déclare ni livraison ni jaugeage ni contrôle qualité ni test de
        # fuite ni incident (Livraisons/Stocks = null — ce sont des tâches
        # du Gérant, pas du Pompiste). Seuls Alertes (L) et Shifts/Caisse
        # (déclaration de son propre shift, avec clôture) lui sont ouverts.
        # SALE_CREATE (Ventes = "C" dans le prototype) n'est PAS accordé —
        # décision explicite du commanditaire de garder la restriction déjà
        # en place (la qualification commerciale reste réservée au
        # gérant/caissier, cf. Phase 7 §2/§4 de processus-double-sources-verite).
        "zylo_liquid_pump_attendant",
        "Pompiste",
        # Refonte alertes D6 : ALERT_ACKNOWLEDGE ajouté — premier sur le
        # terrain à constater une fuite ou un niveau bas, il doit pouvoir
        # signaler qu'il s'en occupe sans avoir ALERT_MANAGE (résolution
        # manuelle justifiée, réservée aux rôles de pilotage).
        [ALERT_READ, ALERT_ACKNOWLEDGE, SHIFT_CASH_DECLARATION_READ, SHIFT_CASH_DECLARATION_CREATE, DECLARATION_LOCK],
    ),
    (
        "zylo_liquid_fleet_coordinator",
        "Coordinateur Flotte / Expéditions",
        [DELIVERY_READ, ALERT_READ],
    ),
    (
        # Phase 6 §1.1 de la mission : nouveau rôle nécessaire, aucun rôle
        # existant ne couvre les actions Maintenance (affecter/clôturer une
        # intervention) sans sur-accorder des droits Ventes non pertinents.
        "zylo_liquid_technician",
        "Technicien de maintenance",
        [
            STATION_READ,
            *_MAINTENANCE_READ_PERMISSIONS,
            INTERVENTION_CREATE,
            INTERVENTION_CLOSE,
            *_DOCUMENT_PERMISSIONS,
        ],
    ),
    (
        # Phase 6 §1.1 — reprend directement le profil `dashAuditeur` déjà
        # validé dans le prototype : lecture seule transverse, aucune
        # permission de création/modification.
        "zylo_liquid_auditor",
        "Auditeur",
        [
            STATION_READ,
            TANK_READ,
            ALERT_READ,
            DELIVERY_READ,
            LEAK_EVENT_READ,
            CASH_READ,
            *_DECLARATION_READ_PERMISSIONS,
            *_APPRO_READ_PERMISSIONS,
            SALE_READ,
            RECEIVABLE_READ,
            PAYMENT_READ,
            PRODUCT_SALE_READ,
            *_MAINTENANCE_READ_PERMISSIONS,
            *_REGULATORY_READ_PERMISSIONS,
            RECONCILIATION_READ,
            DOCUMENT_READ,
            DOCUMENT_READ_SENSITIVE,
            *_SECURITY_READ_PERMISSIONS,
            *_STATION_SUPPLIER_READ_PERMISSIONS,
            *_STATION_STAFF_READ_PERMISSIONS,
            *_STATION_SERVICE_READ_PERMISSIONS,
            *_PRICING_POLICY_READ_PERMISSIONS,
        ],
    ),
    (
        # Phase 6 §1.1 — reprend directement le profil `dashHse` du prototype :
        # gestion des documents réglementaires et des incidents, pas d'accès
        # aux ventes.
        "zylo_liquid_hse",
        "HSE (Hygiène, Sécurité, Environnement)",
        [
            STATION_READ,
            ALERT_READ,
            INCIDENT_DECLARATION_READ,
            INCIDENT_DECLARATION_CREATE,
            *_MAINTENANCE_READ_PERMISSIONS,
            REGULATORY_DOCUMENT_READ,
            REGULATORY_DOCUMENT_CREATE,
            REGULATORY_DOCUMENT_MANAGE,
            REGULATORY_DECLARATION_READ,
            REGULATORY_DECLARATION_MANAGE,
            *_DOCUMENT_PERMISSIONS,
            DOCUMENT_READ_SENSITIVE,
            # Centre administratif et opérationnel de la station — le
            # domaine Sécurité (extincteurs, ATEX) relève directement du
            # rôle HSE.
            SECURITY_EQUIPMENT_READ,
            SECURITY_EQUIPMENT_MANAGE,
        ],
    ),
]


async def seed_default_roles(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Appelé une fois à l'activation du module `zylo_liquid` pour une
    organisation (`modules_registry/service.py::activate_module`) — mêmes
    conventions que `grant_module_permissions_to_owner` : idempotent (ne
    recrée jamais un rôle dont le code existe déjà pour cette organisation),
    jamais appliqué au rôle `owner` (déjà créé à part, toutes permissions)."""
    for code, name, permission_codes in DEFAULT_ROLES:
        existing = await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == code))
        if existing.scalar_one_or_none() is not None:
            continue

        role = Role(organizationId=organization_id, code=code, name=name)
        db.add(role)
        await db.flush()

        for perm_code in permission_codes:
            permission = await get_or_create_permission(db, perm_code, "zylo_liquid", perm_code)
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
