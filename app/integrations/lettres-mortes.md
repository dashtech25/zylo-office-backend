# Lettres mortes d'intégration et reprise manuelle (BE-165)

Modules : `app/integrations/lettres_mortes.py` (service), `app/integrations/router.py` (routes), `app/integrations/models.py` (table `lettreMorte`, migration `c165a0b1d2e3`), `app/integrations/permissions.py` et `seed.py` (permission `integrations.manage`).

## Routes

| Méthode | Chemin | Permission | Effet |
|---|---|---|---|
| GET | `/api/v1/integrations/lettres-mortes` | `integrations.read` | liste les lettres du tenant courant |
| POST | `/api/v1/integrations/lettres-mortes/{id}/reprises` | `integrations.manage` | reprise manuelle, corps `{"motif": "..."}` |

## Entrée dans la file

Un échec définitif (`echec` sans `prochaineTentativeAt`, journal BE-164) est déplacé par `deplacer_en_lettre_morte`. Une seule lettre par tentative. `originalId` reçoit l'`eventId` de la tentative.

## Reprise

Ordre des contrôles : permission (403) puis motif non vide (422) puis lettre du tenant (404) puis lettre non reprise (409 `REPLAY_DUPLICATE`). La reprise pose `operateur`, `motif`, `reprisAt`, appelle la relance une seule fois et écrit l'audit `integration.lettre_morte.reprendre`, dans un même savepoint. Une erreur de relance annule la reprise.

## Écarts et questions ouvertes

- QE-165-01 : le rattachement au tenant s'appelle `organizationId` (convention BE-160/164), et non `tenantId`. Recommandation appliquée.
- QE-165-02 : aucun adaptateur de relance n'existe en BE-165. La route ne fait que marquer la reprise ; le branchement sur le consommateur d'événements (BE-166) reste à faire.
- QE-165-03 : la durée de rétention des lettres est NON DÉFINIE (QE-PAR-17) ; aucune purge n'est implémentée.
- QE-165-04 : le seuil d'épuisement des tentatives n'est pas porté par ce module : l'appelant décide quand déplacer un échec (le service exige seulement un échec définitif).
- Deux reprises concurrentes sur la même lettre ne sont pas verrouillées au niveau SQL ; la vérification `reprisAt` est séquentielle.
