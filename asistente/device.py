"""Manos y ojos crudos: ADB (capturas, toques, deslizar, zoom) y colores de píxel."""
import io
import subprocess
import time

from PIL import Image

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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

    def zoom_out(self, times=2):
        """Pellizco con dos dedos en 'BlueStacks Virtual Touch' (multitáctil tipo A)."""
        d, cy, cmds = "/dev/input/event4", 16383, []
        for i in range(7):
            a = 5898 + (13762 - 5898) * i // 6
            b = 26869 - (26869 - 19005) * i // 6
            cmds += [f"sendevent {d} 3 53 {a}", f"sendevent {d} 3 54 {cy}", f"sendevent {d} 0 2 0",
                     f"sendevent {d} 3 53 {b}", f"sendevent {d} 3 54 {cy}", f"sendevent {d} 0 2 0",
                     f"sendevent {d} 0 0 0"]
        cmds += [f"sendevent {d} 0 2 0", f"sendevent {d} 0 0 0"]
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
