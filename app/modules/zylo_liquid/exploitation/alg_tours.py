"""Règles pures du temps de tour, du planning, du pointage, de la passation et de l'ouverture. Aucune lecture de base."""

from datetime import date, datetime, timedelta


MINUTES_PER_DAY = 1440



def parse_shift_time(value: str) -> int | None:
    """« HH:MM » (00:00–23:59) → minutes depuis minuit ; None si le format est
    invalide (jamais d'exception : le service remonte une erreur de ligne)."""
    if len(value) != 5 or value[2] != ":" or not (value[:2] + value[3:]).isdigit() or not value.isascii():
        return None
    hours, minutes = int(value[:2]), int(value[3:])
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes



def shift_duration_minutes(start_min: int, end_min: int) -> int:
    """fin > début : fin − début ; fin <= début : passe minuit (+24 h) ;
    début = fin : tour de 24 h (1440)."""
    return end_min - start_min if end_min > start_min else end_min - start_min + MINUTES_PER_DAY



def shift_crosses_midnight(start_min: int, end_min: int) -> bool:
    return end_min <= start_min



def shift_segments(start_min: int, end_min: int) -> list[tuple[int, int]]:
    """Intervalles semi-ouverts [début, fin) sur le cycle de 24 h ; un tour qui
    passe minuit est coupé en deux segments."""
    if start_min == end_min:
        return [(0, MINUTES_PER_DAY)]
    if end_min > start_min:
        return [(start_min, end_min)]
    segments = [(start_min, MINUTES_PER_DAY)]
    if end_min > 0:
        segments.append((0, end_min))
    return segments



