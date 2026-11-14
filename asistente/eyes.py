"""El LLM sólo LEE la pantalla (preguntas cortas con respuesta JSON). No decide nada.

Las cifras (recursos, botín, precios, «xN» de las cartas, constructores, títulos de muro, resultado) se leen
primero con ocr.py (plantillas de la fuente del juego, en la CPU, milisegundos). Sólo si el OCR no está seguro
se pregunta al modelo, exactamente como antes."""
import base64
import io
import time
import json
import re
from collections import Counter
from pathlib import Path

import httpx

try:
    import ocr
except Exception:                     # sin OCR (falta numpy/cv2 o las plantillas): todo va al modelo, como antes
    ocr = None


class Eyes:
    def __init__(self, host, model, keep_alive="5m"):
        self.host, self.model = host.rstrip("/"), model
        # el modelo se descarga solo tras `keep_alive` sin preguntas (libera ~7 GB de VRAM y la RAM de su caché
        # de prompts); la siguiente pregunta lo vuelve a cargar (~10 s)
        self.keep_alive = keep_alive
        self.stats = Counter()        # lecturas: "ocr:<qué>" / "modelo:<qué>"

    def ocr(self, what, *args, **kw):
        """Lectura sin modelo (`ocr.<what>`); None si no hay OCR o no está seguro."""
        if ocr is None:
            return None
        try:
            r = getattr(ocr, what)(*args, **kw)
        except Exception as e:                # un fallo del OCR no debe pasar en silencio (QA): se apunta una vez
            r = None
            if what not in getattr(self, "_ocr_errors", set()):
                self._ocr_errors = getattr(self, "_ocr_errors", set()) | {what}
                print(time.strftime("%H:%M:%S"), f"WARN El OCR falló en {what}: {e!r} (paso al modelo)", flush=True)
        if r is not None:
            self.stats["ocr:" + what] += 1
        else:
            self.stats["dudas:" + what] += 1
        if r is None and what != "bubbles" and what != "card_count":
            # para revisar por qué no lo leyó (la última de cada tipo): asistente/ocr_fallos/<qué>.jpg
            # (JPEG: guardar el PNG entero costaba 0,35 s en mitad de la lectura)
            try:
                d = Path(__file__).parent / "ocr_fallos"
                d.mkdir(exist_ok=True)
                args[0].convert("RGB").save(d / f"{what}.jpg", quality=90)
            except Exception:
                pass
        return r

    def warm(self):
        """Carga el modelo sin preguntar nada (para que no tenga que cargarse en mitad de una batalla)."""
        try:
            httpx.post(f"{self.host}/api/generate", json={"model": self.model, "keep_alive": self.keep_alive,
                                                         "options": {"num_ctx": 4096}}, timeout=60)
        except httpx.HTTPError:
            pass

    def summary(self):
        """(lecturas sin modelo, preguntas al modelo, {lectura: veces que el OCR dudó y pasó al modelo})."""
        o = sum(v for k, v in self.stats.items() if k.startswith("ocr:"))
        m = sum(v for k, v in self.stats.items() if k.startswith("modelo"))
        return o, m, {k[6:]: v for k, v in self.stats.items() if k.startswith("dudas:")}

    def ask(self, img, question, max_side=1280, max_tokens=900):
        self.stats["modelo"] += 1
        if max(img.size) > max_side:
            k = max_side / max(img.size)
            img = img.resize((int(img.width * k), int(img.height * k)))
        self.sent = img.size          # qwen2.5-VL da coordenadas en píxeles de ESTA imagen
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        payload = {
            "model": self.model, "stream": False, "format": "json", "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": "Lees capturas de Clash of Clans. Respondes SOLO con el JSON pedido, sin inventar."},
                {"role": "user", "content": question, "images": [base64.b64encode(buf.getvalue()).decode()]},
            ],
        }
        for attempt in range(3):            # Ollama a veces da un 500 (salida JSON rota): se reintenta variando
            if attempt:
                payload["options"]["temperature"] = 0.3 * attempt
                payload.pop("format", None)  # sin gramática JSON; el JSON se rescata del texto
            try:
                r = httpx.post(f"{self.host}/api/chat", json=payload, timeout=120)
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                time.sleep(5)
        txt = r.json()["message"]["content"]
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        # respuesta cortada: rescata los objetos {"x":..,"y":..} completos que sí llegaron
        items = [{"x": int(a), "y": int(b)} for a, b in re.findall(r'"x"\s*:\s*(-?\d+)\s*,\s*"y"\s*:\s*(-?\d+)', txt)]
        return {"bubbles": items, "taps": items, "requests": items} if items else {}

    def _px(self, x, y, orig_size):
        """Pasa (x, y) en píxeles de la imagen enviada a píxeles de la imagen original."""
        sw, sh = self.sent
        return float(x) * orig_size[0] / sw, float(y) * orig_size[1] / sh

    def _coords_hint(self, img, max_side=1280):
        k = min(1.0, max_side / max(img.size))
        return f"en píxeles de la imagen ({int(img.width * k)}x{int(img.height * k)})"

    @staticmethod
    def _num(v):
        if isinstance(v, (int, float)):
            return int(v)
        digits = re.sub(r"\D", "", str(v or ""))
        return int(digits) if digits else None

    # ---------- preguntas concretas ----------
    def loot_available(self, shot):
        """Botín del rival (arriba a la izquierda en la búsqueda)."""
        r = self.ocr("loot", shot)
        if r is not None:
            return {"gold": r["gold"], "elixir": r["elixir"], "dark": r.get("dark") or 0}   # sin renglón de oscuro: 0
        crop = shot.crop((0, 95, 460, 300)).resize((920, 410))
        d = self.ask(crop, 'Hay tres números: oro (moneda amarilla), elixir (gota rosa) y elixir oscuro (gota negra). '
                           'Responde {"gold": int, "elixir": int, "dark": int} (sin espacios ni puntos en los números).')
        return {k: self._num(d.get(k)) for k in ("gold", "elixir", "dark")}

    def my_resources(self, shot):
        """Recursos propios (arriba a la derecha)."""
        out = self.ocr("my_resources", shot)
        if out is None:
            crop = shot.crop((1480, 25, 1900, 235)).resize((840, 420))
            d = self.ask(crop, 'Hay tres barras con números: oro (arriba), elixir (medio) y elixir oscuro (abajo). '
                               'Responde {"gold": int, "elixir": int, "dark": int} (sin espacios en los números).')
            out = {k: self._num(d.get(k)) for k in ("gold", "elixir", "dark")}
        if out.get("dark") and out["dark"] > 600000:          # el oscuro nunca pasa de ~500k
            out["dark"] = None
        return out

    def battle_result(self, shot):
        """Pantalla de resultado: botín conseguido, estrellas y % de daño."""
        r = self.ocr("battle_result", shot)          # las estrellas (None) las cuenta quien llama por píxeles
        if r is not None:
            return {k: r.get(k) for k in ("pct", "stars", "gold", "elixir", "dark")}
        crop = shot.crop((560, 30, 1360, 900)).resize((800, 870))
        d = self.ask(crop, 'Pantalla de fin de batalla de Clash of Clans. Lee el porcentaje de "Daño total", '
                           'cuántas estrellas están encendidas (0-3) y los tres números bajo "Has conseguido": '
                           'oro (moneda), elixir (gota rosa) y elixir oscuro (gota negra; 0 si no aparece). '
                           'Responde {"pct": int, "stars": int, "gold": int, "elixir": int, "dark": int} '
                           '(números sin espacios ni puntos).')
        return {k: self._num(d.get(k)) for k in ("pct", "stars", "gold", "elixir", "dark")}

    def card_count(self, shot, x_left):
        """Número «xN» de una carta de la barra de batalla (1 si no lleva número)."""
        n = self.ocr("card_count", shot, x_left)
        if n is not None:
            return n
        try:                                  # sin nada escrito (héroe, hechizo suelto): es 1, sin preguntar (QA)
            if ocr is not None and not ocr.card_has_text(shot, x_left):
                return 1
        except Exception:
            pass
        crop = shot.crop((x_left, 885, x_left + 140, 945)).resize((420, 180))
        d = self.ask(crop, 'Lee el número blanco que va después de la "x" (arriba a la derecha). '
                           'Responde {"n": N} con ese número; si no hay ninguna "x" con número, {"n": 1}.')
        n = self._num(d.get("n"))
        return n if n and 0 < n < 100 else None

    def village_name(self, shot):
        crop = shot.crop((0, 0, 520, 210)).resize((1040, 420))
        d = self.ask(crop, '¿Qué nombre de jugador aparece (texto blanco grande junto al icono de nivel)? '
                           'Responde {"name": "..."} o {"name": null}.')
        return str(d.get("name") or "")

    def army_bar(self, shot):
        """Casillas de la barra inferior de batalla con su tipo y cantidad."""
        crop = shot.crop((0, 885, 1920, 1080))
        d = self.ask(crop, 'Barra de tropas de una batalla de Clash of Clans. Lista cada casilla de izquierda a derecha '
                           'que NO esté en gris: {"slots": [{"x": centro horizontal 0-1000, "kind": "troop"|"hero"|"siege"|'
                           '"castle"|"spell", "count": int}]}. Héroes = retratos sin "x" número; castillo = escudo del '
                           'clan; hechizos = pociones/frascos; asedio = máquinas/dirigibles. count=1 si no hay número.')
        out = []
        for s in d.get("slots") or []:
            try:
                out.append({"x": int(float(s["x"]) * 1.92), "kind": str(s.get("kind", "troop")),
                            "count": max(1, int(self._num(s.get("count")) or 1))})
            except (KeyError, TypeError, ValueError):
                pass
        return sorted(out, key=lambda s: s["x"])

    def card_kind(self, shot, x_left, spells_def=(), spells_boost=()):
        """Qué es una carta de la barra de batalla que las plantillas no reconocen: "tropa", "heroe", "asedio",
        "hechizo_defensas", "hechizo_tropas" o "gastada". Se le pasa la lista de hechizos de cada función.
        Sin números de ejemplo en la pregunta."""
        crop = shot.crop((max(0, x_left - 5), 860, min(1920, x_left + 150), 1075)).resize((310, 430))
        d = self.ask(crop, 'Carta de la barra de batalla de Clash of Clans. ¿Qué es? Responde {"kind": '
                           '"tropa"|"heroe"|"asedio"|"hechizo_defensas"|"hechizo_tropas"|"gastada"}. '
                           f'"hechizo_defensas" = hechizo que se lanza sobre las defensas enemigas '
                           f'({", ".join(spells_def)}); "hechizo_tropas" = hechizo que se lanza sobre las '
                           f'propias tropas ({", ".join(spells_boost)}); "asedio" = máquina de asedio; '
                           '"gastada" si está gris o pone x0.', max_tokens=40)
        k = str(d.get("kind") or "").lower().replace("é", "e")
        return k if k in ("tropa", "heroe", "asedio", "hechizo_defensas", "hechizo_tropas", "gastada") else None

    def building_kind(self, tile):
        """Qué edificio hay en el centro de un recorte de la aldea enemiga (una pregunta por recorte: con
        cuadrículas de varios el modelo contesta lo mismo para todos). "oro"|"elixir"|"oscuro"|"mina"|"otro"."""
        d = self.ask(tile, 'Edificio de una aldea de Clash of Clans visto desde arriba. ¿Qué es el edificio del '
                           'centro? Responde {"tipo": "almacen_oro"|"almacen_elixir"|"almacen_oscuro"|'
                           '"mina_o_recolector"|"defensa"|"otro"}.', max_tokens=30)
        t = str(d.get("tipo") or "")
        return {"almacen_oro": "oro", "almacen_elixir": "elixir", "almacen_oscuro": "oscuro",
                "mina_o_recolector": "mina"}.get(t, "otro")

    def find(self, shot, what):
        """Centro (x, y) en píxeles de un elemento, o None."""
        d = self.ask(shot, f'Devuelve el centro de: {what}. Formato {{"x": int, "y": int}} {self._coords_hint(shot)}, '
                           f'o {{"x": null}} si NO se ve claramente.')
        x, y = d.get("x"), d.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            px, py = self._px(x, y, shot.size)
            if 0 <= px <= shot.width and 0 <= py <= shot.height:
                return px, py
        return None

    def resource_bubbles(self, shot):
        """Burbujas de recursos listos para recoger (moneda, gota rosa, gota negra sobre fondo blanco).
        Primero por píxeles (icono rodeado del fondo de la burbuja); si no sale ninguna, el modelo como antes, pero
        con la respuesta limitada (sin límite se iba a 900 tokens de coordenadas inventadas: ~13 s)."""
        # sólo por píxeles: el modelo no encontraba ni una de 19 y se inventaba coordenadas (tocaba al azar) y
        # además obligaba a cargarlo en frío (QA). Sin burbujas por píxeles = no hay ninguna.
        return self.ocr("bubbles", shot) or []

    def donation_requests(self, shot):
        crop = shot.crop((0, 0, 740, 1080))
        d = self.ask(crop, 'Panel del chat del clan. Busca peticiones de tropas con un botón verde "Donar". Responde '
                           '{"requests": [{"x": int, "y": int, "text": "lo que piden"}]} con el centro del botón Donar '
                           + self._coords_hint(crop) + ', o {"requests": []} si no hay ninguno.')
        out = []
        for r in d.get("requests") or []:
            try:
                x, y = self._px(r["x"], r["y"], crop.size)
                out.append((x, y, str(r.get("text", ""))))
            except (KeyError, TypeError, ValueError):
                pass
        return out

    def donation_taps(self, shot, request_text):
        d = self.ask(shot, f'Ventana de donación de Clash of Clans. La petición es: "{request_text}". Devuelve las '
                           'cartas de tropas/hechizos/asedios A COLOR (disponibles) que coinciden con lo pedido y cuántas '
                           'veces tocarlas: {"taps": [{"x": int, "y": int, "times": int}]} ' + self._coords_hint(shot) +
                           '. Nunca botones con gemas. Si nada coincide, {"taps": []}.')
        out = []
        for t in d.get("taps") or []:
            try:
                x, y = self._px(t["x"], t["y"], shot.size)
                out.append((x, y, max(1, min(5, int(t.get("times", 1))))))
            except (KeyError, TypeError, ValueError):
                pass
        return out

    def request_is_free(self, shot):
        crop = shot.crop((560, 960, 720, 1075)).resize((480, 345))
        d = self.ask(crop, 'Botón del castillo del clan para pedir tropas. ¿Muestra un número con una GEMA verde '
                           '(cuesta gemas / cuenta atrás)? Responde {"gems": true|false}.')
        return d.get("gems") is False

    def screen_kind(self, shot):
        d = self.ask(shot, 'Clasifica la pantalla: {"kind": "otro_dispositivo"|"cargando"|"popup"|"aldea"|"otro", '
                           '"close": {"x": int, "y": int}|null} (coordenadas ' + self._coords_hint(shot) + '). "otro_dispositivo" si dice que otro dispositivo se '
                           'ha conectado a la aldea. Para "popup" da la X roja de cerrar (NUNCA un botón con gemas ni de '
                           'comprar).')
        c = d.get("close") or {}
        pos = None
        if isinstance(c, dict) and isinstance(c.get("x"), (int, float)) and isinstance(c.get("y"), (int, float)):
            pos = self._px(c["x"], c["y"], shot.size)
            if not (0 <= pos[0] <= shot.width and 0 <= pos[1] <= shot.height):
                pos = None
        return str(d.get("kind", "otro")), pos
