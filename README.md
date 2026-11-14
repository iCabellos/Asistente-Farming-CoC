# ⚔️ CoC Asistente

Asistente que farmea **Clash of Clans** solo, en el emulador **BlueStacks** de tu PC, con varias cuentas en bucle:

- 🏰 **Llena los almacenes** de cada cuenta hasta el % que tú elijas (ataca bases con buen botín).
- 🌙 **Llena la aldea nocturna** (batallas de constructor).
- 🔨 **Mejora lo recomendado** en una cuenta pequeña, hasta el nivel de ayuntamiento que digas.
- 🤝 **Dona** lo que pidan en el clan y **pide tropas** siempre que puede.
- 👀 **Visor web** en `http://localhost:8000`: ves la pantalla en directo, lo que decide, el botín de cada ataque,
  los almacenes, y **ordenas la rutina arrastrando**.
- 🙈 Si entras tú en una cuenta desde el móvil, el asistente **se aparta** para no echarte.

Nunca gasta gemas ni martillos, nunca hace guerra ni batallas competitivas.

> ⚠️ **Aviso**: automatizar el juego va contra las condiciones de uso de Supercell y puede acabar en **baneo**.
> Úsalo bajo tu responsabilidad.

---

## ✅ Lo que necesitas

| | |
|---|---|
| Sistema | **Windows 10 u 11** |
| Memoria | **16 GB de RAM** (BlueStacks + el modelo de visión) |
| Disco | **~15 GB libres** |
| Pantalla del emulador | **1920 × 1080** (obligatorio: el asistente mide la pantalla en píxeles) |
| Idioma del juego | **Español** |

---

## 🚀 Instalación paso a paso (≈ 20 min)

### Paso 1 · BlueStacks (5 min)

1. Descarga e instala **BlueStacks 5** desde https://www.bluestacks.com
2. Abre el **Multi-instance Manager** (icono de capas) → **Nueva instancia** → **Nueva** → **Pie 64-bit** → Crear.
   *(si ya tienes una instancia Pie 64-bit, usa esa)*
3. Abre esa instancia → ⚙️ **Ajustes**:
   - **Pantalla** → Resolución **1920 × 1080** → Guardar.
   - **Avanzado** → activa **Android Debug Bridge (ADB)** → Guardar.
     Apunta el puerto que sale (normalmente `127.0.0.1:5555`).
4. Instala **Clash of Clans** desde Google Play dentro del emulador.
5. Entra en el juego y **vincula todas tus cuentas a Supercell ID** (Ajustes → Supercell ID).
   Comprueba que en *Ajustes → Cambiar de cuenta* salen todas.
6. Pon el juego en **Español** (Ajustes → Idioma).

### Paso 2 · Descargar el asistente (1 min)

- Con Git: `git clone https://github.com/TU_USUARIO/coc-asistente.git`
- Sin Git: botón verde **Code → Download ZIP** y descomprímelo (por ejemplo en el escritorio).

### Paso 3 · Instalar (10 min, casi todo esperar)

1. Entra en la carpeta y haz **doble clic en `instalar.bat`**.
2. Si Windows pregunta *«¿Permitir cambios?»* → **Sí** (instala Python, ADB y Ollama si no los tienes).
3. Espera a que salga **`LISTO`**. Descarga el modelo de visión (~6 GB), tarda según tu conexión.
4. Al acabar tienes en el escritorio **`Iniciar asistente`** y **`Detener asistente`**.

> Si el instalador acaba de instalar Python, ADB u Ollama por primera vez y luego falla,
> **ciérralo y vuelve a abrir `instalar.bat`** (Windows necesita refrescar las rutas).

