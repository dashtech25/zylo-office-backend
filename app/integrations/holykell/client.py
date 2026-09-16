"""Client Holykell (h-smartlink.com / holykell-simulator en dev) — Anti-
Corruption Layer, Phase 4 de la migration monolithe modulaire (voir
`ARCHITECTURE.md` §3.3 et `plan-migration/architecture-migration.md` dans le
repo prototype pour le plan complet).

Avant cette extraction, `app/modules/zylo_liquid/telemetry_sync.py` faisait
le login/les appels HTTP directement et parsait lui-même la forme JSON brute
de Holykell (`sensorWayList`, `tsl` imbriqué en JSON-dans-JSON, mapping
flag->sensorId) au milieu de sa boucle de synchronisation et de ses écritures
SQLAlchemy. Ce fichier est désormais le SEUL endroit du backend qui parle
HTTP à Holykell : login, lecture des groupes/devices, et mapping vers un DTO
interne propre (`HolykellSensorReading`) avant de rendre la main à
l'appelant. Aucune forme JSON brute de Holykell ne doit fuir hors de ce
fichier — `zylo_liquid` ne doit jamais avoir à connaître `sensorWayList`/
`tsl`/`flag`, seulement `HolykellSensorReading`.

Contrat d'API respecté à la lettre : voir `instruction_simulatiom.md`
(captures réelles observées en production h-smartlink.com) — `GET
/admin-api/business/deviceGroup/` retourne bien `sensorWayList` (dernières
valeurs mesurées) par device, c'est le comportement réel documenté, pas une
approximation.

Retry : borné (3 tentatives, backoff exponentiel 0.5s/1s/2s), uniquement sur
les échecs réseau/5xx — jamais sur un 4xx (identifiants invalides, endpoint
inexistant...), où retenter ne changerait rien. Pas de dépendance ajoutée
(`tenacity`/`backoff`) : aucun pattern de retry n'existait déjà ailleurs
dans ce backend, et le besoin ici est assez simple pour une boucle manuelle
sans en justifier une.

Timeout : explicite sur chaque appel (`DEFAULT_TIMEOUT`), jamais laissé à la
valeur par défaut du client HTTP appelant.

Limitation connue et assumée (pas un TODO, un choix documenté — voir Phase 4
du plan de migration) : PAS de circuit breaker ici. Un compte Holykell en
échec répété continue de retenter à chaque cycle de `telemetry_sync.py`
(l'intervalle entre cycles, généralement 5s, joue déjà un rôle amortisseur)
sans jamais "ouvrir le circuit" pour cesser temporairement d'essayer. Sur le
volume actuel (quelques comptes Holykell), le coût d'un appel qui échoue
vite (timeout court + retry borné) est négligeable. À revisiter si le nombre
de comptes/tiers externes croît significativement — amélioration future,
pas bloquante pour cette phase.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger("zylo_office.holykell_client")

DEFAULT_TIMEOUT = httpx.Timeout(10.0)
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5


class HolykellAuthError(Exception):
    """Login refusé par Holykell (identifiants invalides, compte suspendu...)."""


class HolykellApiError(Exception):
    """Un appel HTTP à Holykell a échoué après épuisement des tentatives de
    retry (réseau indisponible, 5xx persistant...)."""


class HolykellSensorReading(BaseModel):
    """Une mesure de capteur Holykell, déjà résolue par ce client — le
    mapping flag->sensorId (fait à partir du `tsl` brut) est réalisé ici,
    jamais laissé à l'appelant. C'est la seule forme sous laquelle
    `zylo_liquid` voit jamais une donnée issue de Holykell."""

    sensor_id: int
    device_serial: str
    device_online: bool
    value: float


async def _request_with_retry(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Exécute une requête HTTP avec retry borné + backoff exponentiel sur
    les échecs réseau et 5xx. Un 4xx n'est jamais retenté : c'est une erreur
    de la requête elle-même (identifiants invalides, endpoint inexistant...),
    pas un problème transitoire qu'un retry pourrait résoudre."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.request(method, url, timeout=DEFAULT_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last_exc = exc
        except httpx.TransportError as exc:
            last_exc = exc

        if attempt < MAX_ATTEMPTS:
            delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Appel Holykell %s %s en échec (tentative %s/%s), nouvelle tentative dans %.1fs : %r",
                method, url, attempt, MAX_ATTEMPTS, delay, last_exc,
            )
            await asyncio.sleep(delay)

    raise HolykellApiError(f"Appel Holykell {method} {url} en échec après {MAX_ATTEMPTS} tentatives") from last_exc


async def login(client: httpx.AsyncClient, base_url: str, username: str, password: str) -> tuple[str, str]:
    """Authentifie un compte Holykell, retourne `(accessToken, tenantId)`.
    Lève `HolykellAuthError` sur un refus d'authentification (4xx), et
    `HolykellApiError` si l'API reste injoignable après retry."""
    try:
        response = await _request_with_retry(
            client, "POST", f"{base_url}/admin-api/system/auth/login",
            json={"username": username, "password": password},
        )
    except httpx.HTTPStatusError as exc:
        raise HolykellAuthError(f"Login Holykell refusé pour {username!r} : HTTP {exc.response.status_code}") from exc
    data = response.json()["data"]
    return data["accessToken"], data["tenantId"]


async def fetch_sensor_readings(
    client: httpx.AsyncClient, base_url: str, access_token: str, tenant_id: str,
) -> list[HolykellSensorReading]:
    """Lit tous les groupes/devices/capteurs pour un compte déjà authentifié,
    retourne des DTO propres. Le parsing du `tsl` (JSON imbriqué,
    flag->sensorId) et la forme de `sensorWayList` (flag->value) restent
    entièrement internes à cette fonction, jamais exposés à l'appelant."""
    response = await _request_with_retry(
        client, "GET", f"{base_url}/admin-api/business/deviceGroup/",
        headers={"Authorization": f"Bearer {access_token}", "tenant-id": tenant_id},
    )
    groups = response.json().get("data", [])

    readings: list[HolykellSensorReading] = []
    for group in groups:
        for device in group.get("deviceList", []):
            serial = device["serialNumber"]
            online = device.get("status", 1) == 1
            sensor_way_list = device.get("sensorWayList") or {}

            flag_to_sensor_id: dict[str, int] = {}
            tsl_raw = device.get("tsl")
            if tsl_raw:
                try:
                    tsl = json.loads(tsl_raw)
                    for sensor_data in tsl.get("sensorDatas", []):
                        flag_to_sensor_id[str(sensor_data["flag"])] = sensor_data["sensorId"]
                except Exception:
                    logger.warning("TSL illisible pour le device Holykell %s, capteurs ignorés pour ce device", serial)
                    continue

            for flag, value in sensor_way_list.items():
                sensor_id = flag_to_sensor_id.get(str(flag))
                if sensor_id is None:
                    continue  # capteur connu de Holykell mais absent du TSL de ce device
                readings.append(
                    HolykellSensorReading(sensor_id=sensor_id, device_serial=serial, device_online=online, value=value)
                )

    return readings
