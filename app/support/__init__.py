"""Accès support et administration, en lecture seule par défaut (BE-262).

Un membre du support ne lit une organisation qu'avec un accès `acces_support`
actif : mode `lecture` par défaut, justification obligatoire, fin datée, audit
de chaque accès et de chaque action. L'écriture exige le mode `ecriture`, la
permission `support.write_sensible` et un accès non expiré.
"""
