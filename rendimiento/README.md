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
| `liga.py`, `modelo.py`, `plan.py`, `prediccion.py` | Cálculos, sin red ni base de datos. |
| `almacen.py` | Datos en disco en el PC y en Vercel Blob en la nube. |
| `vercel.json` | Rutas y recogida diaria. |

- **Recogida:** el cron corre a las 10:05 UTC: entre las 11:05 y las 11:59 en invierno y entre las 12:05 y las 12:59 en verano.
  El plan Hobby sólo garantiza una vez al día, dentro de esa hora. Con varios clanes, cada uno se recoge en su propia ejecución.
- **Quién ve qué:** leer es público para quien tenga la URL. El panel `/#admin` (clanes, cuentas ligadas, recogidas, clave de
  la API y contraseña) pide usuario y contraseña; de inicio son `admin` / `admin`. Lo que se guarda en el panel manda sobre las variables.
- **Datos en directo:** la guerra en juego se pide a la API al abrir Predicciones y cada minuto. Lo demás es de la última recogida.
- **Cuota:** Blob gratuito tiene límites mensuales. Si se superan, Vercel corta el acceso al almacén hasta el mes siguiente.

**Jugadores y cuentas.** En *Resumen → Jugadores y sus cuentas* arrastras cada cuenta a su jugador. El jugador lleva la media de
sus cuentas con guerras (las cuentas sin guerras no bajan la media), los ataques y las estrellas se suman, y cada cuenta conserva
sus KPIs. Quien no esté en ningún grupo cuenta como jugador de una sola cuenta, así que los miembros nuevos entran solos.

## Varios clanes

En Admin se añaden y se quitan clanes; cada uno sale como pestaña arriba y las subpestañas no cambian. Cada clan tiene su propia base (`clan.db` el primero; `clan.db.<tag>` en el PC y `clan/<tag>.db` en Blob los demás), así dos recogidas no se pisan y los datos no se mezclan. La lista está en `clans` dentro de los ajustes; los ajustes antiguos con un solo `clan_tag` siguen valiendo. Quitar un clan lo pasa a `clans_off`: sus datos se conservan y vuelven si se añade otra vez. El alta se valida con la API oficial, porque ClashKing solo conoce los clanes que sigue. La petición lleva `?clan=<tag>` y `clan.use_clan` lo fija para todo lo que venga después.

## Predicciones

Pestaña que se adapta a lo que juega el clan: liga, guerra normal o nada (`mode` en `escenarios_view`). El cálculo está en `liga.py`, sin red ni base de datos; `clan.py` baja los datos en cada recogida (las guerras terminadas no se vuelven a pedir), calcula y guarda el resultado, así que abrir la web no gasta nada.

- **Asegurado y descartado:** `rank_bounds` calcula el mejor y el peor final posibles. Nunca puede marcar como seguro algo que no lo es: `tests/test_liga.py` lo compara con todos los resultados posibles de ligas pequeñas, también con guerras a medias.
- **% de pleno:** `modelo.py` se entrena en cada recogida con los ataques de la liga y el historial de todos los inscritos, propios y rivales. Da el reparto de estrellas de cada cuenta contra cada aldea. Elige solo cuánta memoria usar y cuánto pesa cada jugador, y mide su acierto sobre ataques que no ha visto.
- **Plan de ataque:** `plan.py` busca el reparto con más plenos esperados sin atacar por encima del propio puesto. Quien se queda sin aldea queda de reserva para rematar.
- **Alternativa:** el mismo cálculo dejando subir si el conjunto gana. Cada subida debe ganar más que el error medio del modelo, y solo se dice que sale más rentable si las dos versiones, jugadas 1.500 veces, se diferencian más que el azar. Se elige por ronda, y la matriz y los mensajes del chat la siguen.
- **Guerra normal:** se trata como una liga de dos clanes, con dos ataques por cuenta. Viene de la API oficial, porque ClashKing puede no seguir ese clan. Si termina entre dos recogidas y ya no se ve, se cierra con el marcador del registro del clan y queda marcada como parcial.
- **Previsto y real:** `prediccion.py` predice cada guerra una sola vez con un modelo entrenado solo con lo terminado antes de que empezara, y lo guarda en `battles`. Así la comparación no hace trampa. `Frozen` conserva lo necesario para seguir la guerra en directo sin numpy ni entrenar (`/api/vivo`).
- **Probabilidades:** `simulate` juega cada guerra pendiente con esos porcentajes, la asistencia de cada cuenta, la puntería de cada clan y días buenos y malos, y combina miles de finales.
- **Avance:** los cálculos corren en la recogida, nunca al abrir la web. `clan.Progress` publica la fase y el % en `clan/progreso.json` y la web lo enseña a cualquiera que la tenga abierta, también si lo lanzó el cron.
- **Datos:** la memoria de ataques y las aldeas se guardan en `book`, `war_use` y `village`, y sobreviven a los cambios de clan. La primera recogida de una liga tarda unos 2 minutos; las demás, unos 20 segundos.
- **Cupos de ascenso y descenso:** la API no los da y Supercell no publica una tabla actual. Por defecto 2 y 2; se cambian en Admin por clan.
- **Requiere** la clave de la API oficial: los grupos de liga no están en ClashKing.

Pruebas: `python tests/test_liga.py`.
