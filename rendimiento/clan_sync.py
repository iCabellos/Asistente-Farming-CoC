"""Recogida diaria de datos del clan. La lanza la tarea de Windows (ver programar_clan.ps1)."""
import sys

import clan

if __name__ == "__main__":
    code = 0
    for r in clan.clan_list():
        clan.use_clan(r["tag"])
        code = clan.daily() or code
    sys.exit(code)
