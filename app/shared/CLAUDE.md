# app/shared/ — briques réutilisables par tous les modules

Voir la directive complète : `/CLAUDE.md` (racine du dépôt).

Contient les référentiels et utilitaires génériques consommés par
plusieurs modules : `pagination.py` (Page générique), `schemas.py`
(enveloppes de réponse), `permissions.py` (permissions du référentiel Core
partagé — devises, géo), `currency*.py`, `geo*.py`, `models.py` (mixins de
modèles).

**Avant de créer quelque chose ici**, vérifie ces deux conditions :
1. C'est **réellement réutilisé** (ou immédiatement réutilisable) par
   plusieurs modules — pas seulement pratique pour celui en cours.
2. Ça **ne contient aucune règle métier propre à un domaine** (rien qui
   parle de cuves, stations, contacts CRM, articles de stock...).

Si l'une des deux conditions échoue, le code va dans
`app/modules/<domaine>/`, jamais ici — même bien écrit (pas de "junk
drawer"). `shared/` ne doit jamais importer `app.modules.*`.
