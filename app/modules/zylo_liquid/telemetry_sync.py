"""Sondage continu de l'API Holykell (h-smartlink.com / holykell-simulator
en dev) — refonte alertes Étape 2, décision D1.

Avant cette refonte, cette logique vivait exclusivement dans
`scripts/sync_holykell_live.py`, un script externe lancé à la main sur un
poste (`.venv/bin/python scripts/sync_holykell_live.py`). Conséquence :
en production, si personne ne pensait à lancer ce script, la télémétrie
n'était jamais évaluée — aucune alerte n'était jamais créée ni mise à jour,
quel que soit l'état réel des cuves. Cette boucle tourne désormais DANS ce
process backend (démarrée par `app/main.py` au boot), tant que le serveur
est en ligne.

Contrat d'API respecté à la lettre : voir `instruction_simulatiom.md`
(captures réelles observées en production h-smartlink.com) — `GET
/admin-api/business/deviceGroup/` retourne bien `sensorWayList` (dernières
valeurs mesurées) par device, c'est le comportement réel documenté, pas une
approximation. Jamais d'accès direct à une base de données Holykell tierce
— uniquement des GET authentifiés contre l'API publique (réelle en
production via `HOLYKELL_SYNC_BASE_URL=https://www.h-smartlink.com`, ou le
simulateur en dev/démo).

Résolution du mapping capteur → cuve **depuis la base** à chaque cycle
(`TankSensorMapping`, `active=True`), jamais depuis une table en mémoire
figée au démarrage — un nouveau mapping ajouté via l'API pendant que le
process tourne est donc pris en compte au cycle suivant, sans redémarrage.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import (
    HolykellAccount,
    HolykellDeviceRegistry,
    TankMeasurement,
    TankSensorMapping,
)
from app.modules.zylo_liquid.service import (
    run_alert_evaluation_for_tank,
    run_delivery_detection_for_tank,
)

logger = logging.getLogger("zylo_office.holykell_sync")

DEFAULT_INTERVAL_SEC = 5


async def _login(client: httpx.AsyncClient, base_url: str, username: str, password: str) -> tuple[str, str]:
    resp = await client.post(f"{base_url}/admin-api/system/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["accessToken"], data["tenantId"]


async def sync_one_account(db, client: httpx.AsyncClient, base_url: str, account: HolykellAccount) -> set:
    """Un cycle de sondage pour un compte Holykell : login, lecture des
    groupes/devices, écriture registre + mesure, retourne les cuves
    touchées (pour évaluation alertes/livraison par l'appelant)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        access_token, tenant_id = await _login(client, base_url, account.holykellUsername, account.holykellPassword)
        resp = await client.get(
            f"{base_url}/admin-api/business/deviceGroup/",
            headers={"Authorization": f"Bearer {access_token}", "tenant-id": tenant_id},
        )
        resp.raise_for_status()
        groups = resp.json().get("data", [])
    except Exception as exc:
        account.lastSyncStatus = "failed"
        account.lastSyncError = repr(exc)[:500]
        await db.commit()
        logger.warning("Échec de synchronisation Holykell (compte %s) : %r", account.id, exc)
        return set()

    touched_tank_ids: set = set()
    for g in groups:
        for device in g.get("deviceList", []):
            serial = device["serialNumber"]
            status = device.get("status", 1)
            sensor_way_list = device.get("sensorWayList") or {}

            # Le TSL donne flag->sensorId ; sensorWayList donne flag->value.
            flag_to_sensor_id = {}
            tsl_raw = device.get("tsl")
            if tsl_raw:
                try:
                    tsl = json.loads(tsl_raw)
                    for sd in tsl.get("sensorDatas", []):
                        flag_to_sensor_id[str(sd["flag"])] = sd["sensorId"]
                except Exception:
                    pass

            for flag, value in sensor_way_list.items():
                sensor_id = flag_to_sensor_id.get(str(flag))
                if sensor_id is None:
                    continue

                registry = (await db.execute(
                    select(HolykellDeviceRegistry).where(HolykellDeviceRegistry.hkSensorId == sensor_id)
                )).scalar_one_or_none()
                if registry is None:
                    continue  # capteur connu de Holykell mais pas encore découvert/mappé côté Zylo Liquid

                registry.lastValue = value
                registry.lastValueAt = now
                registry.hkLastStatus = 1 if status == 1 else 0
                # Une ingestion réussie EST une visibilité du capteur (même
                # règle que l'ancien script — voir hkLastSeenAt affiché
                # « Dernière visibilité » dans l'ATG).
                registry.hkLastSeenAt = now

                db.add(TankMeasurement(
                    hkSensorId=sensor_id, hkDeviceSerial=serial, hkSensorName=registry.hkSensorName,
                    hkUnit=registry.hkUnit, measuredAt=now, receivedAt=now, rawValue=value, insertedAt=now,
                ))

                mappings = (await db.execute(
                    select(TankSensorMapping).where(
                        TankSensorMapping.hkSensorId == sensor_id,
                        TankSensorMapping.active == True,  # noqa: E712
                    )
                )).scalars().all()
                for mapping in mappings:
                    touched_tank_ids.add(mapping.tankId)

    account.lastSyncAt = now
    account.lastSyncStatus = "success"
    account.lastSyncError = None
    await db.commit()
    return touched_tank_ids


async def sync_all_accounts() -> None:
    """Un cycle complet : tous les comptes Holykell actifs, toutes
    organisations confondues (chacun avec ses propres identifiants)."""
    base_url = settings.HOLYKELL_SYNC_BASE_URL
    if not base_url:
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        async with AsyncSessionLocal() as db:
            accounts = (await db.execute(
                select(HolykellAccount).where(HolykellAccount.syncEnabled == True)  # noqa: E712
            )).scalars().all()

            all_touched: set = set()
            for account in accounts:
                touched = await sync_one_account(db, client, base_url, account)
                all_touched |= touched

            for tank_id in all_touched:
                try:
                    await run_alert_evaluation_for_tank(db, tank_id)
                    await run_delivery_detection_for_tank(db, tank_id)
                except Exception:
                    # Une cuve en échec d'évaluation ne doit jamais bloquer
                    # les autres — et jamais rester silencieuse (Étape 1,
                    # constat : les exceptions avalées sans trace du script
                    # externe sont précisément ce que cette refonte corrige).
                    logger.exception("Échec d'évaluation alertes/livraison pour la cuve %s", tank_id)


async def sync_loop() -> None:
    """Boucle infinie — démarrée une seule fois au boot du serveur
    (app/main.py), tourne tant que le process est en vie."""
    interval = settings.HOLYKELL_SYNC_INTERVAL_SEC or DEFAULT_INTERVAL_SEC
    logger.info("Boucle de synchronisation Holykell démarrée (intervalle %ss, base=%s)", interval, settings.HOLYKELL_SYNC_BASE_URL)
    while True:
        try:
            await sync_all_accounts()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cycle de synchronisation Holykell en échec")
        await asyncio.sleep(interval)
