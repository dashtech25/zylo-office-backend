"""Achat par checkout (BE-081).

Contenu du paquet :
- `service.py` : `creer_checkout` et `lire_checkout`, seules portes d'écriture et de
  lecture des checkouts ;
- `router.py` : `POST /api/v1/billing/checkouts`, `GET /api/v1/billing/checkouts/{checkoutId}`.

Transitions : `open` à la création ; `pending`, `completed`, `failed`, `cancelled` et
`expired` relèvent de BE-082, BE-083 et BE-084. Aucune route de ce paquet ne fixe un
état autre que `open`.
"""
