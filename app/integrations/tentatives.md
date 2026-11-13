# Journal des tentatives d'intégration (BE-164)

Module : `app/integrations/tentatives.py` (service), `app/integrations/models.py` (table `tentativeIntegration`, migration `9b164a0c164e`), `app/integrations/permissions.py` et `seed.py` (permission `integrations.read`).

## Ce qui est journalisé

Une ligne par tentative : connecteur, événement, corrélation, issue (`succes` ou `echec`), code d'erreur, durée mesurée, rang de tentative, prochaine tentative. Aucun payload ni corps de réponse n'est stocké.

## Exécution

`executer_effet` reçoit l'effet sous forme de fonction asynchrone. Une `ErreurTransitoire` planifie la reprise, une `ErreurDefinitive` ne planifie rien, les autres exceptions ne sont pas journalisées. La clé d'effet est le couple (connecteur, événement) : un second appel après succès ne ré-exécute pas l'effet.

## Backoff

Délai = base x 2^(rang - 1), plafonné. Base et plafond viennent de `INTEGRATION_BACKOFF_BASE_SECONDS` et `INTEGRATION_BACKOFF_CAP_SECONDS`, sans défaut codé (QE-PAR-09). Si l'une manque, `ConfigurationBackoffAbsente` est levée.

## Droits

Lecture par `lister_tentatives` : permission `integrations.read` dans l'organisation demandée, sinon 403 `PERMISSION_DENIED`. Les lignes sont filtrées par organisation.

## Écarts avec la définition

- Rattachement au tenant nommé `organizationId` (convention BE-160), et table nommée `tentativeIntegration` (camelCase).
- Contenu restreint : non défini (QE-PAR-16), aucune colonne de contenu n'existe.
