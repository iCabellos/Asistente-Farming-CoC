"""Manos y ojos crudos: ADB (capturas, toques, deslizar, zoom) y colores de píxel."""
import io
import re
import subprocess
import time

from PIL import Image

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# Valores de BlueStacks Pie 64-bit, por si no se puede detectar la pantalla táctil.
FALLBACK_TOUCH = {"path": "/dev/input/event4", "name": "", "max_x": 32767, "max_y": 32767, "slots": False}


def parse_touch(text):
    """Saca de `getevent -lp` el dispositivo multitáctil. Prefiere el táctil virtual de BlueStacks."""
    devices, cur = [], None
    for line in text.splitlines():
        if m := re.match(r"add device \d+: (\S+)", line):
            cur = {"path": m[1], "name": "", "max_x": None, "max_y": None, "slots": False}
            devices.append(cur)
        elif cur is None:
            continue
        elif m := re.search(r'name:\s+"(.*)"', line):
            cur["name"] = m[1]
        elif m := re.search(r"ABS_MT_POSITION_X\s*:.*max (\d+)", line):
            cur["max_x"] = int(m[1])
        elif m := re.search(r"ABS_MT_POSITION_Y\s*:.*max (\d+)", line):
            cur["max_y"] = int(m[1])
        elif "ABS_MT_SLOT" in line:
            cur["slots"] = True
    found = [d for d in devices if d["max_x"] and d["max_y"]]
    found.sort(key=lambda d: "touch" not in d["name"].lower())
    return found[0] if found else None


def pinch_commands(t):
    """Dos dedos que se juntan en horizontal, en 7 pasos, en la escala del dispositivo.
    Hay dos protocolos multitáctiles: sin ranuras (tipo A) y con ranuras (tipo B)."""
    d, sx, cy = t["path"], t["max_x"] / 32767, t["max_y"] * 16383 // 32767
    cmds = []
    for i in range(7):
        a = int((5898 + (13762 - 5898) * i // 6) * sx)
        b = int((26869 - (26869 - 19005) * i // 6) * sx)
        if t["slots"]:
            for slot, x in ((0, a), (1, b)):
                cmds.append(f"sendevent {d} 3 47 {slot}")
                if i == 0:
                    cmds.append(f"sendevent {d} 3 57 {slot + 1}")
                cmds += [f"sendevent {d} 3 53 {x}", f"sendevent {d} 3 54 {cy}"]
            cmds.append(f"sendevent {d} 0 0 0")
        else:
            cmds += [f"sendevent {d} 3 53 {a}", f"sendevent {d} 3 54 {cy}", f"sendevent {d} 0 2 0",
                     f"sendevent {d} 3 53 {b}", f"sendevent {d} 3 54 {cy}", f"sendevent {d} 0 2 0",
                     f"sendevent {d} 0 0 0"]
    if t["slots"]:
        for slot in (0, 1):
            cmds += [f"sendevent {d} 3 47 {slot}", f"sendevent {d} 3 57 4294967295"]
        return cmds + [f"sendevent {d} 0 0 0"]
    return cmds + [f"sendevent {d} 0 2 0", f"sendevent {d} 0 0 0"]


class Device:
    def __init__(self, adb, serial):
        self.adb, self.serial = adb, serial

    def _run(self, *args, binary=False, timeout=30):
        r = subprocess.run([self.adb, "-s", self.serial, *map(str, args)], capture_output=True,
                           timeout=timeout, creationflags=NO_WINDOW)
        return r.stdout if binary else r.stdout.decode(errors="ignore")

    def connect(self):
        subprocess.run([self.adb, "connect", self.serial], capture_output=True, timeout=10, creationflags=NO_WINDOW)

    def shot(self) -> Image.Image:
        for _ in range(3):
            data = self._run("exec-out", "screencap", "-p", binary=True)
            if data:
                return Image.open(io.BytesIO(data)).convert("RGB")
            self.connect()
            time.sleep(2)
        raise RuntimeError("no hay captura del emulador")

    def shell(self, cmd):
        return self._run("shell", cmd)

    def tap(self, x, y, wait=0.0):
        self.shell(f"input tap {int(x)} {int(y)}")
        if wait:
            time.sleep(wait)

    def taps(self, pts):
        if pts:
            self.shell(" ; ".join(f"input tap {int(x)} {int(y)}" for x, y in pts))

    def swipe(self, x1, y1, x2, y2, ms=500, wait=0.0):
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {ms}")
        if wait:
            time.sleep(wait)

    def back(self, wait=1.0):
        self.shell("input keyevent 4")
        time.sleep(wait)

    def touch(self):
        """Pantalla táctil de este emulador. Se busca una vez: su número cambia entre instalaciones."""
        if not hasattr(self, "_touch"):
            self._touch = parse_touch(self.shell("getevent -lp")) or dict(FALLBACK_TOUCH)
        return self._touch

    def zoom_out(self, times=2):
        """Pellizco con dos dedos, escrito directamente en la pantalla táctil."""
        cmds = pinch_commands(self.touch())
        for _ in range(times):
            self.shell(" ; ".join(cmds))
        time.sleep(0.8)

    def launch_game(self):
        self.shell("monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1")

    def foreground(self):
        out = self.shell("dumpsys window")
        return next((l for l in out.splitlines() if "mCurrentFocus" in l), "")


def color(img, x, y, r=4):
    """Color medio de un cuadradito alrededor de (x, y)."""
    box = img.crop((x - r, y - r, x + r, y + r)).resize((1, 1))
    return box.getpixel((0, 0))


def is_yellow(c):   # botón Batalla de la aldea
    return c[0] > 180 and c[1] > 130 and c[2] < 100 and c[0] - c[2] > 120   # el botón brilla (animado)


def is_orange(c):   # botón Siguiente de la búsqueda
    return c[0] > 215 and 95 < c[1] < 200 and c[2] < 90


def is_red(c):      # Terminar batalla / Rendirse
    return c[0] > 190 and c[1] < 110 and c[2] < 110


def is_green(c):    # Volver (resultado), Enviar…
    return c[1] > 180 and c[0] < 190 and c[2] < 120


def is_grey(c):     # casilla de tropa agotada
    return max(c) - min(c) < 25
