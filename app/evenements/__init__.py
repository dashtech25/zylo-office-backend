"""Contrat commun des événements de domaine (BE-150).

Ce paquet fixe la forme de l'enveloppe qui transporte tout événement publié par le socle et les
modules, et le point d'entrée `publier_enveloppe` qui la valide avant toute distribution. Le
transport reste `app.shared.events` (registre en mémoire, un process) ; la persistance et la
consommation idempotente relèvent de BE-166.
"""
