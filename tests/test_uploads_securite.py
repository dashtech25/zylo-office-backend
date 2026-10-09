"""Uploads sécurisés (T-014) : liste blanche par contenu, lecture bornée,
nom généré côté serveur, téléchargement forcé hors images et PDF, limites
d'import/export et appartenance organisationnelle.

Intention : chaque test vérifie un comportement de sécurité précis, sur le
point d'entrée HTTP réel (pas seulement sur les fonctions utilitaires)."""

import io
import os
import uuid

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from starlette.datastructures import UploadFile

from app.shared import storage_router
from app.shared.storage import get_storage_backend

PDF_OK = b"%PDF-1.4\n% contenu de test\n%%EOF\n"
PNG_OK = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_OK = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP_OK = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 16
HTML_ACTIF = b"<!doctype html><html><body><script>alert(document.domain)</script></body></html>"
SVG_ACTIF = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>'


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _upload(client: AsyncClient, headers: dict, name: str, content: bytes, content_type: str):
    return await client.post("/api/v1/storage/upload", files={"file": (name, content, content_type)}, headers=headers)


# ---- Liste blanche et détection par contenu ----


async def test_html_renomme_en_png_est_refuse(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Un HTML actif déguisé en image est refusé : la détection porte sur les octets, pas sur le nom ni sur le Content-Type."""
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "photo.png", HTML_ACTIF, "image/png")
    assert res.status_code == 415, res.text


async def test_svg_est_refuse(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "logo.svg", SVG_ACTIF, "image/svg+xml")
    assert res.status_code == 415, res.text


async def test_html_declare_pdf_est_refuse(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "rapport.pdf", HTML_ACTIF, "application/pdf")
    assert res.status_code == 415, res.text


async def test_pdf_valide_est_accepte_avec_nom_genere(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Un PDF valide passe. La référence de stockage est générée côté serveur : elle ne contient pas le nom fourni."""
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "rapport client.pdf", PDF_OK, "application/pdf")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mimeType"] == "application/pdf"
    assert body["storageReference"].endswith(".pdf")
    assert "rapport" not in body["storageReference"]


@pytest.mark.parametrize(
    ("content", "expected_ext", "expected_mime"),
    [(PNG_OK, ".png", "image/png"), (JPEG_OK, ".jpg", "image/jpeg"), (WEBP_OK, ".webp", "image/webp")],
)
async def test_extension_reecrite_selon_le_contenu_detecte(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, content, expected_ext, expected_mime
):
    """Mauvais magic bytes vs extension : le fichier PNG nommé `.pdf` est stocké en `.png`, type réel."""
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "trompeur.pdf", content, "application/pdf")
    assert res.status_code == 200, res.text
    assert res.json()["storageReference"].endswith(expected_ext)
    assert res.json()["mimeType"] == expected_mime


async def test_nom_malveillant_ne_sort_pas_du_repertoire(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Nom `../../etc/passwd.pdf` : la référence n'a ni séparateur ni `..`, et le nom renvoyé est réduit à son nom de base."""
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "../../etc/passwd.pdf", PDF_OK, "application/pdf")
    assert res.status_code == 200, res.text
    body = res.json()
    assert ".." not in body["storageReference"]
    assert "/" not in body["storageReference"] and "\\" not in body["storageReference"]
    assert body["fileName"] == "passwd.pdf"
    assert os.path.exists(os.path.join(get_storage_backend()._root, body["storageReference"]))


# ---- Taille et lecture bornée ----


async def test_fichier_trop_volumineux_est_refuse_sans_lecture_complete(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch
):
    """Un fichier de 26 Mo (au-delà des 25 Mo) est refusé en 413. Le serveur ne lit jamais plus de MAX+1 octets."""
    maximum = storage_router.MAX_UPLOAD_BYTES
    lus: list[int] = []
    original_read = UploadFile.read

    async def espion(self, size=-1):
        assert size != -1, "lecture sans borne interdite"
        data = await original_read(self, size)
        lus.append(len(data))
        return data

    monkeypatch.setattr(UploadFile, "read", espion)
    gros = PDF_OK + b"\x00" * (maximum + 1024 * 1024 - len(PDF_OK))
    res = await _upload(client, _headers(registered_user, zylo_liquid_organization), "gros.pdf", gros, "application/pdf")
    assert res.status_code == 413, res.text
    assert sum(lus) <= maximum + 1


# ---- Organisation : l'upload exige l'appartenance ----


