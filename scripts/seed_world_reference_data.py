"""Charge le référentiel mondial des pays et devises (Country/Currency,
Core, communs à tous les modules) — jamais saisis à la main : ce script
lit `app/shared/data/world_reference_data.json`, lui-même généré une seule
fois par extraction directe des données natives d'Odoo (`res_country_data.xml`
et `res_currency_data.xml` d'`addons/base`, l'ancienne version officielle de
Zylo Office) — les mêmes données que celles qu'utilisait l'ancien système,
jamais réinventées ni tapées à la main.

Idempotent : n'insère que les pays/devises absents, ne touche jamais une
ligne déjà présente (une devise ou un pays déjà en base peut avoir été
corrigé manuellement — ce script ne doit jamais écraser une correction).

Volontairement absent de ce script : Region et City. Contrairement aux
pays/devises (référentiel mondial stable), les régions et villes dépendent
du découpage réel de chaque réseau de stations et doivent être créées via
l'API existante (déjà supportée), pas préchargées globalement."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.shared.currency import Currency
from app.shared.geo import Country

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "shared" / "data" / "world_reference_data.json"


async def main() -> None:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    async with AsyncSessionLocal() as db:
        existing_currency_codes = {row[0] for row in (await db.execute(select(Currency.code))).all()}
        created_currencies = 0
        for entry in data["currencies"]:
            if entry["code"] in existing_currency_codes:
                continue
            db.add(Currency(code=entry["code"], name=entry["name"], symbol=entry["symbol"], decimalPlaces=entry["decimalPlaces"]))
            created_currencies += 1
        await db.commit()

        existing_country_codes = {row[0] for row in (await db.execute(select(Country.isoCode2))).all()}
        currency_rows = {row[0]: (row[1], row[2]) for row in (await db.execute(select(Currency.code, Currency.symbol, Currency.id))).all()}
        currency_by_code = {code: symbol for code, (symbol, _id) in currency_rows.items()}
        currency_id_by_code = {code: cid for code, (_symbol, cid) in currency_rows.items()}
        created_countries = 0
        for entry in data["countries"]:
            if entry["isoCode2"] in existing_country_codes:
                continue
            currency_code = entry["currencyCode"] if entry["currencyCode"] in currency_by_code else "XAF"
            db.add(
                Country(
                    isoCode2=entry["isoCode2"],
                    name=entry["name"],
                    currencyId=currency_id_by_code.get(currency_code),
                    currencyCode=currency_code,
                    currencySymbol=currency_by_code.get(currency_code, "FCFA"),
                    phonePrefix=entry["phonePrefix"],
                    defaultTimezone=entry["defaultTimezone"],
                )
            )
            created_countries += 1
        await db.commit()

        # Correction ciblée d'un premier run de ce script (avant l'ajout du
        # fuseau horaire par pays) : seules les lignes encore à la valeur
        # par défaut de la colonne ("Africa/Douala", jamais explicitement
        # choisie) sont corrigées — jamais une ligne dont le fuseau a été
        # changé depuis, manuellement ou non.
        tz_by_iso = {c["isoCode2"]: c["defaultTimezone"] for c in data["countries"]}
        placeholder_result = await db.execute(select(Country).where(Country.defaultTimezone == "Africa/Douala"))
        corrected = 0
        for country in placeholder_result.scalars().all():
            correct_tz = tz_by_iso.get(country.isoCode2)
            if correct_tz and correct_tz != "Africa/Douala":
                country.defaultTimezone = correct_tz
                corrected += 1
        await db.commit()

        print(f"Devises créées : {created_currencies} (déjà présentes ignorées : {len(existing_currency_codes)})")
        print(f"Pays créés : {created_countries} (déjà présents ignorés : {len(existing_country_codes)})")
        print(f"Fuseaux horaires corrigés (placeholder jamais explicitement choisi) : {corrected}")


if __name__ == "__main__":
    asyncio.run(main())
