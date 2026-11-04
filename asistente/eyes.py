"""El LLM sólo LEE la pantalla (preguntas cortas con respuesta JSON). No decide nada."""
import base64
import io
import time
import json
import re

import httpx


class Eyes:
    def __init__(self, host, model):
        self.host, self.model = host.rstrip("/"), model

    def ask(self, img, question, max_side=1280):
        if max(img.size) > max_side:
            k = max_side / max(img.size)
            img = img.resize((int(img.width * k), int(img.height * k)))
        self.sent = img.size          # qwen2.5-VL da coordenadas en píxeles de ESTA imagen
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        payload = {
            "model": self.model, "stream": False, "format": "json", "keep_alive": "2h",
            "options": {"temperature": 0, "num_predict": 900, "num_ctx": 4096},
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
        crop = shot.crop((0, 95, 460, 300)).resize((920, 410))
        d = self.ask(crop, 'Hay tres números: oro (moneda amarilla), elixir (gota rosa) y elixir oscuro (gota negra). '
                           'Responde {"gold": int, "elixir": int, "dark": int} (sin espacios ni puntos en los números).')
        return {k: self._num(d.get(k)) for k in ("gold", "elixir", "dark")}

    def my_resources(self, shot):
        """Recursos propios (arriba a la derecha)."""
        crop = shot.crop((1480, 25, 1900, 235)).resize((840, 420))
        d = self.ask(crop, 'Hay tres barras con números: oro (arriba), elixir (medio) y elixir oscuro (abajo). '
                           'Responde {"gold": int, "elixir": int, "dark": int} (sin espacios en los números).')
        out = {k: self._num(d.get(k)) for k in ("gold", "elixir", "dark")}
        if out.get("dark") and out["dark"] > 600000:          # el oscuro nunca pasa de ~500k
            out["dark"] = None
        return out

    def battle_result(self, shot):
        """Pantalla de resultado: botín conseguido, estrellas y % de daño."""
        crop = shot.crop((560, 30, 1360, 900)).resize((800, 870))
        d = self.ask(crop, 'Pantalla de fin de batalla de Clash of Clans. Lee el porcentaje de "Daño total", '
                           'cuántas estrellas están encendidas (0-3) y los tres números bajo "Has conseguido": '
                           'oro (moneda), elixir (gota rosa) y elixir oscuro (gota negra; 0 si no aparece). '
                           'Responde {"pct": int, "stars": int, "gold": int, "elixir": int, "dark": int} '
                           '(números sin espacios ni puntos).')
        return {k: self._num(d.get(k)) for k in ("pct", "stars", "gold", "elixir", "dark")}

    def card_count(self, shot, x_left):
        """Número «xN» de una carta de la barra de batalla (1 si no lleva número)."""
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

    def best_side(self, shot):
        d = self.ask(shot, 'Base enemiga vista desde arriba. ¿En qué lado hay más ALMACENES de oro/elixir '
                           '(depósitos grandes) cerca del borde? Responde {"side": "UL"|"UR"|"LL"|"LR"} '
                           '(UL arriba-izquierda, UR arriba-derecha, LL abajo-izquierda, LR abajo-derecha).')
        s = str(d.get("side", "UL")).upper()
        return s if s in ("UL", "UR", "LL", "LR") else "UL"

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
        """Burbujas de recursos listos para recoger (moneda, gota rosa, gota negra sobre fondo blanco)."""
        d = self.ask(shot, 'Vista de una aldea de Clash of Clans. Lista TODAS las burbujas blancas pequeñas con una '
                           'moneda dorada, una gota rosa o una gota negra encima de colectores, minas o taladros. '
                           'Responde {"bubbles": [{"x": int, "y": int}]} ' + self._coords_hint(shot) +
                           ', o {"bubbles": []}.')
        out = []
        for b in d.get("bubbles") or []:
            try:
                out.append(self._px(b["x"], b["y"], shot.size))
            except (KeyError, TypeError, ValueError):
                pass
        return out

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
