# Quelle palette de couleurs fait foi ?

- **Question** : la palette de référence est-elle `globals.css`, ou la palette de la coquille (sidebar) et du prototype ?
- **Tâches concernées** : T-032, T-030
- **Contexte** : `src/app/globals.css` déclare `--color-primary: #3498db` sur `:root` (vérifié, ligne 13) et redéclare les tokens dans un bloc `@theme inline` (ligne 100). La sidebar utilise `#5ebcfc`, et `src/modules/zylo-liquid/styles/prototype.css` (403 lignes) porte d'autres couleurs (revue FRT-004). `globals.css` précise « light-only ».
- **Options** :
  - A. `globals.css` fait foi ; la sidebar prend la couleur de marque `#3498db` (recommandation).
  - B. La palette de la sidebar fait foi : `globals.css` est réaligné, et les autres composants changent.
  - C. Nouvelle palette : hors périmètre, à commander au design.
- **Recommandation vérifiée** : option A. Vérification : les lignes citées ci-dessus ont été relues. Le changement visuel de la sidebar est à valider par le client avant la fusion de T-032.
- **État** : En attente de réponse (validation design)
