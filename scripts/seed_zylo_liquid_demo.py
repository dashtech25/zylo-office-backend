"""CLI de développement — peuple une organisation avec un réseau Zylo Liquid
de démonstration (app.modules.zylo_liquid.dev_seed.seed_demo_network).

Usage :
    .venv/bin/python scripts/seed_zylo_liquid_demo.py <organization-slug>

N'écrit rien si l'organisation a déjà au moins une station (idempotent).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.identity.models import Organization, OrganizationUser  # noqa: E402
from app.modules.zylo_liquid.dev_seed import seed_demo_network  # noqa: E402


async def main(slug: str) -> None:
    async with AsyncSessionLocal() as db:
        organization = (await db.execute(select(Organization).where(Organization.slug == slug))).scalar_one_or_none()
        if organization is None:
            print(f"Organisation introuvable pour le slug '{slug}'.")
            return

        owner_membership = (
            await db.execute(select(OrganizationUser).where(OrganizationUser.organizationId == organization.id))
        ).scalars().first()
        if owner_membership is None:
            print(f"Aucun membre trouvé pour l'organisation '{slug}' — impossible d'attribuer la création des prix.")
            return

        result = await seed_demo_network(db, organization.id, owner_membership.userId)
        print(result)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: seed_zylo_liquid_demo.py <organization-slug>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
