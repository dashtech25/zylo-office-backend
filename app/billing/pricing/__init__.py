"""Module de tarification de la facturation : prix, devise et taxe (BE-078).

Valeurs non définies. Ce module ne contient aucun montant, aucune devise et aucun
taux de taxe. Ils sont saisis par la finance dans la table `price_rule` ; tant
qu'une règle n'est pas complète, la résolution bloque (voir `resolution.py`).
Aucune route HTTP : service interne utilisé par les devis (BE-077), le checkout
(BE-081), les factures (BE-086) et le changement de plan (BE-088).
"""
