# Préférences et consentement par catégorie (BE-168)

Module : `app/notifications/preferences.py`. Table : `preference_notification` (migration `8e5a2c1d9f3b`).

## Routes

| Méthode et chemin | Rôle | Réponses |
| --- | --- | --- |
| `GET /api/v1/notifications/preferences` | Préférences de l'utilisateur courant (une ligne par catégorie renseignée) | 200 |
| `PUT /api/v1/notifications/preferences/{categorie_code}` | Consentement de l'utilisateur courant pour la catégorie ; `{"consentement": false}` = désinscription | 200 ; 404 NOTIFICATION_CATEGORY_NOT_FOUND |

## Règles

| Règle | Comportement |
| --- | --- |
| CA-1 | Chaque `PUT` écrit `horodatageConsentement` (instant UTC) et `sourceConsentement`. |
| CA-2 | Après désinscription, `verifier_envoi_autorise` lève `403` CONSENT_SUPPRESSED (consommé par BE-169). |
| CA-3 | Lire ou modifier les préférences d'un autre utilisateur : `403` PERMISSION_DENIED. |
| CA-4 | Pas de plage de silence ni d'heure calme. Pas de préférence inventée pour une catégorie non renseignée. |
| CA-5 | Cible hors de l'organisation active : `404` TENANT_MISMATCH. |

## Points ouverts

- QE-PAR-02 : les routes n'identifient que l'utilisateur courant ; la règle CA-3 est vérifiée dans le service.
- QE-PAR-04 : pas de colonne `canal`.
- QE-PAR-14 : plage de silence non implémentée.
- Absence de ligne : aucune suppression d'envoi, aucun consentement présumé (à confirmer avant BE-169).
