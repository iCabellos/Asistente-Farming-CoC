"""Control manual del emulador con las funciones del asistente. PARAR ANTES EL ASISTENTE (visor: Detener).
Uso: control.py <cmd> [args]   cmds: shot NAME [x0 y0 x1 y1] | tap X Y [NAME] | swipe X1 Y1 X2 Y2 [MS] |
     switch ACC | home | which | eval EXPR | ask NAME "pregunta" [x0 y0 x1 y1]
Las capturas van a asistente/capturas_control/."""
import sys
import time
from pathlib import Path

A = Path(__file__).resolve().parent
sys.path.insert(0, str(A))
import os
os.chdir(A)
import asistente as s  # noqa: E402

OUT = A / "capturas_control"
OUT.mkdir(exist_ok=True)


def save(name, box=None):
    img = s.dev.shot()
    img.save(OUT / f"{name}.png")
    if box:
        c = img.crop(box)
        c.save(OUT / f"{name}_crop.png")
    print("guardada", OUT / f"{name}.png")
    return img


cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "shot":
    save(args[0], tuple(map(int, args[1:5])) if len(args) >= 5 else None)
elif cmd == "tap":
    s.dev.tap(int(args[0]), int(args[1]), 1.5)
    if len(args) > 2:
        save(args[2])
elif cmd == "swipe":
    s.dev.swipe(*map(int, args[:4]), int(args[4]) if len(args) > 4 else 500, wait=1.5)
elif cmd == "switch":
    s.dev.connect()
    print(s.switch_to(args[0]))
elif cmd == "home":
    s.dev.connect()
    print(s.go_home())
elif cmd == "which":
    print(s.which_account())
elif cmd == "eval":
    print(eval(args[0], vars(s)))
elif cmd == "ask":
    img = s.dev.shot()
    box = tuple(map(int, args[2:6])) if len(args) >= 6 else None
    print(s.eyes.ask(img.crop(box) if box else img, args[1]))
    img.save(OUT / f"{args[0]}.png")
