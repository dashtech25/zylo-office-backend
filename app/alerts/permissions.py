"""Permissions déclarées par le module Alertes — extrait de
`app/modules/zylo_liquid/permissions.py` (2026-09-15, Phase 3 de la
migration monolithe modulaire). Mêmes valeurs de chaîne qu'avant
l'extraction : elles sont déjà seedées dans la table `permission` et
attachées à des rôles existants (voir `roles_seed.py`) — renommer la
chaîne casserait les assignations de rôle déjà en base, ce que cette
extraction ne fait jamais (seul l'emplacement du code Python bouge)."""

ALERT_READ = "zyloLiquid.alert.read"
# D3/D6 (refonte alertes) : acquitter ("je m'en occupe") est une action bien
# plus légère que résoudre manuellement avec justification — ouverte à des
# rôles opérationnels qui n'ont pas ALERT_MANAGE (le pompiste, premier à
# constater une fuite ou un niveau bas sur le terrain, notamment).
ALERT_ACKNOWLEDGE = "zyloLiquid.alert.acknowledge"
ALERT_MANAGE = "zyloLiquid.alert.manage"
