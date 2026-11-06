# Rendimiento del clan

Publicada en https://coc-rendimiento-clan.vercel.app

Web con los KPIs del clan: resumen, miembros, guerras, ligas y fichas de cada cuenta y cada jugador. Es independiente del
asistente: una vez publicada no necesita BlueStacks ni el PC encendido.

## En tu PC

`Abrir rendimiento.bat` → http://localhost:8001. Usa `clan.db` y `clan.json` de esta carpeta.

## Publicar en Vercel

1. **Sube el repositorio a GitHub** e impórtalo en Vercel. En *Root Directory* pon `rendimiento`.
2. **Crea el almacén:** Storage → Blob → **Private**, y conéctalo al proyecto. Así aparece `BLOB_READ_WRITE_TOKEN`.
3. **Variables de entorno:** las de `.env.example`. La clave de Supercell debe estar creada con la IP `45.79.218.79`.
4. **Sube tu histórico** una vez, desde esta carpeta y con el token del paso 2:
   ```
   pip install vercel
   set BLOB_READ_WRITE_TOKEN=...
   python subir_datos.py
   ```
5. **Despliega** y abre `/#admin`. Entra con `admin` / `admin` y **cambia el acceso** en el momento: la web es pública.
6. **Apaga la recogida del PC** para no tener dos históricos: `schtasks /Delete /TN "CoC Asistente - Clan diario" /F`.

## Cómo funciona

| Pieza | Qué hace |
|---|---|
| `public/` | La web. Sin compilación. |
| `api/index.py` | La API; en Vercel, una sola función. |
| `clan.py` | Recogida, KPIs y vistas. |
| `almacen.py` | Datos en disco en el PC y en Vercel Blob en la nube. |
| `vercel.json` | Rutas y recogida diaria. |

- **Recogida:** el cron corre a las 10:05 UTC: entre las 11:05 y las 11:59 en invierno y entre las 12:05 y las 12:59 en verano.
  El plan Hobby sólo garantiza una vez al día, dentro de esa hora.
- **Quién ve qué:** leer es público para quien tenga la URL. El panel `/#admin` (cuentas ligadas, tag del clan, recogidas, clave de
  la API y contraseña) pide usuario y contraseña; de inicio son `admin` / `admin`. Lo que se guarda en el panel manda sobre las variables.
- **Datos en directo:** «en guerra» y las cuentas atrás son de la última recogida, no de este momento.
- **Cuota:** Blob gratuito tiene límites mensuales. Si se superan, Vercel corta el acceso al almacén hasta el mes siguiente.

**Jugadores y cuentas.** En *Resumen → Jugadores y sus cuentas* arrastras cada cuenta a su jugador. El jugador lleva la media de
sus cuentas con guerras (las cuentas sin guerras no bajan la media), los ataques y las estrellas se suman, y cada cuenta conserva
sus KPIs. Quien no esté en ningún grupo cuenta como jugador de una sola cuenta, así que los miembros nuevos entran solos.