async def test_upload_dans_une_organisation_etrangere_est_refuse(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Un utilisateur ne peut pas écrire dans le préfixe d'une organisation dont il n'est pas membre."""
    autre = await _creer_utilisateur(client)
    autre_org = await _creer_organisation(client, autre)
    res = await _upload(client, _headers(registered_user, autre_org), "x.pdf", PDF_OK, "application/pdf")
    assert res.status_code == 403, res.text


# ---- Téléchargement : en-têtes et type forcé ----


async def test_pdf_servi_en_inline_avec_nosniff_et_csp_sandbox(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    upload = await _upload(client, _headers(registered_user, zylo_liquid_organization), "a.pdf", PDF_OK, "application/pdf")
    ref = upload.json()["storageReference"]
    url = get_storage_backend().get_download_url(ref)
    res = await client.get(url)
    assert res.status_code == 200
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in res.headers["content-security-policy"]
    assert res.headers["content-disposition"].startswith("inline")
    assert res.headers["content-type"].startswith("application/pdf")


async def test_fichier_existant_de_type_actif_servi_en_attachment(client: AsyncClient):
    """Fichier déjà stocké avec une extension active (fixture) : jamais servi inline, type neutre, nosniff."""
    backend = get_storage_backend()
    ref = backend.upload(HTML_ACTIF, "legacy.html", uuid.uuid4())
    url = backend.get_download_url(ref)
    res = await client.get(url)
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in res.headers["content-security-policy"]
    assert not res.headers["content-type"].startswith("text/html")


async def test_svg_existant_servi_en_attachment(client: AsyncClient):
    backend = get_storage_backend()
    ref = backend.upload(SVG_ACTIF, "vieux.svg", uuid.uuid4())
    res = await client.get(backend.get_download_url(ref))
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("attachment")
    assert not res.headers["content-type"].startswith("image/svg")


# ---- Import et export : limites de taille, lignes et colonnes ----


async def test_import_xlsx_au_dela_de_la_limite_d_octets_est_refuse(client: AsyncClient, registered_user: dict):
    gros = b"PK" + b"\x00" * (6 * 1024 * 1024)
    res = await client.post(
        "/api/v1/import/xlsx",
        files={"file": ("gros.xlsx", gros, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code == 413, res.text


async def test_import_xlsx_au_dela_du_nombre_de_lignes_est_refuse(client: AsyncClient, registered_user: dict):
    classeur = Workbook()
    feuille = classeur.active
    for _ in range(10_001):
        feuille.append(["a"])
    tampon = io.BytesIO()
    classeur.save(tampon)
    res = await client.post(
        "/api/v1/import/xlsx",
        files={"file": ("lignes.xlsx", tampon.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code == 413, res.text


async def test_export_au_dela_du_nombre_de_lignes_est_refuse(client: AsyncClient, registered_user: dict):
    res = await client.post(
        "/api/v1/export/xlsx",
        json={"filename": "x", "headers": ["a"], "rows": [["1"]] * 10_001},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code == 413, res.text


# ---- Photo de profil : la référence doit appartenir à l'acteur ----


async def _creer_utilisateur(client: AsyncClient) -> dict:
    from tests.conftest import unique_email

    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    tokens = login.json()
    user = {"email": email, "password": password, "accessToken": tokens["accessToken"], "refreshToken": tokens["refreshToken"]}
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['accessToken']}"})
    user["id"] = me.json()["id"]
    return user


async def _creer_organisation(client: AsyncClient, user: dict) -> dict:
    headers = {"Authorization": f"Bearer {user['accessToken']}"}
    res = await client.post("/api/v1/organizations", json={"name": "Autre Org", "slug": f"autre-{uuid.uuid4().hex[:8]}"}, headers=headers)
    return res.json()


async def test_photo_de_profil_de_son_organisation_acceptee(client: AsyncClient, registered_user: dict, organization: dict):
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"})
    upload = await _upload(client, _headers(registered_user, organization), "moi.png", PNG_OK, "image/png")
    ref = upload.json()["storageReference"]
    res = await client.patch(
        f"/api/v1/users/{me.json()['id']}",
        json={"photoStorageReference": ref},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code == 200, res.text


async def test_photo_de_profil_d_une_autre_organisation_refusee(client: AsyncClient, registered_user: dict, organization: dict):
    """Référence issue d'une organisation dont l'acteur n'est pas membre : refusée à l'écriture."""
    autre = await _creer_utilisateur(client)
    autre_org = await _creer_organisation(client, autre)
    upload = await _upload(client, _headers(autre, autre_org), "pas-a-moi.png", PNG_OK, "image/png")
    ref = upload.json()["storageReference"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {registered_user['accessToken']}"})
    res = await client.patch(
        f"/api/v1/users/{me.json()['id']}",
        json={"photoStorageReference": ref},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code == 403, res.text
