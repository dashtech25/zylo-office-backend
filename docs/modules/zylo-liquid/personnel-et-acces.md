# Personnel de station et accès (A4, T-021)

Aucun mot de passe n'est généré, renvoyé ni stocké dans les réponses du module personnel. Un compte est créé **en attente** par le flux d'invitation de `app/identity/invitations.py` ; la personne choisit son mot de passe via le lien reçu par e-mail (usage unique, expiration).

## Endpoints et contrats

| Route | Réponse | Changement par rapport à remy |
|---|---|---|
| `POST /station-staff` | `CreateStationStaffResponse` : `staff`, `invitationExpiresAt` | `temporaryPassword` retiré |
| `POST /station-staff/bulk` | `BulkCreateStationStaffResponse` : `createdCount`, `data[]` (`rowNumber`, `staff`, `invitationExpiresAt`) | nouvelle route |
| `POST /station-staff/{user_id}/reset-password` | `ResetStationStaffPasswordResponse` : `userId`, `invitationExpiresAt` | ne renvoie plus de mot de passe ; compte actif refusé (409 `password_reset_unavailable`) |
| `POST /station-staff/{user_id}/reactivate` | `StationStaffResponse` | nouvelle route, garde `stationStaff.manage` scopée à la station de la fiche |
| `GET /station-staff?stationId=` | `StationStaffListItem[]` (`hasProfile`, poste, niveau hiérarchique) | enrichi |

## Règles

- **Validation avant écriture** (lot) : e-mail, N° d'employé, poste et hiérarchie sont vérifiés pour toutes les lignes avant toute écriture ; les erreurs sont rapportées ensemble.
- **Écriture par personne** : compte + invitation (commit du flux T-021), puis fiche de poste, puis attribution du rôle. L'atomicité complète d'une ligne ne peut être garantie tant que `assign_role` n'accepte pas `commit=False` (lot B-L5). Voir [questions](../../questions/travail-en-cours/personnel-acces.md).
- **Hiérarchie** : un gérant ne nomme ni un gérant ni la direction ; la personne gérée doit être de niveau inférieur (`exploitation/personnel_postes.py`).
- **Garde du dernier gérant** : une station ne reste jamais sans gérant actif.
- **Envoi** : sans e-mail configuré, la création est refusée avant écriture (503 `user_creation_disabled`), comme pour tout compte.
