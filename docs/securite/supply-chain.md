# Sécurité des dépendances et SBOM (BE-249)

Module : `scripts/securite/supply_chain.py`. Tests : `tests/test_supply_chain_be249.py`.

## SBOM

`generer_sbom` lit `requirements.txt` et produit un document CycloneDX 1.5 :
nom de l'artefact, révision de source et empreinte SHA-256 du fichier requirements
dans `metadata`. Chaque ligne doit être épinglée par `==` ; sinon le contrôle échoue.

## Audit de vulnérabilités

Le contrôle lit la sortie `pip-audit -f json`. Il bloque :

- toute vulnérabilité qu'aucune exception valide ne couvre ;
- toute exception expirée (le jour de l'expiration inclus reste valide) ;
- toute exception dépassant `duree_maximale_exception_jours`, si cette valeur est non nulle ;
- toute sortie d'audit ou exception illisible (échec fermé).

Une exception couvre une vulnérabilité si l'identifiant, le paquet (nom normalisé) et la
version exacte correspondent. Elle est définie dans `scripts/securite/exceptions_dependances.toml`
et doit porter `id`, `paquet`, `version`, `motif`, `responsable`, `date`, `expire`.

## Commandes

```bash
.venv/bin/python scripts/securite/supply_chain.py --revision "$(git rev-parse --short HEAD)" \
    --sbom-sortie var/sbom/sbom.cdx.json
.venv/bin/python scripts/securite/supply_chain.py --revision REV --sbom-sortie CHEMIN \
    --audit-json audit.json   # audit déjà produit
```

Sans `--audit-json`, `pip-audit` doit être installé (`requirements-dev.txt`). Code de
sortie : 0 si rien ne bloque, 1 sinon.

## Non défini (QE-EXP-19)

Sources de vulnérabilité, criticités et délais maximaux ne sont pas arrêtés. Ils figurent
dans `scripts/securite/supply_chain.toml` avec des valeurs vides ou à 0, qui signifient
« non appliqué ». Tant que la criticité n'est pas définie, toute vulnérabilité non couverte
bloque. Aucune de ces valeurs n'est codée dans le module.
