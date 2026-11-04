"""Registre des modules (socle).

Modules: `models.py` (tables module, organizationModule), `manifeste.py` (codes reconnus, versions de
manifeste supportées), `etats.py` (états absent, inconnu, incompatible, disponible : seul disponible
ouvre l'accès), `service.py` (activation par organisation, garde is_module_active).

Garde d'accès (BE-025) : `service._projeter_acces` calcule `accessState`, `canActivate` et `canOpen`
à partir de l'activation, du registre et de l'entitlement ; le catalogue et
`GET /organizations/current/modules/{moduleId}/access` lisent cette même projection. Fail-closed :
seuls l'absence de ligne d'entitlement (accès legacy) et un droit `active` avec abonnement
`active`/`trial` ouvrent l'accès.
"""