def shifts_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Semi-ouvert : un tour qui finit à 14:00 et un autre qui commence à
    14:00 ne se chevauchent PAS."""
    return any(a0 < b1 and b0 < a1 for a0, a1 in shift_segments(*a) for b0, b1 in shift_segments(*b))



def shift_contains_minute(interval: tuple[int, int], minute: int) -> bool:
    return any(s <= minute < e for s, e in shift_segments(*interval))



PLANNING_MAX_RANGE_DAYS = 31



# Seuils d'avertissement (D14) : « à confirmer terrain », donc des constantes
# nommées et non des nombres éparpillés dans le service.
PLANNING_MIN_REST_MINUTES = 11 * 60



PLANNING_MAX_NIGHTS_PER_WEEK = 3



PLANNING_NIGHT_START_MINUTE = 22 * 60



PLANNING_NIGHT_END_MINUTE = 5 * 60



SHIFT_ROLE_LABELS: dict[str, str] = {
    "shift_manager": "Responsable de tour",
    "team_lead": "Chef d'équipe",
    "pump_attendant": "Pompiste",
}



# Rôle RBAC (code) -> rôle dans le tour : l'éligibilité d'une personne dérive
# de son poste sur la station (A4), jamais d'un champ saisi à part.
RBAC_ROLE_TO_SHIFT_ROLE: dict[str, str] = {
    "zylo_liquid_shift_manager": "shift_manager",
    "zylo_liquid_team_lead": "team_lead",
    "zylo_liquid_pump_attendant": "pump_attendant",
}



_WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]



_MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]



def format_date_fr(day: date, with_weekday: bool = True) -> str:
    """« lundi 5 octobre » (messages d'erreur destinés au gérant)."""
    text = f"{day.day} {_MONTHS_FR[day.month - 1]}"
    return f"{_WEEKDAYS_FR[day.weekday()]} {text}" if with_weekday else text



def format_dates_fr(days: list[date], limit: int = 10) -> str:
    """« 7, 8 et 9 octobre » (même mois) ou « 30 septembre et 1 octobre »."""
    days = sorted(set(days))
    shown, rest = days[:limit], len(days) - limit
    if len({(d.year, d.month) for d in shown}) == 1:
        parts = [str(d.day) for d in shown]
        tail = f" {_MONTHS_FR[shown[0].month - 1]}"
    else:
        parts = [f"{d.day} {_MONTHS_FR[d.month - 1]}" for d in shown]
        tail = ""
    if rest > 0:
        return ", ".join(parts) + tail + f" et {rest} autre(s) date(s)"
    return (", ".join(parts[:-1]) + " et " + parts[-1] if len(parts) > 1 else parts[0]) + tail



def shift_occurrence_bounds(day: date, start_time: str, end_time: str) -> tuple[datetime, datetime] | None:
    """Début et fin réels (heure locale de la station, sans fuseau) d'un tour
    placé à une date : fin <= début = lendemain ; début = fin = 24 h."""
    start, end = parse_shift_time(start_time), parse_shift_time(end_time)
    if start is None or end is None:
        return None
    starts_at = datetime.combine(day, datetime.min.time()) + timedelta(minutes=start)
    return starts_at, starts_at + timedelta(minutes=shift_duration_minutes(start, end))



def intervals_overlap(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    """Semi-ouvert [début, fin) : 06:15 -> 06:15 enchaîné avec 06:15 -> 06:15 ne se chevauche pas."""
    return a[0] < b[1] and b[0] < a[1]



def is_night_interval(starts_at: datetime, ends_at: datetime) -> bool:
    """Un tour est « de nuit » s'il touche la plage 22:00-05:00 (heure locale)."""
    for offset in (-1, 0):
        base = datetime.combine(starts_at.date() + timedelta(days=offset), datetime.min.time())
        night = (base + timedelta(minutes=PLANNING_NIGHT_START_MINUTE), base + timedelta(days=1, minutes=PLANNING_NIGHT_END_MINUTE))
        if intervals_overlap((starts_at, ends_at), night):
            return True
    return False



def closed_iso_weekdays(closed_weekdays: str | None, weekly_hours: dict | None) -> set[int]:
    """Jours fermés (1=lundi..7=dimanche) d'une station : `weeklyHours` (par
    jour) l'emporte sur `closedWeekdays` quand il est renseigné, comme dans la
    fiche station (les deux mécanismes ne se combinent jamais)."""
    if weekly_hours:
        return {int(k) for k, v in weekly_hours.items() if isinstance(v, dict) and v.get("closed") and str(k).isdigit()}
    return {int(p) for p in (closed_weekdays or "").split(",") if p.strip().isdigit()}



ATTENDANCE_STATUSES = ("pending", "present", "late", "absent_justified", "absent_unjustified")



ATTENDANCE_TIMED_STATUSES = ("present", "late")



ATTENDANCE_ABSENT_STATUSES = ("absent_justified", "absent_unjustified")



ATTENDANCE_LINE_KINDS = ("planned", "replacement", "unplanned")



# Fenêtre de saisie du RT : début du tour - 3 h -> clôture (ou fin prévue tant que B3 n'existe pas) + 12 h.
ATTENDANCE_WINDOW_BEFORE_START = timedelta(hours=3)



ATTENDANCE_WINDOW_AFTER_END = timedelta(hours=12)



# Résolution de HH:MM (§7.3) : arrivée dans [début - 12 h ; fin prévue], départ dans ]arrivée ; fin prévue + 8 h].
ATTENDANCE_ARRIVAL_BEFORE_START = timedelta(hours=12)



ATTENDANCE_DEPARTURE_AFTER_END = timedelta(hours=8)



ATTENDANCE_EARLY_DEPARTURE_WARNING = timedelta(minutes=15)



ATTENDANCE_REASON_MIN, ATTENDANCE_REASON_MAX = 3, 300



ATTENDANCE_NOTE_MAX = 300



ATTENDANCE_EXTERNAL_NAME_MIN, ATTENDANCE_EXTERNAL_NAME_MAX = 2, 120



ATTENDANCE_MAX_LINES = 200



ATTENDANCE_STATUS_LABELS: dict[str, str] = {
    "pending": "à pointer",
    "present": "présent",
    "late": "en retard",
    "absent_justified": "absent justifié",
    "absent_unjustified": "absent non justifié",
}



# Nom de l'événement de domaine publié (app/shared/events.py) pour chaque absence non justifiée.
ATTENDANCE_ABSENCE_UNJUSTIFIED_EVENT = "AttendanceAbsenceUnjustified"



def format_hhmm(value: datetime) -> str:
    return value.strftime("%H:%M")



def resolve_arrival_time(hhmm: str, starts_at: datetime, ends_at: datetime) -> datetime | None:
    """Arrivée « HH:MM » -> horodatage : l'instant le plus proche du début du
    tour dans [début - 12 h ; fin prévue]. Une arrivée à 21:50 pour un tour de
    nuit 22:00 devient la veille au soir. None si aucun instant ne convient."""
    minutes = parse_shift_time(hhmm)
    if minutes is None:
        return None
    base = datetime.combine(starts_at.date(), datetime.min.time()) + timedelta(minutes=minutes)
    candidates = [base + timedelta(days=d) for d in (-2, -1, 0, 1, 2)]
    inside = [c for c in candidates if starts_at - ATTENDANCE_ARRIVAL_BEFORE_START <= c <= ends_at]
    return min(inside, key=lambda c: (abs(c - starts_at), c)) if inside else None



def resolve_departure_time(hhmm: str, arrived_at: datetime, ends_at: datetime) -> datetime | None:
    """Départ « HH:MM » -> horodatage : l'instant strictement postérieur à
    l'arrivée, au plus tard fin prévue + 8 h, le plus proche de la fin prévue.
    Pour un tour de 24 h (06:15 -> 06:15), « 06:15 » est résolu au lendemain.
    None si aucun instant ne convient."""
    minutes = parse_shift_time(hhmm)
    if minutes is None:
        return None
    base = datetime.combine(arrived_at.date(), datetime.min.time()) + timedelta(minutes=minutes)
    candidates = [base + timedelta(days=d) for d in (-1, 0, 1, 2)]
    inside = [c for c in candidates if arrived_at < c <= ends_at + ATTENDANCE_DEPARTURE_AFTER_END]
    return min(inside, key=lambda c: (abs(c - ends_at), c)) if inside else None



def attendance_window(starts_at: datetime, ends_at: datetime, closed_at: datetime | None) -> tuple[datetime, datetime]:
    """Fenêtre de saisie du RT (naïve, heure locale station). Tant que B3 n'existe
    pas, `closed_at` est nul et la fin prévue du tour fait office de clôture."""
    reference = closed_at.replace(tzinfo=None) if closed_at is not None else ends_at
    return starts_at - ATTENDANCE_WINDOW_BEFORE_START, reference + ATTENDANCE_WINDOW_AFTER_END



def attendance_delay_minutes(arrived_at: datetime | None, starts_at: datetime) -> int | None:
    """Écart de retard CALCULÉ (jamais stocké) : arrivée - début du tour, si positif."""
    if arrived_at is None or arrived_at <= starts_at:
        return None
    return int((arrived_at - starts_at).total_seconds() // 60)



HANDOVER_KINDS = ("instruction", "open_issue", "info")



HANDOVER_CATEGORIES = ("pump", "tank", "delivery", "price_credit", "safety", "staff", "customer", "report_feedback", "other")



HANDOVER_IMPORTANCES = ("normal", "high")



HANDOVER_MAX_ITEMS = 50



HANDOVER_DESCRIPTION_MIN, HANDOVER_DESCRIPTION_MAX = 3, 1000



HANDOVER_RESOLUTION_MIN, HANDOVER_RESOLUTION_MAX = 3, 500



# Le RT écrit jusqu'à 12 h après la fin du tour (clôture, ou fin prévue tant que B3 n'existe pas) ; au-delà, le gérant seul.
HANDOVER_WRITE_AFTER_END = timedelta(hours=12)



# Anomalie ouverte depuis plus de 7 jours : avertissement non bloquant (seuil à confirmer terrain).
HANDOVER_OLD_ISSUE_DAYS = 7



# Rôle de l'auteur mémorisé sur la ligne (affiche « consigne du gérant » sans dépendre d'un rôle qui changerait).
HANDOVER_AUTHOR_ROLE_MANAGER = "station_admin"



HANDOVER_AUTHOR_ROLE_SHIFT_MANAGER = "shift_manager"



# Fenêtre d'ouverture : début - 60 min <= maintenant < fin (marge de prise de poste et de passation ;
# 60 min arbitraire, À CONFIRMER TERRAIN, PC-39).
SHIFT_OPENING_EARLY_MINUTES = 60



# Événements de domaine publiés APRÈS le commit (aucun abonné en B3 ; alertes câblées en F4).
SHIFT_OPENED_EVENT = "ShiftOpened"



SHIFT_OPENED_OFF_PLANNING_EVENT = "ShiftOpenedOffPlanning"



def shift_opening_window(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    """Fenêtre d'ouverture [début - 60 min ; fin[ (heure locale station, naïve)."""
    return starts_at - timedelta(minutes=SHIFT_OPENING_EARLY_MINUTES), ends_at



# Écart entre deux fermetures au-delà duquel un avertissement ambre est affiché (jours ; À CONFIRMER TERRAIN).
SHIFT_REPORT_LONG_GAP_DAYS = 2



VOUCHER_NUMBER_MAX, PAYMENT_CODE_MAX = 30, 40
