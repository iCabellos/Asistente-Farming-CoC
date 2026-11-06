"""Comprueba que el zoom out funciona en este emulador. Lo lanza probar_zoom.bat.

Hay que tener el juego abierto en la aldea, con el zoom acercado, y el asistente detenido.
Deja antes.png y despues.png en esta carpeta para poder compararlas.
"""
import json
from pathlib import Path

from PIL import ImageChops, ImageStat

from device import Device, parse_touch

HERE = Path(__file__).parent


def main():
    enabled = (HERE / "ENABLED").exists()
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    dev = Device(cfg.get("adb", "adb"), cfg.get("serial", "127.0.0.1:5555"))
    dev.connect()
    if enabled:
        print("AVISO: el asistente está activado. Detenlo antes de probar, o se pisarán los toques.\n")

    size = dev.shell("wm size").strip()
    version = dev.shell("getprop ro.build.version.release").strip()
    print(f"Android {version} · {size}")
    if "1920x1080" not in size and "Override size: 1920x1080" not in size:
        print("MAL: la resolución debe ser 1920x1080. Cámbiala en Ajustes de BlueStacks > Pantalla.")
        print("     Sin eso, el asistente toca en sitios equivocados aunque el zoom funcione.")

    if "input" not in dev.shell("id"):
        print("MAL: ADB no tiene permiso para escribir toques. Prueba otra instancia Pie 64-bit.")

    raw = dev.shell("getevent -lp")
    touch = parse_touch(raw)
    if not touch:
        print("MAL: no encuentro la pantalla táctil. Pasa este listado a quien te ayude:\n")
        print(raw)
        return
    print(f"Táctil: {touch['path']} «{touch['name']}» · rango {touch['max_x']}x{touch['max_y']} · "
          f"protocolo {'B' if touch['slots'] else 'A'}")

    antes = dev.shot()
    dev.zoom_out(3)
    despues = dev.shot()
    antes.save(HERE / "antes.png")
    despues.save(HERE / "despues.png")
    cambio = sum(ImageStat.Stat(ImageChops.difference(antes, despues)).mean) / 3
    print(f"\nCambio en pantalla: {cambio:.1f}")
    if cambio > 3:
        print("BIEN: la imagen ha cambiado. Mira antes.png y despues.png: la aldea debe verse más pequeña.")
    else:
        print("La imagen casi no ha cambiado. Una de dos:")
        print(" - ya estaba al mínimo: acerca con Ctrl + rueda del ratón y repite la prueba;")
        print(" - el pellizco no llega: pasa este texto completo a quien te ayude.")


if __name__ == "__main__":
    main()
