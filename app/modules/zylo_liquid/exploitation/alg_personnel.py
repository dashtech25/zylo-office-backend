"""Règles pures de la hiérarchie du personnel (niveaux, libellés de poste). Aucune lecture de base."""




STAFF_HIERARCHY_LEVELS: dict[str, int] = {
    "owner": 1,
    "zylo_liquid_station_admin": 2,
    "zylo_liquid_shift_manager": 3,
    "zylo_liquid_team_lead": 4,
    "zylo_liquid_pump_attendant": 5,
}



STAFF_POSITION_LABELS: dict[str, str] = {
    "owner": "Direction",
    "zylo_liquid_station_admin": "Gérant",
    "zylo_liquid_shift_manager": "Responsable de tour",
    "zylo_liquid_team_lead": "Chef d'équipe",
    "zylo_liquid_pump_attendant": "Pompiste",
}



# Niveau supposé d'un acteur qui a le droit de gérer le personnel sans porter
# aucun rôle de la hiérarchie (rôle personnalisé) : traité comme un gérant,
# jamais comme la direction.
STAFF_DEFAULT_ACTOR_LEVEL = 2



STAFF_MANAGER_ROLE_CODE = "zylo_liquid_station_admin"



def staff_hierarchy_level(role_code: str | None) -> int | None:
    return STAFF_HIERARCHY_LEVELS.get(role_code) if role_code else None



def staff_position_label(role_code: str | None, role_name: str | None) -> str | None:
    """Correspondance fixe code -> libellé ; sinon le nom en base."""
    if role_code in STAFF_POSITION_LABELS:
        return STAFF_POSITION_LABELS[role_code]
    return role_name



def staff_can_manage_level(actor_level: int, target_level: int | None) -> bool:
    """On ne peut attribuer/gérer qu'un poste de niveau STRICTEMENT inférieur
    (nombre strictement supérieur) au sien ; hors hiérarchie = autorisé."""
    return target_level is None or target_level > actor_level
