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

### Paso 4 · Tus cuentas (3 min)

Abre **`asistente\config.json`** con el Bloc de notas. Por cada cuenta, en `"accounts"`, cambia:

| Campo | Qué poner | Ejemplo |
|---|---|---|
| nombre de la cuenta (la clave) | un nombre corto tuyo | `"Principal"` |
| `village_name` | el nombre de la aldea **tal cual sale arriba a la izquierda** en el juego | `"MiAldea"` |
| `switch_label` | el nombre de la tarjeta en **Supercell ID → Cambiar de cuenta** | `"MiAldea"` |
| `label` | cómo quieres verla en el visor | `"Principal · TH18"` |
| `capacity` | no hace falta: el asistente lee el **Máx.** de cada recurso del juego y lo actualiza solo | `28000000` |
| `builder_capacity` | *(opcional)* igual, para la aldea nocturna | `4700000` |
| `min_loot` | botín mínimo para atacar una base | `1000000` |
| `auto_build` | `true` si quieres que **mejore solo** esa cuenta | `true` |
| `auto_build_until_th` | nivel de ayuntamiento en el que deja de mejorar | `10` |
| `request_message` | *(opcional)* mensaje al pedir tropas | `"Dragones porfa"` |

Y en `"home_account"` pon la cuenta que más dona (el asistente se queda en ella mientras descansa).

Si una cuenta te sobra, bórrala (y sus pasos en `"routine"`). Guarda el archivo.

> 💡 Los **porcentajes** de llenado y el **orden de la rutina** no hace falta tocarlos aquí: se cambian desde el visor.

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
| **🔁 Rutina en bucle** | La lista de tareas. **Arrastra** las filas para cambiar la prioridad, cambia cuenta/tarea, ⏸ desactiva, ✕ quita, ＋ añade. Pulsa **Guardar**. Iconos: ⚙️ haciéndolo · ✅ hecho/lleno · ⏳ pendiente · 🙈 saltada (estabas jugando) · ⚠️ falló · 💤 desactivada. **⏭ Empezar ya** se salta el descanso. |
| **💰 Botín por ataque** | Cada ataque con estrellas, % y oro/elixir/oscuro, y el TOTAL. |
| **Diario** | Qué ve, qué decide y qué hace, en tiempo real. |
| **🏆 Rendimiento** | Enlace a la web del clan, que es un proyecto aparte: ver [`rendimiento/`](rendimiento/README.md). |

### Rendimiento

La web del clan vive en [`rendimiento/`](rendimiento/README.md): se abre aparte con `rendimiento/Abrir rendimiento.bat` y se puede publicar en Vercel. El visor sólo la enlaza; cambia el enlace con la variable `COC_RENDIMIENTO_URL`.

### Tareas disponibles

| Tarea | Qué hace |
|---|---|
| **Llenar almacenes** | Ataca bases con buen botín hasta llegar al % objetivo. Si ya está lleno, pasa a lo siguiente. |
| **Farmear** | Igual, pero como mucho N ataques por vuelta. |
| **Llenar aldea nocturna** | Batallas de constructor hasta llenar la aldea nocturna (tope N por vuelta). |
| **Mejorar lo recomendado** | Abre el panel de constructores y pone a mejorar lo **recomendado** que se pueda pagar (nunca con gemas). Para al llegar a `auto_build_until_th`. |

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
| Estaba jugando y se ha parado | Normal: si entras desde otro dispositivo se aparta 45 min. Para que siga antes, borra `asistente\PAUSA_DUENO`. |

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
