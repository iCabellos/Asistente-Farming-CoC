"""Descarga de la wiki de Clash of Clans (Fandom) las imágenes de referencia para las plantillas:
edificios por nivel (almacenes, recolectores, defensas, ayuntamiento) y retratos (Avatar_*) de tropas, héroes,
hechizos y máquinas de asedio. Se guardan en asistente/ref/. Uso: python ref_descargar.py"""
import json
import subprocess
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://clashofclans.fandom.com/api.php"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = Path(__file__).resolve().parent / "ref"

BUILDINGS = {
    "almacenes": ["Gold_Storage", "Elixir_Storage", "Dark_Elixir_Storage", "Gold_Mine", "Elixir_Collector",
                  "Dark_Elixir_Drill", "Town_Hall"],
    "defensas": ["Air_Defense", "Inferno_Tower", "X-Bow", "Eagle_Artillery", "Scattershot", "Archer_Tower",
                 "Cannon", "Wizard_Tower", "Mortar", "Hidden_Tesla", "Bomb_Tower", "Air_Sweeper", "Monolith",
                 "Spell_Tower", "Firespitter", "Multi-Archer_Tower", "Ricochet_Cannon", "Multi-Gear_Tower"],
}


def api(**params):
    params.update(format="json", action="query")
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def list_images(prefix):
    out, cont = [], {}
    while True:
        d = api(list="allimages", aiprefix=prefix, ailimit=500, **cont)
        out += d["query"]["allimages"]
        if "continue" not in d:
            return out
        cont = {"aicontinue": d["continue"]["aicontinue"]}


def fetch(url, dst):
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    # con curl (autorizado por el usuario 13-nov): urllib recibe 403 aunque lleve la misma cabecera
    r = subprocess.run(["curl", "-s", "-f", "-L", "-A", UA["User-Agent"], "-o", str(dst), url],
                       capture_output=True, timeout=60)
    time.sleep(0.15)                                   # sin prisa: no cargar la wiki
    if r.returncode != 0:
        dst.unlink(missing_ok=True)
        print("fallo", dst.name, r.returncode)
        return False
    return True


def main():
    n = 0
    for cat, prefixes in BUILDINGS.items():
        for pre in prefixes:
            pat = re.compile(rf"^{re.escape(pre)}(\d+)([A-Z]?)\.png$")
            for im in list_images(pre):
                m = pat.match(im["name"])
                if m:
                    n += fetch(im["url"], OUT / cat / im["name"])
    skip = re.compile(r"pre_|Background|_old|\(old\)|Clan_Symbol|^Avatar_\d|vfl", re.I)
    for im in list_images("Avatar_"):
        name = im["name"]
        if name.lower().endswith(".png") and not skip.search(name):
            n += fetch(im["url"], OUT / "avatar" / name)
    print("descargadas", n)


if __name__ == "__main__":
    main()
