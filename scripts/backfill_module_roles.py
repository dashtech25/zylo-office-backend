"""Rattache les rôles par défaut existants à leur module (T-018 : backfill explicite).

Usage (à la demande, jamais au démarrage) :
    python scripts/backfill_module_roles.py --dry-run   # rapport seul
    python scripts/backfill_module_roles.py             # applique, puis rapport JSON

Sans effet sur les rôles personnalisés (listés dans le rapport) ni sur les
permissions. Relançable : un rôle déjà rattaché est ignoré.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES as ZL_ROLES  # noqa: E402
from app.modules.zylo_tanker.roles_seed import DEFAULT_ROLES as ZT_ROLES  # noqa: E402
from app.rbac.module_backfill import backfill_module_roles  # noqa: E402


async def main(dry_run: bool) -> None:
    defaults = {
        "zylo_liquid": [code for code, _name, _perms in ZL_ROLES],
        "zylo_tanker": [code for code, _name, _perms in ZT_ROLES],
    }
    async with AsyncSessionLocal() as db:
        report = await backfill_module_roles(db, defaults, dry_run=dry_run)
    print(json.dumps({"dryRun": dry_run, **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Produit le rapport sans rien modifier.")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
