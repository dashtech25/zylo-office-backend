# Bibliothèque de graphiques de référence

- **Question** : quelle bibliothèque de graphiques est la référence du frontend ?
- **Tâches concernées** : T-033a, T-033b
- **Contexte** : trois graphiques utilisent des approches différentes (revue FRT-006). `src/modules/zylo-tanker/components/EChartsTrendChart.tsx` existe (vérifié) et utilise ECharts.
- **Options** :
  - A. ECharts, déjà utilisé par le tanker (recommandation).
  - B. Recharts : option à évaluer si un usage existant le justifie (usage non recompté ici).
  - C. Les deux : rejeté, maintenance double.
- **Recommandation vérifiée** : option A. Vérification : présence du composant ECharts (vérifié) ; l'usage de Recharts n'a pas été recompté par la revue.
- **État** : En attente de réponse