**Comprueba la conexión**: con BlueStacks abierto, doble clic en **`probar_conexion.bat`**.
Debe salir `127.0.0.1:5555   device`. Si sale otra cosa → [Problemas frecuentes](#-problemas-frecuentes).

### Paso 4 · Tus cuentas (1 min)

Abre **`asistente\config.json`** con el Bloc de notas. **Sólo hace falta el nombre de tus aldeas**; con esto ya funciona:

```json
{ "accounts": ["MiAldea", "MiSegundaAldea"] }
```

El asistente llena los almacenes de cada cuenta, en bucle. Todo lo demás lo averigua solo o tiene un valor por defecto:
la capacidad de los almacenes la lee del juego, el botín mínimo sale de esa capacidad, y la tarjeta de cada cuenta en
Supercell ID la encuentra leyendo la lista (la primera vez; después guarda una plantilla y va al instante).

Si quieres afinar, cada cuenta admite estos campos (todos opcionales):

| Campo | Qué hace | Por defecto |
|---|---|---|
| `village_name` | nombre de la aldea **tal cual sale arriba a la izquierda** en el juego | el nombre de la cuenta |
| `switch_label` | nombre de la tarjeta en **Supercell ID**, sólo si quieres buscarla por ese nombre | `village_name` |
| `label` | cómo se ve en el visor | el nombre de la cuenta |
| `tasks` | qué hace esa cuenta si no escribes `"routine"`: `fill_storages`, `farm`, `builder_base`, `build`, `walls` | `["fill_storages"]` |
| `min_loot` | botín mínimo para atacar: `"auto"` o `{"gold": N, "elixir": N, "dark": N, "mode": "gold_or_elixir"}` (lo que falte, automático) | `"auto"` |
| `max_searches` | bases que mira antes de atacar la que haya | `25` |
| `full_ratio`, `dark_full_ratio`, `builder_full_ratio` | hasta qué parte llenar (también desde el visor) | `0.9`, `0.5`, `0.9` |
| `farm_focus` | sólo cuenta estos recursos: `["gold"]`, `["dark"]`… | todos |
| `auto_build`, `auto_build_until_th` | mejora sola lo recomendado hasta ese ayuntamiento | `false`, `10` |
| `donor` | la cuenta en la que se queda mientras descansa, para donar | ninguna |

Para no repetir un campo en todas las cuentas, ponlo una vez en `"account_defaults": { ... }`.

**Opciones generales** (también opcionales; cualquiera se puede poner dentro de una cuenta para cambiarla sólo en ella):

| Opción | Qué hace | Por defecto |
|---|---|---|
| `routine` | lista de pasos `{"account", "task"}` en el orden que quieras (se edita desde el visor) | las `tasks` de cada cuenta |
| `home_account` | cuenta en la que descansa | la primera con `donor` |
| `donate`, `request_troops` | donar en el clan / pedir tropas cuando es gratis | `true`, `true` |
| `rest_minutes_between_cycles`, `rest_minutes_when_full` | descanso entre vueltas | `2`, `30` |
| `owner_pause_minutes` | cuánto se aparta si entras tú a jugar | `45` |
| `min_loot_ratio` | botín mínimo automático, como parte de la capacidad | `0.035` |
| `walls_spend_ratio`, `walls_one_by_one`, `walls_recheck_hours` | muros: cuándo gastar, cuándo ir de uno en uno, cada cuánto volver a mirar | `0.8`, `10`, `72` |
| `hero_ability_seconds`, `stall_seconds` | habilidad de los héroes y cuándo dar la batalla por parada | `7`, `15` |
| `troop_roles`, `spell_roles` | qué tropas son tanque/apoyo… y qué hechizos van a defensas o a tropas | los del juego |
| `mass_event`, `mass_cards`, `mass_count` | evento de tropa en masa | `false` |
| `serial`, `adb`, `game_package` | dispositivo ADB, ruta de adb y paquete del juego | `127.0.0.1:5555` |
| `ollama`, `model`, `model_keep_alive`, `model_max_ram_gb` | modelo de visión | `qwen2.5vl:7b` |
| `bluestacks_player`, `bluestacks_instance`, `emulator_args`, `emulator_process` | cómo arrancar el emulador | BlueStacks 5 |
| `panel_port`, `panel_host`, `clan_site_url` | visor | `8000` |
| `advanced` | cambia constantes internas (coordenadas, tablas) sin tocar el código: `{"SPEED_BTN": [1840, 615]}` | — |

La lista completa, con sus valores, está en [`asistente/settings.py`](asistente/settings.py).

Si escribes algo mal (una cuenta que no existe en la rutina, una tarea inventada, un número imposible), el asistente
**no se cae**: lo dice en el diario y en el visor, usa el valor por defecto y sigue. Los cambios se aplican solos, sin reiniciar
(salvo la conexión, el emulador y el visor, que se leen al arrancar).

> 💡 El asistente está medido para el juego **en español** y a **1920x1080**. Con otra resolución 16:9 adapta capturas y
> toques solo (y avisa); con otra proporción no funciona.

### Paso 5 · ¡A farmear!

1. Doble clic en **`Iniciar asistente`** (escritorio).
2. Se abre el visor **http://localhost:8000**. En unos segundos verás la pantalla del emulador y al asistente trabajando.
   *(si BlueStacks estaba cerrado, lo abre él solo)*
3. Para pararlo: **`Detener asistente`** (acaba lo que está haciendo y se para).

---

## 🖥️ El visor (http://localhost:8000)

| Zona | Para qué |
|---|---|
| **Pantalla** | El emulador en directo, con los toques del asistente marcados. |
| **📦 Almacenes** | Por cuenta: barra con lo que tienes y una **marca blanca que arrastras** = hasta qué % llenar. Debajo, cuánto tendrías, cuánto falta y **≈ cuántos ataques**. Se actualiza tras cada ataque. |
| **🔁 Rutina en bucle** | La lista de tareas. **Arrastra** las filas para cambiar la prioridad, cambia cuenta/tarea, ⏸ desactiva, ✕ quita, ＋ añade. Pulsa **Guardar**. Iconos: ⚙️ haciéndolo · ✅ hecho/lleno · ⏳ pendiente · 🙈 saltada (estabas jugando) · ⚠️ falló · 💤 desactivada · ➡️ pedido desde el visor. **⚡ Hacer ya** (en cada fila): deja lo que esté haciendo y va a ese paso; luego sigue la rutina desde ahí. Obedece en el siguiente punto seguro (entre ataques, en la búsqueda o en la pausa; nunca corta una batalla con tropas ya desplegadas) y, si estaba detenido, lo arranca. Arriba: **⏭ Empezar ya** se salta el descanso y **⏭ Ya no juego** se salta la pausa de cuando juegas tú. |
| **💰 Botín por ataque** | Cada ataque con estrellas, % y oro/elixir/oscuro, y el TOTAL. |
| **Diario** | Qué ve, qué decide y qué hace, en tiempo real. |
| **🏆 Rendimiento** | Enlace a la web del clan, que es un proyecto aparte: ver [`rendimiento/`](rendimiento/README.md). |

### Rendimiento

La web del clan vive en [`rendimiento/`](rendimiento/README.md): se abre aparte con `rendimiento/Abrir rendimiento.bat` y se puede publicar en Vercel. El visor sólo la enlaza; cambia el enlace con la variable `COC_RENDIMIENTO_URL`.

### Tareas disponibles

| Tarea | Qué hace |
|---|---|
| **Llenar almacenes** | Ataca sin tope, con buen botín, hasta llegar al % objetivo. Si ya está lleno, pasa a lo siguiente (también si dos ataques seguidos no suman nada: ya no cabe). |
| **Farmear** | N ataques por vuelta (la única tarea con número; las demás siguen hasta cumplir su objetivo). |
| **Llenar aldea nocturna** | Batallas de constructor, sin tope, hasta llenar la aldea nocturna. Sólo para antes si dos batallas seguidas no suman nada (bonus diario agotado). |
| **Mejorar lo recomendado** | Abre el panel de constructores y pone a mejorar lo **recomendado** que se pueda pagar (nunca con gemas). Para al llegar a `auto_build_until_th`. |
| **Mejorar muros** | Farmea sin tope y, cuando el oro o el elixir llegan al `walls_spend_ratio` del almacén (80 % por defecto), los gasta en muros: busca la fila «Muro x N» del panel de constructores (por plantilla, `tpl/muro_panel.png`), usa **Mejorar más** para pagar de una vez todos los que lleguen, primero el nivel más bajo, y lee la confirmación «Mejorar muros … por Oro xN» antes de pulsar Vale. Necesita un **constructor libre normal**: el duende constructor cobra gemas («¡Buenas, jefe!») y se cierra con la X; si no hay, sigue farmeando y con los almacenes llenos descansa. Los botones de pago se buscan por el icono de su precio (moneda o gota), porque en ayuntamientos altos aparece un tercer botón con **anillos de muro**, que nunca se toca. Nunca gemas, martillos ni anillos. Cuando la lista ya no tiene muros (repasada dos veces), marca la cuenta como terminada (`walls_done`, se revisa cada 12 h por si sube el ayuntamiento) y **activa el siguiente paso de muros que esté en cola** (`"queue": true`, icono 🕓 en el visor). |

---

## 🤖 Cómo funciona (resumen)

- `vigilante.py` mantiene vivo todo: BlueStacks, el visor (`server.py`), Ollama y el asistente. Si algo se cuelga, lo reinicia.
- `asistente/asistente.py` es el asistente: toca la pantalla por **ADB** y mira capturas.
- `asistente/vision.py` lee la pantalla por colores y plantillas (contorno de la aldea, defensas aéreas, cartas).
- `asistente/eyes.py` usa un modelo de visión local (**qwen2.5vl:7b** en **Ollama**) sólo para leer números y textos
  (botín, recursos, nombres). Todo corre en tu PC, nada sale a internet.
- El ataque se planifica solo: elige el lado, lanza rayos/hielos a las defensas aéreas, despliega tropas y héroes
  y activa habilidades a su hora. Cada ataque deja capturas en `asistente/ultimo_ataque/` para revisarlo.

---

## 🧯 Problemas frecuentes

| Problema | Solución |
|---|---|
| `probar_conexion.bat` no sale `device` | En BlueStacks: Ajustes → Avanzado → **ADB activado**. Mira el puerto y ponlo en `"serial"` de `config.json`. Reinicia BlueStacks. |
| El visor no abre | Espera 30 s y recarga. Si sigue: ejecuta `Iniciar asistente` otra vez. |
| La pantalla del visor sale negra | BlueStacks está minimizado o arrancando; espera un minuto. |
| No cambia de cuenta | `switch_label` debe coincidir con la tarjeta de *Cambiar de cuenta* (Supercell ID). |
| Toca en sitios raros | La resolución del emulador **tiene que ser 1920 × 1080** y el zoom del juego al mínimo. |
| No hace zoom out o no se mueve bien | Con la aldea a la vista y el asistente detenido, doble clic en **`probar_zoom.bat`**: comprueba la resolución y el táctil, y prueba el zoom. |
| Lee mal los números | Comprueba que Ollama está instalado y que se descargó el modelo: `ollama list` debe mostrar `qwen2.5vl:7b`. |
| El PC va muy lento | El modelo de visión necesita RAM: cierra programas o usa un PC con 16 GB+. |
| Quiero que pare ya | `Detener asistente`. Para que deje de tocar al instante, cierra BlueStacks. |
| Estaba jugando y se ha parado | Normal: si entras desde otro dispositivo se aparta 45 min. Para que siga antes, pulsa **Ya no juego** en el visor (o borra `asistente\PAUSA_DUENO`). |

---

## 📁 Estructura

```
coc-asistente/
├─ instalar.bat            ← instalación (una vez)
├─ Iniciar asistente.bat   ← pone a farmear y abre el panel
├─ Detener asistente.bat   ← parada limpia
├─ probar_conexion.bat     ← comprueba ADB
├─ probar_zoom.bat         ← comprueba el zoom out
├─ vigilante.py            ← mantiene todo vivo
├─ server.py · index.html  ← visor web (localhost:8000)
├─ rendimiento/            ← web del clan, independiente (lista para Vercel)
├─ requirements.txt
└─ asistente/
   ├─ asistente.py           ← el asistente
   ├─ settings.py          ← valores por defecto y validación de config.json
   ├─ vision.py · eyes.py · device.py
   ├─ tpl/ · cards/        ← plantillas de imagen (defensas, barco, cartas de tropas)
   ├─ config.example.json  ← plantilla de configuración
   └─ config.json          ← TU configuración (no se sube a GitHub)
```

### Subirlo a GitHub

```bash
git init
git add .
git commit -m "CoC asistente"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/coc-asistente.git
git push -u origin main
```

`asistente/config.json` (tus cuentas), `rendimiento/clan.json` y `rendimiento/clan.db` (tu clan), los registros y las capturas **no se suben** (están en `.gitignore`).
