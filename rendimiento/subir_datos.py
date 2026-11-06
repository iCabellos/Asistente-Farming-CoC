"""Sube a Vercel Blob lo que ya tienes en el PC: el histórico, los jugadores y cuáles son tus cuentas.
Se usa una sola vez. Sin esto la web empezaría sólo con lo que ClashKing conserve.

  pip install vercel
  set BLOB_READ_WRITE_TOKEN=...      (Vercel → Storage → tu almacén)
  python subir_datos.py
"""
import json
import os
import sys

import almacen
import clan

if __name__ == "__main__":
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        sys.exit("Falta BLOB_READ_WRITE_TOKEN.")
    if not almacen.DB.exists():
        sys.exit(f"No encuentro {almacen.DB}.")
    c = clan.db()
    try:
        ajustes = {"groups": clan.account_groups(c), "own_names": sorted(clan.own_names())}   # nunca la clave de la API
    finally:
        c.close()
    almacen.subir(almacen.BLOB_DB, almacen.DB.read_bytes(), "application/octet-stream")
    almacen.subir(almacen.BLOB_AJUSTES, json.dumps(ajustes, ensure_ascii=False).encode("utf-8"), "application/json")
    print(f"Subido: {almacen.DB.stat().st_size // 1024} KB de histórico y {len(ajustes['groups'])} jugadores agrupados.")
