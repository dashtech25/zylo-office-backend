# T-014 : Uploads sécurisés (liste blanche, lecture bornée, téléchargement forcé)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `fix/T-014-uploads` · **Base de test** : `zylo_t014_test` · **Ports** : back 3114
- **Dépendances** : aucune
- **Décisions requises** : `securite/types-fichiers-autorises.md` (recommandation : PDF et images seulement)

## Objectif
Empêcher le stockage et la diffusion inline de contenu actif (HTML, SVG, scripts) depuis l'origine de l'API. Liste blanche unique, type détecté par contenu, lecture bornée, téléchargement forcé hors images et PDF, et traitement des fichiers déjà stockés.

## Problèmes résolus
- BCK-008 (P1, XSS stockée), BCK-012 (P2, limite sur import XLSX), IAM-019 (P2, photo de profil non contrôlée), REV-S-10 (listes incohérentes, lecture avant limite, fichiers existants)

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-002 (ordre de fusion) ; T-005 (confort).

## Fichiers / modules concernés
- `app/shared/storage_router.py` (lecture ligne 34 : `await file.read()` avant contrôle de taille ; service ligne 87)
- `app/shared/storage.py` (extension, ligne 75)
- `app/shared/import_router.py` (lecture sans limite, ligne 27)
- `app/files/` (contrôle d'organisation)
- `app/identity/schemas.py`, `service.py` (photo de profil)
- `tests/test_uploads_securite.py` (créé)

## Stratégie
1. Liste blanche unique : PDF, PNG, JPEG, WebP (recommandation). Les types bureautiques ne sont ajoutés que sur demande écrite du client.
2. Lecture au plus `MAX+1` octets : refus dès le dépassement, sans charger le fichier entier.
3. Détection par contenu (signatures), extension réécrite selon le type détecté.
4. `Content-Disposition: attachment` pour tout ce qui n'est pas image ou PDF ; `X-Content-Type-Options: nosniff` partout ; `Content-Security-Policy: sandbox` sur les réponses de fichiers.
5. Fichiers déjà stockés avec une extension active : servis en `attachment` et `nosniff`, sans modification du stockage.
6. Photo de profil : la référence doit appartenir à l'acteur à l'écriture.
7. Import XLSX et exports : limite de lignes et de colonnes, réponse 413.

## Tests attendus
- `.html` et `.svg` refusés ; PDF valide accepté ; fichier HTML renommé `.png` refusé.
- Fichier existant de type actif : réponse `attachment` et `nosniff` (test sur un fichier de fixture).
- Import XLSX au-delà de la limite : 413.
- Lecture bornée : test qui vérifie qu'un fichier de 10 Mo n'est pas lu en entier.
- Playwright sur build prod : upload d'un document dans le module concerné.

## Critères d'acceptation
- Aucun type actif servi inline depuis l'API.
- Limites de taille sur import et export.
- Liste de types identique dans le plan, la fiche et le code.

## Risque et retour arrière
Moyen : un type légitime absent de la liste est refusé. Retour arrière : réactiver l'ancien contrôle par variable de configuration pour la seule liste, sans toucher au stockage.

## Livrable documentaire
- `docs/architecture/securite/fichiers.md` (créé)
- `docs/questions/securite/types-fichiers-autorises.md`

## Parallélisable avec
T-006 à T-013, T-015 (fichiers distincts).
