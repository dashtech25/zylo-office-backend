"""Tests du modèle documentaire (processus-double-sources-verite, Phase 5
§6, Bloc 5 de 08-plan-implementation.md) : association logique — un même
Document référencé par plusieurs entités, jamais dupliqué (décision du
commanditaire prise avant la Phase 5)."""

import uuid

from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_create_document_with_initial_link(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    fake_entity_id = str(uuid.uuid4())
    res = await client.post(
        "/api/v1/zylo-liquid/documents",
        json={
            "storageReference": "s3://bucket/bl-2026-001.pdf",
            "fileName": "bl-2026-001.pdf",
            "mimeType": "application/pdf",
            "linkedEntityType": "DeliveryDeclaration",
            "linkedEntityId": fake_entity_id,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    document_id = res.json()["id"]

    list_res = await client.get(f"/api/v1/zylo-liquid/documents/by-entity?linkedEntityType=DeliveryDeclaration&linkedEntityId={fake_entity_id}", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["id"] == document_id


async def test_same_document_linked_to_two_entities_never_duplicated(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Cœur de la décision « association logique » : un seul Document, deux
    DocumentLink — jamais une copie physique par entité liée."""
    headers = _headers(registered_user, zylo_liquid_organization)
    doc_res = await client.post(
        "/api/v1/zylo-liquid/documents",
        json={"storageReference": "s3://bucket/facture-partagee.pdf", "fileName": "facture-partagee.pdf"},
        headers=headers,
    )
    document_id = doc_res.json()["id"]

    entity_a_id = str(uuid.uuid4())
    entity_b_id = str(uuid.uuid4())

    link_a = await client.post(
        "/api/v1/zylo-liquid/document-links",
        json={"documentId": document_id, "linkedEntityType": "Sale", "linkedEntityId": entity_a_id},
        headers=headers,
    )
    assert link_a.status_code == 201, link_a.text

    link_b = await client.post(
        "/api/v1/zylo-liquid/document-links",
        json={"documentId": document_id, "linkedEntityType": "Receivable", "linkedEntityId": entity_b_id},
        headers=headers,
    )
    assert link_b.status_code == 201, link_b.text

    docs_for_a = await client.get(f"/api/v1/zylo-liquid/documents/by-entity?linkedEntityType=Sale&linkedEntityId={entity_a_id}", headers=headers)
    docs_for_b = await client.get(f"/api/v1/zylo-liquid/documents/by-entity?linkedEntityType=Receivable&linkedEntityId={entity_b_id}", headers=headers)
    assert docs_for_a.json()[0]["id"] == document_id
    assert docs_for_b.json()[0]["id"] == document_id
    # Même storageReference des deux côtés — bien le même fichier physique, pas une copie.
    assert docs_for_a.json()[0]["storageReference"] == docs_for_b.json()[0]["storageReference"]


async def test_duplicate_link_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    doc_res = await client.post(
        "/api/v1/zylo-liquid/documents", json={"storageReference": "s3://bucket/x.pdf", "fileName": "x.pdf"}, headers=headers
    )
    document_id = doc_res.json()["id"]
    entity_id = str(uuid.uuid4())

    first = await client.post(
        "/api/v1/zylo-liquid/document-links", json={"documentId": document_id, "linkedEntityType": "Sale", "linkedEntityId": entity_id}, headers=headers
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/zylo-liquid/document-links", json={"documentId": document_id, "linkedEntityType": "Sale", "linkedEntityId": entity_id}, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "document_link_already_exists"
