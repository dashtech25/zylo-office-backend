# Fichiers : stockage, téléchargement et limites (T-014)

- **Statut** : à vérifier (T-014, branche `fix/T-014-uploads`).
- **Décision appliquée** : `docs/questions/securite/types-fichiers-autorises.md`, option A (PDF, PNG, JPEG, WebP).
- **Problèmes couverts** : BCK-008 (XSS stockée par upload), BCK-012 (limites d'import/export), IAM-019 (photo de profil), REV-S-10.

## Liste blanche

| Type | Extension stockée | Signature (octets) | Affichage |
|---|---|---|---|
| PDF | `.pdf` | `%PDF-` dans les 1024 premiers octets | en ligne |
| PNG | `.png` | `89 50 4E 47 0D 0A 1A 0A` | en ligne |
| JPEG | `.jpg` | `FF D8 FF` | en ligne |
| WebP | `.webp` | `RIFF....WEBP` | en ligne |

- Source unique : `app/shared/file_types.py`. Ni le nom, ni le Content-Type fourni, ni l'extension ne décident : seuls les octets décident.
- L'extension stockée est celle du type détecté. La référence est générée par le backend (`<organisation>_<uuid><ext>` en local, `<organisation>/<uuid><ext>` en S3) : le nom fourni n'entre jamais dans le stockage.
- Le nom renvoyé (`fileName`) est réduit à son nom de base (pas de chemin, pas de `..`, 255 caractères au plus).

## Upload (`POST /api/v1/storage/upload`)

1. L'organisation indiquée par `X-Organization-Id` doit être une organisation dont l'utilisateur est membre (403 sinon).
2. Lecture bornée : `read(MAX+1)` (MAX = 25 Mo). Au-delà : 413, sans chargement complet.
3. Type hors liste blanche : 415.
4. Les miniatures ne sont produites que pour les images de la liste.

## Téléchargement (`GET /api/v1/storage/local/{ref}`, lien signé)

- Toutes les réponses : `X-Content-Type-Options: nosniff` et `Content-Security-Policy: sandbox`.
- PDF et images de la liste : `Content-Disposition: inline`, type réel.
- Tout autre fichier, y compris un HTML ou un SVG stocké avant T-014 : `attachment`, type `application/octet-stream` si le type est actif (html, svg, xml, javascript), sans modification du stockage.

## Import et export

- Import XLSX (`POST /api/v1/import/xlsx`) : 5 Mo au plus (413), 10 000 lignes au plus et 100 colonnes au plus (413).
- Export XLSX et DOCX (`POST /api/v1/export/xlsx|docx`) : 10 000 lignes et 100 colonnes au plus (413).

## Photo de profil

- `PATCH /api/v1/users/{id}` : une référence `photoStorageReference` n'est acceptée que si son préfixe d'organisation désigne une organisation dont l'acteur est membre (403 sinon). `null` efface la photo.

## Limites connues

- Le stockage n'enregistre pas l'utilisateur qui a uploadé un fichier : le contrôle de photo vérifie l'appartenance à l'organisation, pas l'auteur exact. Un membre de deux organisations peut réutiliser une référence de l'autre.
- `POST /api/v1/zylo-liquid/documents` n'est pas contrôlé sur le préfixe de la référence (les tests existants utilisent des références fictives) : à traiter dans une tâche dédiée.
- Les bureautiques (DOCX, XLSX) envoyés par un utilisateur sont désormais refusés (415). Les DOCX générés par le serveur (bons de commande) ne passent pas par la route d'upload et restent stockables.
- Les SVG ne sont pas acceptés : aucune prise en charge d'un aperçu SVG.
- Le rendu PDF dans une iframe avec `Content-Security-Policy: sandbox` n'a pas été vérifié dans un navigateur réel (test Playwright non lancé dans cette tâche).
