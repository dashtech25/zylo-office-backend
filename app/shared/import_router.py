"""Analyse générique de fichiers tabulaires uploadés (XLSX) vers un tableau
de cellules texte — miroir en lecture de `export_router.py`. Réutilisable par
tout import de données tabulaires de l'app, pas seulement Zylo Liquid (P1-7,
audit module Stations 2026-09-16 : la table de calibration d'une cuve ne
pouvait être modifiée que par import CSV, jamais XLSX). Le fichier n'est
jamais persisté ni interprété métier ici — seule la structure ligne/colonne
est extraite ; c'est à l'appelant (ex. import de calibration) de valider et
d'interpréter les valeurs."""

import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from openpyxl import load_workbook
from pydantic import BaseModel

from app.core.security import get_current_user

import_router = APIRouter()

# T-014 (BCK-012) : limites d'import. Lecture bornée à MAX+1 octets, puis bornes de
# lignes et de colonnes : une feuille démesurée consomme mémoire et CPU du serveur.
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
MAX_IMPORT_COLUMNS = 100


class ParsedTable(BaseModel):
    rows: list[list[str]]


@import_router.post("/xlsx", response_model=ParsedTable, dependencies=[Depends(get_current_user)])
async def parse_xlsx(file: UploadFile) -> ParsedTable:
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Fichier XLSX trop volumineux (5 Mo maximum).")
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=422, detail="Fichier XLSX invalide ou corrompu.")
    sheet = workbook.active
    if sheet is None:
        return ParsedTable(rows=[])
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        if len(rows) >= MAX_IMPORT_ROWS:
            raise HTTPException(status_code=413, detail="Fichier XLSX au-delà de 10 000 lignes.")
        if len(row) > MAX_IMPORT_COLUMNS:
            raise HTTPException(status_code=413, detail="Fichier XLSX au-delà de 100 colonnes.")
        rows.append([("" if cell is None else str(cell)) for cell in row])
    return ParsedTable(rows=rows)
