# Types de fichiers acceptés en stockage et en diffusion

- **Question** : quels types de fichiers l'application accepte-t-elle en stockage ?
- **Tâches concernées** : T-014
- **Contexte** : le plan (§7, première version) disait « PDF et images seulement », la fiche T-014 retenait aussi « types bureautiques ». La contradiction est relevée par REV-S-10. `app/shared/storage_router.py` lit le fichier entier avant de contrôler la taille, et sert le fichier avec un type déduit de l'extension.
- **Options** :
  - A. PDF, PNG, JPEG, WebP seulement. Pas de contenu actif, pas de bureautique.
  - B. A plus les formats bureautiques (docx, xlsx) servis en téléchargement forcé uniquement.
- **Recommandation vérifiée** : option A. Les formats bureautiques sont ajoutés sur demande écrite du client, avec téléchargement forcé. Vérification : la fiche T-014 et le plan sont alignés sur cette liste.
- **État** : En attente de réponse
