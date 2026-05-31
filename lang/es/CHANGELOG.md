
## 2026-04-20

### Nueva versión ProxMenux v1.2.1 — *SR-IOV Awareness & GPU Passthrough Hardening*

Release puntual sobre **v1.2.0** que aborda tres áreas reportadas por la comunidad y que necesitaban arreglo antes del siguiente ciclo estable: reconocimiento completo de SR-IOV en todo el subsistema GPU/PCI, gestión robusta de los dispositivos de audio acompañantes de la GPU durante el attach y detach de passthrough (Intel iGPU con audio del chipset, tarjetas discretas con audio HDMI, VMs con GPU mixta), y fixes de compatibilidad para los proveedores de notificaciones con IA (endpoints custom OpenAI-compatible tipo LiteLLM/MLX/LM Studio, modelos de razonamiento de OpenAI, y modelos thinking de Gemini 2.5+/3.x). También incluye mejoras de calidad de vida en el instalador NVIDIA, el Monitor de salud de discos, y los helpers de ciclo de vida de LXC usados por los wizards de passthrough.

---

## 🎛️ SR-IOV Awareness en todo el subsistema GPU

Intel `i915-sriov-dkms` y AMD MxGPU dividen la Physical Function (PF) de una GPU en Virtual Functions (VFs) que pueden asignarse de forma independiente a LXCs y VMs. Anteriormente ProxMenux no tenía reconocimiento alguno de SR-IOV: trataba VFs y PFs de manera idéntica, lo que podía reescribir `vfio.conf` con el vendor:device ID de la PF, colapsar el árbol de VFs en el siguiente arranque, y dejar a los usuarios sin poder iniciar sus guests. Se ha auditado y endurecido cada ruta que pudiera alterar un árbol de VFs activo.

### Helpers de detección
- Nuevos `_pci_is_vf`, `_pci_has_active_vfs`, `_pci_sriov_role`, `_pci_sriov_filter_array` en `scripts/global/pci_passthrough_helpers.sh`
- Equivalentes HTTP/JSON en la ruta Flask de GPU — la UI del Monitor lee el estado VF/PF directamente desde sysfs (`physfn`, `sriov_totalvfs`, `sriov_numvfs`, `virtfn*`)

### Pre-start hook (`gpu_hook_guard_helpers.sh`)
El guard pre-start de las VMs ahora reconoce Virtual Functions. Tanto la rama de sintaxis slot-only (que solía iterar todas las funciones del slot y exigir `vfio-pci` en todas) como la rama full-BDF saltan las VFs, de modo que Proxmox puede realizar su rebind vfio-pci por VF con normalidad. El falso bloqueo "GPU passthrough device is not ready" en VMs SR-IOV ha desaparecido.

### Los scripts de mode-switch rechazan operaciones SR-IOV
`switch_gpu_mode.sh`, `switch_gpu_mode_direct.sh`, `add_gpu_vm.sh`, `add_gpu_lxc.sh`, `vm_creator.sh`, `synology.sh`, `zimaos.sh` y `add_controller_nvme_vm.sh` rechazan ahora las VFs y las PFs con VFs activas antes de tocar la configuración del host. Un dialog claro "SR-IOV Configuration Detected" explica la situación. Para los wizards invocados en mitad de flujo (creadores de VM) el mensaje se entrega por `whiptail` para que interrumpa limpiamente, seguido de una línea `msg_warn` por dispositivo para dejar rastro en el log.

### Nuevo estado "SR-IOV active" en la UI del Monitor
La tarjeta GPU de la página Hardware gana un tercer estado visual con un color teal dedicado, una pill in-line `SR-IOV ×N` (o `SR-IOV VF` para una Virtual Function), y ramas LXC y VM en discontinuo/atenuadas. El botón Edit se oculta porque el estado está gestionado por hardware.

![SR-IOV active card and modal](https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/sriov-indicator.png)

### Modal dashboard para GPUs SR-IOV
Al abrir el modal de una Physical Function con VFs activas se muestra ahora:
- Banner de métricas agregadas ("Metrics below reflect the Physical Function, aggregate across N VFs")
- Telemetría normal en tiempo real de la GPU para la PF
- Una tabla **Virtual Functions**, una fila por VF, con el driver actual (`i915`, `vfio-pci`, unbound) y la VM o LXC específica que la consume, incluyendo el estado running/stopped — los consumidores se descubren cruzando entradas `hostpci` y líneas de mount `/dev/dri/renderDN` contra el BDF de la VF y el nodo DRM render

Al abrir el modal de una Virtual Function se muestran su PF padre (clickable para navegar de vuelta al modal de la PF), el driver actual y el consumidor.

### El popup de VM Conflict Policy ya no se dispara para VFs de SR-IOV
La regex en `detect_affected_vms_for_selected` casaba el slot (`00:02`) contra VMs que tenían una VF (`00:02.1`) asignada, produciendo un dialog confuso "Keep GPU in VM config". Con el gate SR-IOV upstream, el flujo nunca llega a ese camino de código para slots SR-IOV.

---

## 🔊 GPU + Audio Passthrough — Hardening de ciclo de vida completo

Una ronda de fixes en torno a cómo el passthrough de GPU gestiona su dispositivo de audio acompañante. Anteriormente, solo se recogía automáticamente el hermano `.1` de una GPU discreta; el passthrough de iGPU Intel a una VM — donde el audio vive separado en el chipset en `00:1f.3` y no en `00:02.1` — se saltaba silenciosamente. En el detach, el viejo `sed` que limpiaba líneas hostpci por substring de slot también podía eliminar una GPU no relacionada cuyo BDF contuviera el slot buscado como substring (p. ej. el slot `00:02` casando dentro de `0000:02:00.0`). Ambos caminos son ahora robustos.

### Checklist de audio-companion de iGPU en el attach
`add_gpu_vm.sh::detect_optional_gpu_audio` mantiene la fast path de auto-include para el clásico hermano `.1` (NVIDIA / AMD discretas con audio HDMI en la tarjeta). Cuando no existe audio `.1`, el script ahora:
- Escanea sysfs en busca de cada controlador PCI de audio del host
- Salta cualquier cosa ya cubierta por el IOMMU group de la GPU
- Pregunta al usuario mediante un `_pmx_checklist` (`dialog` en modo standalone, `whiptail` en modo wizard llamado desde `vm_creator`/`synology`/`zimaos`) qué controladores de audio pasar junto con la GPU
- Muestra cada entrada con su driver actual en el host (`snd_hda_intel`, `snd_hda_codec_*`, etc.) para que la decisión sea informada
- Por defecto **none** — el usuario opta activamente por incluirlos

### Cascada de audio huérfano en el detach
Cuando el usuario elige "Remove GPU from VM config" durante un mode switch, los scripts hacen ahora un seguimiento con limpieza dirigida:
- `switch_gpu_mode.sh`, `switch_gpu_mode_direct.sh` y `add_gpu_vm.sh::cleanup_vm_config` (limpieza de la VM origen en el flujo "move GPU") llaman todos al helper compartido `_vm_list_orphan_audio_hostpci`
- El helper usa un escaneo en dos pasadas del config de la VM: pasada 1 registra las bases de slot de las entradas hostpci display/3D; pasada 2 clasifica las entradas de audio y **salta cualquier audio cuyo slot aún tenga un hermano display en la misma VM** — protegiendo el audio HDMI de otras dGPUs que queden en la VM
- Antes el simple match por substring habría marcado el `02:00.1` de NVIDIA como huérfano al hacer detach de una iGPU Intel en `00:02.0`
- El flujo interactivo de switch confirma las eliminaciones con un checklist de `dialog` (por defecto ON). La variante web hace auto-remove sin preguntar — el runner no tiene buena forma de renderizar un checklist — y loguea cada BDF que ha tocado

### Extensión de la cascada a vfio.conf
Para cada audio eliminado por la cascada, los scripts de switch-mode comprueban ahora si su BDF sigue referenciado por cualquier otra VM vía `_pci_bdf_in_any_vm`. Si nada más lo usa, el `vendor:device` se añade a `SELECTED_IOMMU_IDS` antes de que se ejecute el update de `/etc/modprobe.d/vfio.conf`. Eso cierra el bucle para el caso de la iGPU Intel: `8086:51c8` (PCH HD Audio) se retira ahora de `vfio.conf` junto con `8086:46a3` (iGPU) cuando ambos salen del modo VM y ninguna otra VM los referencia. Si otra VM aún usa el audio, el ID se conserva deliberadamente — sin efectos secundarios rompedores sobre otras VMs. `add_gpu_vm.sh` NO extiende la limpieza en el flujo *move*, porque la GPU sigue en uso en otro sitio y sus IDs deben permanecer.

### Regex precisa de eliminación de hostpci
Cada `sed` inline usado para hacer detach de una GPU del config de una VM casaba antes el slot como substring libre:
```
/^hostpci[0-9]+:.*${slot}/d
```
Para `slot=00:02` ese patrón casa la substring dentro de `0000:02:00.0` (una dGPU NVIDIA no relacionada en el slot `02:00`) y borraría ambas tarjetas. El fix ancla el match a la forma BDF real:
```
/^hostpci[0-9]+:[[:space:]]*(0000:)?${slot}\.[0-7]([,[:space:]]|$)/d
```
Aplicado en `switch_gpu_mode.sh`, `switch_gpu_mode_direct.sh` y `add_gpu_vm.sh::cleanup_vm_config`. El helper basado en awk en `vm_storage_helpers.sh::_remove_pci_slot_from_vm_config` (usado por los wizards NVMe) ya usaba el patrón correcto y no necesitó cambios.

---

## 🤖 Compatibilidad de proveedores de IA — OpenAI-Compatible, modelos Reasoning y Thinking

Tres fixes coordinados que desbloquean categorías de modelos previamente rechazadas por el pipeline de mejora de notificaciones.

### Endpoints OpenAI-compatible
LiteLLM, MLX, LM Studio, vLLM, LocalAI, Ollama-proxy — el `list_models()` del proveedor exigía antes `"gpt"` en cada nombre de modelo, así que los setups locales sirviendo `mlx-community/...`, `Qwen3-...`, `mistralai/...` veían una lista de modelos vacía. Cuando se establece una Custom Base URL, la comprobación de substring `"gpt"` se omite ahora y `EXCLUDED_PATTERNS` (embeddings, whisper, tts, dall-e) es el único filtro. La capa de ruta Flask también deja de intersectar el resultado contra `verified_ai_models.json` para endpoints custom — la lista verificada solo describe los IDs oficiales de modelo de OpenAI y estaba borrando cada modelo local que el usuario realmente servía.

### Modelos reasoning de OpenAI
`o1`, `o3`, `o3-mini`, `o4-mini`, `gpt-5`, `gpt-5-mini`, `gpt-5.1`, `gpt-5.2-pro`, `gpt-5.4-nano`, etc. (excluyendo las variantes `*-chat-latest`) usan un contrato API más estricto: `max_completion_tokens` en lugar de `max_tokens`, sin `temperature`. Enviar los parámetros clásicos de chat producía HTTP 400 Bad Request para todos ellos. Un detector en `openai_provider.py` bifurca ahora el payload en consecuencia y establece `reasoning_effort: "minimal"` — por defecto estos modelos gastan su presupuesto de output en razonamiento interno y devuelven una respuesta vacía para la breve petición de traducción de notificación.

### Modelos thinking de Gemini 2.5+ / 3.x
`gemini-2.5-flash`, `2.5-pro`, `gemini-3-pro-preview`, `gemini-3.1-pro-preview`, etc. tienen "thinking" interno activado por defecto. Con el pequeño presupuesto de tokens usado para el enriquecimiento de notificaciones (≤250 tokens), el presupuesto de thinking consumía toda la asignación y el modelo devolvía output vacío con `finishReason: MAX_TOKENS`. `gemini_provider.py` establece ahora `thinkingConfig.thinkingBudget: 0` para variantes no-`lite` de 2.5+ y 3.x, de modo que los tokens disponibles van a la respuesta visible al usuario. Las variantes lite (sin thinking activado) quedan intactas.

---

## 📋 Refresh de Verified AI Models

`AppImage/config/verified_ai_models.json` refrescado para los proveedores re-testeados contra APIs en vivo. La nueva herramienta privada de mantenimiento (mantenida fuera de la AppImage) re-ejecuta un test estandarizado de translate+explain contra cada modelo que anuncia cada proveedor, clasifica pass / warn / fail, e imprime un snippet JSON listo para pegar. Re-ejecutar antes de cada release de ProxMenux para mantener la lista al día.

| Provider | New recommended | Notes |
|----------|-----------------|-------|
| **OpenAI** | `gpt-4.1-nano` | `gpt-4.1-nano`, `gpt-4.1-mini`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4o`, `gpt-5-chat-latest`, más `gpt-5.4-nano` / `gpt-5.4-mini` desde 2026-03. Snapshots con fecha y modelos legacy excluidos. Modelos reasoning soportados por el código pero no listados por defecto — más lentos / más caros sin mejorar la calidad de las notificaciones |
| **Gemini** | `gemini-2.5-flash-lite` | `gemini-2.5-flash-lite`, `gemini-2.5-flash` (funciona ahora), `gemini-3-flash-preview`. Aliases `latest` omitidos intencionadamente — resolvían a modelos distintos entre ejecuciones y producían timeouts en algunas regiones. Las variantes Pro rechazan `thinkingBudget=0` y son excesivas para traducción de notificaciones |
| Groq / Anthropic / OpenRouter | *sin cambios* | Marcados con un `_note` — se re-verificarán en cuanto haya keys disponibles |

---

## 🩺 Monitor de salud de discos — Persistencia de observaciones en el journal watcher

Un bug latente en `notification_events.py::_check_disk_io` hacía que los errores de I/O del kernel en tiempo real capturados por el journal watcher se superficiaran como notificaciones pero nunca se escribieran en la tabla permanente de observaciones por disco. En la práctica el escaneo paralelo periódico de dmesg solía registrar la observación poco después, pero bajo casos límite de timing (ventana de dmesg obsoleta, restart de servicio justo después del error, rotación de buffer) la observación podía perderse.

El journal watcher registra ahora la observación antes del gate de cooldown de notificación de 24h, usando la misma clasificación de signature por familia (`io_<disk>_ata_connection_error`, `io_<disk>_block_io_error`, `io_<disk>_ata_failed_command`) que el escaneo periódico. Ambos caminos deduplican ahora en la misma fila vía el UPSERT en `record_disk_observation`, de modo que los conteos de ocurrencias son precisos sin importar qué detector disparó primero.

---

## 🔧 Pulido del instalador NVIDIA

### Race condition de `lsmod` silenciada
Durante la reinstalación, la verificación de unload de módulos en `unload_nvidia_modules` producía errores espurios `lsmod: ERROR: could not open '/sys/module/nvidia_uvm/holders'` porque `lsmod` lee `/proc/modules` y luego abre el directorio `holders/` de cada módulo, que desaparece transitoriamente mientras el módulo está siendo eliminado. La comprobación lee ahora `/proc/modules` directamente e inserta sleeps cortos para dejar que el kernel finalice el unload antes de re-verificar. Aplicado en el mismo espíritu a los otros cuatro call sites de `lsmod` en el script.

### Dialog → whiptail en el flujo de update LXC
El mensaje "Insufficient Disk Space" en `update_lxc_nvidia` y la confirmación "Update NVIDIA in LXC Containers" usan ahora dialogs estilo `whiptail` consistentes con el resto del messaging in-flow, evitando la rotura visual que `dialog --msgbox` causaba al renderizarse en mitad de la secuencia en la fase de update de contenedores.

---

## 🧵 Helper de ciclo de vida LXC — Stop seguro con timeout

Un `pct stop` simple puede colgarse indefinidamente cuando el contenedor tiene un lock obsoleto de una operación abortada previa, cuando los procesos de dentro (Plex, Jellyfin, bases de datos) ignoran TERM y caen en uninterruptible-sleep mientras la GPU que estaban usando es arrancada, o cuando `pct shutdown --timeout` no es respetado por pct mismo. Reportes de campo de esperas de 5+ min durante mode switches de GPU hicieron de esto un peligro real de UX.

Nuevo helper compartido `_pmx_stop_lxc <ctid> [log_file]` en `pci_passthrough_helpers.sh`:
1. Devuelve 0 inmediatamente si el contenedor no está corriendo
2. `pct unlock` best-effort (silencioso ante fallo) — la mayoría de contenedores no están realmente bloqueados; solo nos importan los casos en que lo están
3. `pct shutdown --forceStop 1 --timeout 30` envuelto en un `timeout 45` externo para no esperar nunca más que eso a la fase graceful, incluso si pct se atasca en I/O del backend
4. Verifica el estado real vía `pct status` — pct puede devolver no-cero mientras el contenedor está de hecho parado
5. Si sigue corriendo, `pct stop` envuelto en `timeout 60`. Verificar de nuevo
6. Devuelve 1 solo si el contenedor está realmente atascado tras ~107 s totales — el wizard continúa en lugar de colgarse

Cableado en las tres rutas de modo GPU que paran LXCs durante un switch: `switch_gpu_mode.sh`, `switch_gpu_mode_direct.sh`, y `add_gpu_vm.sh::cleanup_lxc_configs`.

---

## ⚙️ Estabilidad del prompt de reboot en `add_gpu_vm.sh`

El prompt final "Reboot Required" del wizard de asignación GPU-a-VM estaba disparando reboots espurios en ciertas invocaciones de cadena de menú (`menu` → `main_menu` → `hw_grafics_menu` → `add_gpu_vm`). Con el helper `_pmx_yesno` a veces devolvía exit 0 sin que el usuario hubiera confirmado realmente, llamando `reboot` de inmediato. Con un `read` simple en su lugar el proceso quedaba suspendido por SIGTTIN cuando la cadena de menú desligaba el script del grupo de proceso foreground del terminal, dejando `[N]+ Stopped menu` en el shell padre sin posibilidad de responder.

El prompt usa ahora `whiptail --yesno` invocado directamente (el patrón verificado para funcionar de forma fiable en esa cadena de menú) e inserta una pausa `Press Enter to continue ... read -r` entre la respuesta "Yes" y la llamada real a `reboot` — de modo que un Enter accidental en el botón de confirmar no puede disparar un reboot inmediato sin un paso de confirmación visible primero.

---

### 🙏 Gracias

Gracias a los usuarios que reportaron los casos de SR-IOV, LiteLLM/MLX y GPU + audio — estas mejoras existen gracias a reportes detallados y reproducibles. No dudéis en seguir reportando issues o sugiriendo mejoras 🙌.

---


## 2026-04-17

### Nueva versión ProxMenux v1.2.0 — *AI-Enhanced Monitoring*


![ProxMenux AI](https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/ProxMenux_ai.png)

Esta release es la culminación del ciclo beta v1.1.9.1 → v1.1.9.6 e introduce la mayor evolución de **ProxMenux Monitor** hasta la fecha: notificaciones mejoradas con IA, un sistema de notificaciones multicanal rediseñado, una experiencia de hardware y almacenamiento totalmente reelaborada, y mejoras amplias de rendimiento en todo el stack de monitorización. También consolida todo el trabajo reciente en los scripts de Storage, Hardware y GPU/TPU.

---

## 🤖 ProxMenux Monitor — Notificaciones mejoradas con IA

Las notificaciones pueden mejorarse ahora usando IA para generar mensajes claros y contextuales en lugar del output técnico crudo.

Ejemplo — en lugar de `backup completed exitcode=0 size=2.3GB`, la IA produce: *"The web server backup completed successfully. Size: 2.3GB"*.

### Lo que hace la IA
- Transforma notificaciones técnicas en mensajes legibles
- Traduce a tu idioma preferido
- Te deja elegir el nivel de detalle: minimal, standard o detailed
- Funciona con Telegram, Discord, Email, Pushover y Webhooks

### Lo que la IA NO hace
- **No** es un chatbot ni un asistente
- **No** analiza tu sistema ni toma decisiones
- **No** tiene acceso a datos más allá de la notificación que está procesando
- **No** ejecuta comandos ni modifica el servidor
- **No** almacena historial ni aprende de tus datos

### Soporte multi-proveedor
Elige entre 6 proveedores de IA, cada uno con su propia API key almacenada de forma independiente:
- **Groq** — inferencia rápida, free tier generoso
- **Google Gemini** — excelente relación calidad/precio, free tier disponible
- **OpenAI** — estándar de la industria
- **Anthropic Claude** — excelente para escritura y traducción
- **OpenRouter** — 300+ modelos con una sola API key
- **Ollama** — ejecución 100% local, sin internet

### Verified AI Models
Una lista curada de modelos (`verified_ai_models.json`) testeada específicamente para mejora de notificaciones.

- **Verificación híbrida**: el sistema obtiene los modelos del lado del proveedor y filtra para mostrar solo los testeados que funcionan correctamente
- **Memoria de modelo por proveedor**: el modelo seleccionado se guarda por proveedor, de modo que cambiar de proveedor preserva cada elección
- **Verificación diaria**: una tarea en background comprueba la disponibilidad de modelos y migra automáticamente a una alternativa verificada si el modelo actual desaparece
- **Modelos incompatibles excluidos**: Whisper, TTS, image/video, embeddings, guard models, etc. se filtran por proveedor

| Provider | Recommended | Also Verified |
|----------|-------------|---------------|
| Gemini | gemini-2.5-flash-lite | gemini-flash-lite-latest |
| OpenAI | gpt-4o-mini | gpt-4.1-mini |
| Groq | llama-3.3-70b-versatile | llama-3.1-70b-versatile, llama-3.1-8b-instant, llama3-70b-8192, llama3-8b-8192, mixtral-8x7b-32768, gemma2-9b-it |
| Anthropic | claude-3-5-haiku-latest | claude-3-5-sonnet-latest, claude-3-opus-latest |
| OpenRouter | meta-llama/llama-3.3-70b-instruct | meta-llama/llama-3.1-70b-instruct, anthropic/claude-3.5-haiku, google/gemini-flash-2.5-flash-lite, openai/gpt-4o-mini, mistralai/mixtral-8x7b-instruct |
| Ollama | (todos los modelos locales) | Sin filtrado — muestra todos los modelos instalados |

### Custom AI Prompts
Los usuarios avanzados pueden definir su propio prompt para tener control total sobre el formato y la traducción.

- **Selector de Prompt Mode** — Default Prompt o Custom Prompt
- **Export / Import** — guarda y comparte prompts custom entre instalaciones
- **Example Template** — punto de partida para construir tu propio prompt
- **Community Prompts** — enlace directo a GitHub Discussions para compartir plantillas
- El selector de idioma se oculta en modo Custom Prompt (defines el idioma de salida en el propio prompt)

### Contexto enriquecido
- El **uptime** del sistema se incluye solo para eventos de error/warning (no informativos) — ayuda a distinguir errores de arranque vs runtime
- Tracking de **frecuencia de eventos** — indica problemas recurrentes vs puntuales
- Datos de **SMART disk health** pasados para errores relacionados con discos
- La base de datos de **errores conocidos de Proxmox** mejora la precisión del diagnóstico
- Instrucciones de prompt más claras para prevenir alucinaciones de la IA

---

## 📨 Rediseño del sistema de notificaciones

- **Arquitectura multicanal** — canales Telegram, Discord, Pushover, Email y Webhook corriendo simultáneamente
- **Configuración por evento** — habilita/deshabilita tipos de evento específicos por canal
- **Channel Overrides** — personaliza el comportamiento de notificación por canal
- **Endpoint webhook seguro** — sistemas externos pueden enviar notificaciones autenticadas
- **Almacenamiento cifrado** — API keys y datos sensibles guardados cifrados
- **Procesamiento basado en cola** — worker en background con reintento automático para notificaciones fallidas
- **Almacenamiento de config basado en SQLite** — reemplaza el config basado en ficheros para mayor fiabilidad

### Soporte de Telegram Topics
Envía notificaciones a un topic específico dentro de grupos con Topics habilitado.
- Nuevo campo **Topic ID** en el canal Telegram
- Detección automática de grupos con topics habilitados
- Totalmente retrocompatible

### Notificaciones de update de ProxMenux
El Monitor detecta ahora cuándo se publica una nueva versión de ProxMenux.
- **Doble canal** — monitoriza tanto stable (`version.txt`) como beta (`beta_version.txt`)
- **Integración con GitHub** — compara versiones locales vs remotas
- **Dashboard Update Indicator** — el logo de ProxMenux cambia a una variante de update cuando se detecta una nueva versión (no intrusivo, sin popups)
- **Estado persistente** — el estado se guarda en `config.json`, reseteado por los scripts de update
- Un único toggle en Settings controla ambos canales (habilitado por defecto)

---

## 🖥️ Panel de Hardware — Detección ampliada

La página Hardware se ha ampliado significativamente, con mejor detección y detalle por dispositivo más rico.

- **Controladoras SCSI / SAS / RAID** — modelo, driver y slot PCI mostrados en la sección de storage controllers
- **Detección de PCIe Link Speed** — los drives NVMe muestran la velocidad de link actual (generación PCIe y ancho de carriles), facilitando detectar drives que rinden por debajo por ancho de banda limitado del slot
- **Modal de detalle de disco mejorado** — los drives NVMe, SATA, SAS y USB exponen ahora sus campos específicos (info de link PCIe, versión/velocidad SAS, tipo de interfaz) en lugar de una vista genérica
- **Reconocimiento más inteligente de tipo de disco** — etiquetado uniforme para NVMe SSDs, SATA SSDs, HDDs y discos extraíbles
- **Caching de Hardware Info** (`lspci`, `lspci -vmm`) — la caché de 5 min evita escaneos repetidos de datos que no cambian

---

## 💽 Storage Overview — Salud, observaciones, exclusiones

El Storage Overview se ha reelaborado en torno al estado en tiempo real y al tracking controlado por el usuario.

### Alineación del estado de salud de disco
- Los badges reflejan ahora el estado **actual** SMART reportado por Proxmox, no un peor histórico
- **Observaciones preservadas** — los hallazgos históricos siguen accesibles vía el badge "X obs."
- **Recuperación automática** — cuando SMART reporta healthy de nuevo, el disco muestra inmediatamente **Healthy**
- Eliminado el viejo tracking `worst_health` que requería limpieza manual

### Mejoras del registro de discos
- **Lookup inteligente por serial** — cuando un serial es desconocido el sistema comprueba si existe una entrada con serial antes de insertar una nueva
- **Sin duplicados** — previene entradas separadas para el mismo disco apareciendo con/sin serial
- **Soporte de discos USB** — gestiona drives USB que pueden aparecer bajo nombres de dispositivo distintos entre reboots

### Exclusiones de Storage e interfaces de Red
- Sección **Storage Exclusions** — excluye drives de la monitorización de salud y notificaciones
- **Network Interface Exclusions** — nueva sección para excluir interfaces (bridges `vmbr`, bonds, NICs físicas, VLANs) de salud y notificaciones; ideal para interfaces deshabilitadas intencionadamente que de otro modo generarían falsas alertas
- **Toggles separados** por ítem para Health monitoring y Notifications

### Robustez en la detección de discos
- **Validación de Power-On-Hours** — detecta y corrige valores absurdamente grandes (miles de millones de horas) en drives con codificación SMART no estándar
- **Bit masking inteligente** — extrae el valor correcto de drives que empaquetan info extra en bytes altos
- **Fallback elegante** — muestra "N/A" en lugar de números imposibles cuando los datos no pueden parsearse

---

## 🧠 Monitor de salud y ciclo de vida de errores

### Limpieza de errores obsoletos
Los errores de recursos que ya no existen se resuelven ahora automáticamente.
- **VMs / CTs eliminadas** — los errores relacionados se auto-resuelven cuando se elimina el recurso
- **Discos retirados** — los errores de drives USB desconectados o hot-swap se limpian
- **Cambios de cluster** — los errores de cluster se limpian cuando un nodo abandona el cluster
- **Patrones de log** — los errores basados en logs se auto-resuelven tras 48 horas sin recurrencia
- **Updates de seguridad** — las notificaciones de update se auto-resuelven tras 7 días

### Sistema de migración de base de datos
- **Detección automática de columnas** — las columnas faltantes se añaden en el arranque
- **Compatibilidad de schema** — funciona tanto con convenciones de nombrado de columna antiguas como nuevas
- **Retrocompatible** — se soportan bases de datos de versiones anteriores de ProxMenux
- **Migración elegante** — sin pérdida de datos durante updates de schema

---

## 🧩 Modal de detalle VM / CT

El modal de detalle VM/CT se ha rediseñado por completo para mejorar la usabilidad.

- **Navegación con tabs** — *Overview* (información general, estado, uso de recursos) y *Backups* (historial dedicado)
- **Mejoras visuales** — iconos en todo, jerarquía y espaciado mejorados, mejor distinción VM vs CT
- **Adaptación a móvil** — se adapta correctamente a pantallas móviles tanto en webapp como en acceso directo por navegador, sin más overflow en dispositivos pequeños
- **Controles touch-friendly** — botones y espaciado mayores

### Modal de Secure Gateway
- **Lista de storage con scroll** cuando hay muchos destinos disponibles
- Layout adaptado a móvil y jerarquía visual mejorada

### Conexión de terminal
- **Fix de bucle de reconexión** que afectaba a dispositivos móviles
- Manejo mejorado de WebSocket para navegadores móviles
- Recuperación más elegante de timeouts de conexión

### Gestión de Fail2ban y Lynis
- **Botones de delete** añadidos en Settings para ambas herramientas
- Eliminación limpia de paquetes y ficheros de configuración
- Dialog de confirmación para prevenir borrado accidental

---

## ⚡ Optimizaciones de rendimiento

Reducción importante de uso de CPU y eliminación de picos en el Monitor.

### Intervalos de polling escalonados
Los collectors corren ahora en schedules con offset para prevenir ejecución simultánea:

| Collector | Schedule |
|-----------|----------|
| CPU sampling | Cada 30s en offset 0 |
| Temperature sampling | Cada 15s en offset 7s |
| Latency pings | Cada 60s en offset 25s |
| Temperature record | Cada 60s en offset 40s |
| Health collector | Arranca en offset 55s |
| Notification polling | Health=10s, Updates=30s, ProxMenux=45s, AI=50s |

### Información de sistema cacheada
Los comandos costosos se cachean ahora para reducir ejecución repetida:

| Command | Cache TTL | Impact |
|---------|-----------|--------|
| `pveversion` | 6 horas | Elimina picos de CPU del 23%+ por ejecución de Perl |
| `apt list --upgradable` | 6 horas | Reduce consultas del gestor de paquetes |
| `pvesh get /cluster/resources` | 30 segundos | 6 llamadas API por request reducidas a 1 |
| `sensors` | 10 segundos | Lecturas de temperatura cacheadas entre polls |
| `smartctl` (SMART health) | 30 minutos | Health checks de disco reducidos desde cada 5 min |
| `lspci` / `lspci -vmm` | 5 minutos | Info de hardware cacheada (no cambia) |
| `journalctl --since 24h` | 1 hora | Conteo de intentos de login cacheado (92% de reducción) |

### Timeouts de journalctl aumentados
Previene cascadas de timeout bajo carga del sistema:

| Query Type | Before | After |
|------------|--------|-------|
| Short-term (3-10 min) | 3s | 10s |
| Medium-term (1 hour) | 5s | 15s |
| Long-term (24 hours) | 5s | 20s |

### Frecuencia de polling reducida
- Intervalo de `TaskWatcher` subido de **2s → 5s** (60% menos comprobaciones)

### GitHub Actions
- Todas las actions de workflow actualizadas a **v6** para compatibilidad con Node.js 24
- Warnings de deprecación eliminados en CI/CD

---

## 🧰 Scripts — Trabajo en Storage, Hardware y GPU/TPU

Esta release también consolida trabajo significativo en los scripts core de ProxMenux.

### Scripts de Storage
- **Tests SMART programados** y flujo interactivo de test SMART mejorado con feedback de progreso más claro
- Reelaboración de **formateo de disco** (`format-disk.sh`) con selección de dispositivo más segura y flujo de dialog
- **Disk passthrough** para VMs y CTs — enumeración de dispositivos actualizada, identificación basada en serial, y teardown más limpio
- **Adición de controladora NVMe para VMs** — selección de tipo de controladora y detección de slot mejoradas
- **Import disk image** — validación de path más suave y reporte de progreso
- Refresh de la guía manual de **Disk & storage**

### Scripts de Hardware / GPU / TPU
- **Coral TPU installer** actualizado para kernels y udev rules actuales (Proxmox VE 8 & VE 9)
- **NVIDIA installer** — instalación de driver más limpia, manejo de kernel headers, y flujo de attachment VM/LXC
- **GPU mode switch** (variantes directa e interactiva) — switching más seguro entre modos iGPU
- **Add GPU to VM / LXC** — dialogs de selección unificados y gestión de permisos
- **Herramientas de GPU Intel / AMD** mantenidas en sync con los nuevos patrones compartidos
- **Hardware & graphics menu** reestructurado para consistencia con el resto de ProxMenux


## 2026-03-14

### Nueva versión v1.1.9 — *Helper Scripts Catalog Rebuilt*

### Cambiado

- **Helper Scripts Menu — Reconstrucción completa del catálogo**
  El catálogo de Helper Scripts se ha reconstruido por completo para adaptarse a la nueva arquitectura de datos del proyecto [Community Scripts](https://community-scripts.github.io/ProxmoxVE/).

  La implementación previa dependía de un fichero `metadata.json` que ya no existe en el repositorio upstream. El catálogo conecta ahora directamente a la **API de PocketBase** (`db.community-scripts.org`), que es la nueva fuente de datos oficial del proyecto.

  Un nuevo workflow de GitHub Actions genera un índice local `helpers_cache.json` que reemplaza la antigua dependencia de metadata. Esta nueva caché es más rica, más estructurada, e incluye:
  - Tipo de script, slug, descripción, notas y credenciales por defecto
  - Variantes de OS por script (p. ej. Debian, Alpine) — cada una mostrada como una opción seleccionable separada en el menú
  - URL directa de GitHub y **URL Mirror** (`git.community-scripts.org`) para cada script
  - Nombres de categoría embebidos directamente en la caché — sin necesidad de requests externos para construir el menú
  - Metadata adicional: puerto por defecto, website, logo, soporte de update, disponibilidad ARM

  Los scripts que soportan múltiples variantes de OS (p. ej. Docker con Alpine y Debian) muestran ahora correctamente **una entrada por OS**, cada una con su propia opción de descarga GitHub y Mirror — restaurando el comportamiento que existía antes de la migración upstream.

---

### 🎖 Reconocimiento especial

Esta actualización no habría sido posible sin la apertura y colaboración de los mantenedores de **Community Scripts**.

Cuando la estructura de metadata upstream cambió y rompió el catálogo de ProxMenux, los mantenedores respondieron rápidamente, explicaron la nueva arquitectura en detalle y proporcionaron toda la información necesaria para reconstruir la integración limpiamente.

Agradecimientos especiales a:

- **MickLeskCanbiZ ([@MickLesk](https://github.com/MickLesk))** — por documentar la nueva estructura de path de scripts por tipo y slug, y por la guía técnica clara y directa.
- **Michel Roegl-Brunner ([@michelroegl-brunner](https://github.com/michelroegl-brunner))** — por explicar la nueva estructura de colecciones de PocketBase (`script_scripts`, `script_categories`).

El proyecto Helper Scripts es un recurso extraordinario para la comunidad Proxmox. Los scripts pertenecen enteramente a sus autores y mantenedores — ProxMenux simplemente ofrece una forma guiada de descubrirlos y lanzarlos. Todo el crédito va a la comunidad detrás de [community-scripts/ProxmoxVE](https://github.com/community-scripts/ProxmoxVE).

## 2025-09-18

### Nueva versión v1.1.8 — *ProxMenux Offline Mode*

![ProxMenux Offline](https://macrimi.github.io/ProxMenux/ProxMenux_offline.png)

---

### Añadido

- **Modo de ejecución offline (sin dependencia de GitHub)**  
  Todos los scripts core de ProxMenux se ejecutan ahora **enteramente en local**, sin requerir requests en vivo a GitHub (`raw.githubusercontent.com`).  
  Este cambio proporciona:
  - Mayor estabilidad durante la ejecución
  - Sin interrupciones por timeouts de red o bloqueos regionales de GitHub
  - Soporte para **entornos offline o aislados**

  ⚠️ Esta actualización resuelve issues recientes donde usuarios en ciertas regiones eran incapaces de ejecutar scripts debido a errores de CDN o filtrado TLS al descargar ficheros `.sh` desde URLs raw de GitHub.

  **🎖 Reconocimiento especial: @cod378**  
  Esta conversión offline ha sido posible gracias al extraordinario trabajo de **@cod378**,  
  que rediseñó toda la lógica interna del installer y el updater, refactorizó el sistema de gestión de ficheros,  
  e implementó el nuevo workflow de ejecución totalmente local.  
  Sin su colaboración, dedicación y aportación técnica, esta transformación no habría sido posible.

- **ProxMenux Monitor v1.0.1**  
  Esta actualización trae un gran salto en la interfaz de **ProxMenux Monitor**.  
  Nuevas funciones y mejoras:
  - `Proxy Support`: Accede a ProxMenux a través de proxies inversos con plena funcionalidad
  - `Authentication System`: Asegura tu dashboard con protección por contraseña
  - `Two-Factor Authentication (2FA)`: Soporte opcional TOTP para mayor seguridad
  - `PCIe Link Speed Detection`: Ver velocidades de conexión NVMe y detectar cuellos de botella de rendimiento
  - `Enhanced Storage Display`: Auto-formatea tamaños de disco (GB → TB cuando corresponde)
  - `SATA/SAS Interface Info`: Detecta y muestra el tipo de storage (SATA, SAS, NVMe, etc.)
  - `Health Monitoring System`: Health check integrado del sistema con alertas descartables
  - Renderizado mejorado entre navegadores y mejor rendimiento

- **Helper Scripts Menu (Mirror Support)**  
  El menú `Helper Scripts` ahora:
  - Detecta **URLs mirror** y muestra opciones de descarga alternativas cuando están disponibles
  - Lista las versiones de OS disponibles cuando un helper script depende de la versión (p. ej. instaladores de plantillas)

---

### Arreglado

- Fixes menores y refinamientos a lo largo del codebase para asegurar compatibilidad offline total y una experiencia de usuario más suave.



## 2025-09-04

### Nueva versión v1.1.7

### Añadido

- **ProxMenux Monitor**  
  Tu nueva herramienta de monitorización para Proxmox. Descubre todas las funciones que te ayudarán a gestionar y supervisar tu infraestructura eficientemente.

  ProxMenux Monitor está diseñado para soportar futuras actualizaciones donde **se puedan disparar acciones sin usar el terminal**, gestionadas a través de una **interfaz amigable** accesible en múltiples formatos y dispositivos.

  Accede en: **http://your-server-ip:8008**

  ![ProxMenux Monitor](https://macrimi.github.io/ProxMenux/monitor/welcome.png)
- **Nuevo método de eliminación de banner**  
  Una nueva función para deshabilitar el mensaje de suscripción de Proxmox con seguridad mejorada:
  - Crea un backup completo antes de modificar ningún fichero
  - Muestra un warning claro de que pueden producirse breaking changes con futuras actualizaciones de la GUI
  - Si la GUI no carga, el usuario puede revertir los cambios por SSH desde el menú post-install usando la herramienta **"Uninstall Options → Restore Banner"**

  Gracias especiales a **@eryonki** por proporcionar el método mejorado.

---

### Mejorado

- **CORAL TPU Installer actualizado para PVE 9**  
  El instalador del driver CORAL TPU soporta ahora tanto **Proxmox VE 8 como VE 9**, asegurando compatibilidad con los kernels y udev rules más recientes.

- **Instalación e integración de Log2RAM**  
  - La instalación de Log2RAM es ahora idempotente y puede ejecutarse con seguridad múltiples veces.
  - Ajusta automáticamente la configuración de `journald` para alinearse con el tamaño y comportamiento de Log2RAM.
  - Asegura que el journaling esté correctamente afinado para evitar overflows o agotamiento de RAM en sistemas con poca memoria.

- **Función de optimización de Red (LXC + NFS)**  
  Mejorada para prevenir warnings de "martian source" en setups donde **contenedores LXC comparten storage con VMs** vía NFS dentro del mismo servidor.

- **Progreso de APT Upgrade**  
  Al ejecutar actualizaciones completas del sistema vía ProxMenux, se muestra ahora una **barra de progreso en tiempo real**, dando al usuario visibilidad clara del proceso de update.

---

### Arreglado

- Otras pequeñas mejoras y fixes para optimizar el rendimiento en runtime y eliminar bugs menores.



## 2025-01-10

### Nueva versión v1.1.6

![Shared Resources Menu](https://macrimi.github.io/ProxMenux/share/main-menu.png)


### Añadido

- **Nuevo menú: Mount and Share Manager**  
  Introducido un nuevo menú integral para gestionar recursos compartidos entre el host Proxmox y los contenedores LXC:

  **Opciones de configuración del host:**
  - **Configure NFS Shared on Host** - Añadir, ver y eliminar recursos NFS compartidos en el servidor Proxmox con gestión automática de exports
  - **Configure Samba Shared on Host** - Añadir, ver y eliminar recursos Samba/CIFS compartidos en el servidor Proxmox con configuración de share
  - **Configure Local Shared on Host** - Crear y gestionar directorios locales compartidos con los permisos adecuados en el host Proxmox

  **Opciones de integración LXC:**
  - **Configure LXC Mount Points (Host ↔ Container)** - **Función core** que permite montar directorios del host dentro de contenedores LXC con gestión automática de permisos. Incluye la capacidad de **ver los mount points existentes** para cada contenedor de forma clara y organizada y **eliminar mount points** con verificación apropiada de que el proceso se completó con éxito. Especialmente optimizado para **contenedores no privilegiados** donde el mapeo UID/GID es crítico.
  - **Configure NFS Client in LXC** - Configura un cliente NFS dentro de contenedores privilegiados
  - **Configure Samba Client in LXC** - Configura un cliente Samba dentro de contenedores privilegiados
  - **Configure NFS Server in LXC** - Instala servidor NFS dentro de contenedores privilegiados
  - **Configure Samba Server in LXC** - Instala servidor Samba dentro de contenedores privilegiados

  **Documentación y soporte:**
  - **Help & Info (commands)** - Guías integrales con instrucciones manuales paso a paso para todos los escenarios de compartición

  Todo el sistema está construido en torno a la funcionalidad de **LXC Mount Points**, que detecta automáticamente los tipos de filesystem, gestiona el mapeo de permisos entre usuarios del host y del contenedor, y proporciona integración fluida tanto para contenedores privilegiados como no privilegiados.

---

### Mejorado

- **Mejora de auto-detección de Log2RAM**  
  En el script automático de post-install, la función de instalación de Log2RAM ahora pregunta al usuario cuando la detección automática de disco ssd/m2 falla.
  Esto asegura que Log2RAM pueda instalarse aún en sistemas donde la detección automática de disco no funciona correctamente.

---

### Arreglado

- **Verificación del repositorio de updates de Proxmox**  
  Arreglado un issue en la función de update de Proxmox donde los ficheros source vacíos del repositorio causaban errores durante la verificación de conflictos. La función gestiona ahora correctamente ficheros vacíos de `/etc/apt/sources.list.d/` sin lanzar falsos warnings.

  Gracias a **@JF_Car** por reportar este issue.

---

### Reconocimientos

Gracias especiales a **@JF_Car**, **@ghosthvj** y **@jonatanc** por sus pruebas, feedback valioso y sugerencias que ayudaron a refinar la funcionalidad de recursos compartidos y a mejorar la experiencia general de usuario.



## 2025-08-20

### Nueva versión v1.1.5

### Añadido

- **Nuevo script: Upgrade PVE 8 a PVE 9**  
  Añadida una herramienta de upgrade completa ubicada bajo `Utilities and Tools`. Proporciona:
  1. **Upgrade automático** de PVE 8 a 9
  2. **Upgrade interactivo** con confirmaciones paso a paso
  3. **Modo check-only** usando `check-pve8to9`
  4. **Instrucciones manuales** mostradas en orden para usuarios que prefieren actualizar manualmente

- **Nuevas herramientas en System Utilities**
  - [`s-tui`](https://github.com/amanusk/s-tui): Monitorización de CPU basada en terminal con gráficas
  - [`intel-gpu-tools`](https://gitlab.freedesktop.org/drm/igt-gpu-tools): Útil para diagnósticos de GPU Intel

---

### Mejorado

- **Gestión de APT Upgrade**  
  La función de upgrade de PVE bloquea ahora el proceso si algún paquete pide confirmación manual. Esto evita upgrades parciales y asegura consistencia.

- **Optimización de Red (sysctl)**  
  - Parámetros de kernel obsoletos eliminados (p. ej. `tcp_tw_recycle`, `nf_conntrack_helper`) para prevenir warnings en **Proxmox 9 / kernel 6.14**
  - Ahora genera solo parámetros sysctl válidos y al día

- **Gestión de Patch de CPU AMD**  
  - Aplica ahora `idle=nomwait` correcto y opciones KVM (`ignore_msrs=1`, `report_ignored_msrs=0`)
  - El warning esperado está ahora documentado y gestionado con seguridad para estabilidad con Ryzen/EPYC

- **Fixes de Timezone y NTP**  
  - Detecta automáticamente la timezone usando geolocalización por IP pública
  - Fallback a UTC si la detección falla
  - Reinicia Postfix tras establecer la timezone → resuelve el warning de mismatch `/var/spool/postfix/etc/localtime`

- **Lógica del Repository & Package Installer**  
  - Verifica ahora que existan repositorios funcionales antes de instalar ningún paquete
  - Si no hay ninguno disponible, añade un repositorio **Debian stable** como fallback
  - Reemplaza el obsoleto `mlocate` por `plocate` (compatible con Debian 13 y Proxmox 9)

- **Logs y Feedback de usuario mejorados**  
  - Las acciones que fallan proporcionan ahora mensajes precisos (en lugar de marcarse falsamente como éxito)
  - Ayuda a los usuarios a entender claramente qué se ha aplicado o saltado



## 2025-08-06

### Nueva versión v1.1.4

### Añadido

- **Preparación de compatibilidad con Proxmox 9**  
  Esta versión prepara **ProxMenux** para el próximo **Proxmox VE 9**:
  - La función para añadir los repositorios oficiales de Proxmox soporta ahora el nuevo formato `.sources` usado en Proxmox 9, manteniendo retrocompatibilidad con Proxmox 8.
  - La eliminación de banner se soporta ahora opcionalmente para Proxmox 9.

- **Detección de xshok-proxmox**  
  Añadida una comprobación para detectar si el script post-install `xshok-proxmox` ya ha sido ejecutado.  
  Si se detecta, se muestra un warning para evitar ajustes conflictivos:

  ```
  It appears that you have already executed the xshok-proxmox post-install script on this system.

  If you continue, some adjustments may be duplicated or conflict with those already made by xshok.

  Do you want to continue anyway?
  ```

---

### Mejorado

- **Eliminación de banner (Proxmox 8.4.9+)**  
  Actualizada la lógica para eliminar el banner de suscripción en **Proxmox 8.4.9**, debido a cambios en `proxmoxlib.js`.

- **LXC Disk Passthrough (UUID persistente)**  
  La función para añadir un disco físico a un contenedor LXC usa ahora **paths persistentes basados en UUID**.  
  Esto asegura que los discos permanezcan correctamente montados, incluso si el orden `/dev/sdX` cambia por hardware nuevo.

  ```bash
  PERSISTENT_DISK=$(get_persistent_path "$DISK")
  if [[ "$PERSISTENT_DISK" != "$DISK" ]] ...
  ```

- **System Utilities Installer**  
  Comprueba ahora si las sources APT están disponibles antes de instalar las herramientas seleccionadas.  
  Si una nueva instalación de Proxmox no tiene repos activos, **añadirá automáticamente las sources por defecto** para evitar fallos de instalación.

- **Activación de IOMMU en sistemas ZFS**  
  La función que habilita IOMMU para passthrough verifica ahora los parámetros de kernel existentes para evitar duplicación si el usuario ya los ha configurado manualmente.

---

### Arreglado

- Limpieza de código menor y rendimiento de runtime mejorado en varios módulos.



## 2025-07-20

### Cambiado

- **Eliminación del banner de suscripción (Proxmox 8.4.5+)**  
  Mejorada la función `remove_subscription_banner` para asegurar compatibilidad con Proxmox 8.4.5, donde el método de eliminación de banner fallaba tras instalaciones limpias.

- **Detección de Log2RAM mejorada**  
  Tanto en los scripts post-install automático como personalizable, se ha mejorado la lógica para la instalación de Log2RAM.  
  Ahora detecta correctamente si Log2RAM ya está configurado y evita disparar errores o reconfiguración.

- **Instalación de Figurine optimizada**  
  La función `install_figurine` evita ahora duplicar entradas en `.bashrc` si la personalización del prompt root ya existe.


### Añadido

- **Nueva función: Nombrado persistente de interfaces de Red**  
  Añadida una nueva función `setup_persistent_network` para crear nombres de interfaz de red estables usando ficheros `.link` basados en direcciones MAC.  
  Esto evita renombrados impredecibles (p. ej. `enp2s0` convirtiéndose en `enp3s0`) cuando cambia el hardware, se reordena la topología PCI o se aplican configuraciones de passthrough.

  **¿Por qué usar ficheros `.link`?**  
  Porque los nombres predecibles de interfaz en `systemd` pueden cambiar con reordenamientos o reemplazos de hardware. Usar ficheros `.link` estáticos atados a direcciones MAC asegura consistencia, especialmente en sistemas con múltiples NICs o setups de passthrough.

  Gracias especiales a [@Andres_Eduardo_Rojas_Moya] por contribuir la función de nombrado  
  de red persistente y por la idea original.

```bash
[Match]
MACAddress=XX:XX:XX:XX:XX:XX

[Link]
Name=eth0
```


## 2025-07-01

### Nueva versión v1.1.3

![Installer Menu](https://macrimi.github.io/ProxMenux/install/install.png)

- **Dos modos de instalación para ProxMenux**  
  El installer ofrece ahora dos modos distintos:  
  1. **Versión Lite (sin traducciones):** Solo instala dos paquetes oficiales de Debian (`dialog`, `jq`) para habilitar menús y parsing JSON. No se escriben ficheros más allá del directorio de configuración.  
  2. **Versión Full (con traducciones):** Usa un virtual environment y permite seleccionar el idioma de interfaz durante la instalación.  

  Al actualizar, si el usuario cambia de full a lite, la versión vieja se **eliminará automáticamente** para una transición limpia.

### Añadido

- **Nuevo script: Setup automatizado de post-instalación**  
  Un nuevo script post-install minimal que realiza el setup esencial automáticamente:  
  - Upgrade y sync del sistema  
  - Eliminar el banner enterprise  
  - Optimizar APT, journald, logrotate, límites del sistema  
  - Mejorar gestión de kernel panic, ajustes de memoria, entropía, red  
  - Añadir tweaks a `.bashrc` y **auto-instalación de Log2RAM** (si se detecta SSD/M.2)

- **Nueva función: Configuración de Log2RAM**  
  Disponible ahora tanto en los scripts post-install personalizable como automático.  
  En sistemas con SSD/NVMe, Log2RAM se **habilita automáticamente** para preservar la vida del disco.

- **Nuevos menús:**
  - 🧰 **System Utilities Menu**  
    Permite a los usuarios seleccionar e instalar herramientas CLI útiles con validación de comando apropiada.
  - 🌐 **Network Configuration & Repair**  
    Un nuevo menú interactivo para analizar y reparar interfaces de red.

### Mejorado

- **Lógica del menú Post-Install**  
  Las opciones están ahora agrupadas más lógicamente para mejor usabilidad.

- **Menú VM Creation**  
  Mejorado con soporte mejorado de modelo de CPU y opciones custom.

- **Script UUP Dump ISO Creator**  
  - Añadida opción para **personalizar la ubicación de la carpeta temporal**  
  - Arreglado un issue donde se eliminaba la carpeta temp entera en lugar de solo el contenido  
    💡 Sugerido por [@igrokit](https://github.com/igrokit)  
    [#17](https://github.com/MacRimi/ProxMenux/issues/17), [#11](https://github.com/MacRimi/ProxMenux/issues/11)

- **Script Physical Disk to LXC**  
  Gestiona ahora **discos formateados con XFS** correctamente.  
  ¡Gracias a [@antroxin](https://github.com/antroxin) por reportar y testear!

- **System Utilities Installer**  
  Reescrito para **verificar la disponibilidad del comando** tras la instalación, asegurando que las herramientas funcionen como se espera.  
  🐛 Fix para [#18](https://github.com/MacRimi/ProxMenux/issues/18) por [@DST73](https://github.com/DST73)

### Arreglado

- **Habilitar IOMMU en ZFS**  
  La detección y configuración para habilitar IOMMU en sistemas basados en ZFS es ahora totalmente funcional.  
  🐛 Fix para [#15](https://github.com/MacRimi/ProxMenux/issues/15) por [@troponaut](https://github.com/troponaut)

### Otros

- Mejoras de rendimiento y limpieza de código en varios módulos.



## 2025-06-06

### Añadido

- **Nuevo menú: Proxmox PVE Helper Scripts**  
  Introducido oficialmente el nuevo menú **Proxmox PVE Helper Scripts**, reemplazando el anterior: Esenciales Proxmox.  
  Este nuevo menú incluye:
  - Búsqueda de script por nombre en tiempo real
  - Navegación basada en categoría

  Es una forma más limpia, rápida y funcional de acceder a los scripts de la comunidad en Proxmox.

  ![Helper Scripts Menu](https://macrimi.github.io/ProxMenux/menu-helpers-script.png)


- **Nuevos modelos de CPU en VM Creation**  
  El menú de selección de CPU en VM creation ha sido ampliado considerablemente para soportar perfiles avanzados de CPU QEMU y x86-64.  
  Esto permite mejor compatibilidad con sistemas guest modernos y fine-tuning del rendimiento para workloads específicos, incluyendo virtualización anidada y funciones asistidas por hardware.


  ![CPU Config](https://macrimi.github.io/ProxMenux/vm/config-cpu.png)

  Gracias a **@Nida Légé (Nidouille)** por sugerir esta mejora.


- **Soporte para imágenes de disco `.raw`**  
  La herramienta de import de disco para VMs soporta ahora ficheros `.raw`, además de `.img`, `.qcow2` y `.vmdk`.  
  Esto mejora la compatibilidad cuando se trabaja con exports de disco de otros hypervisors o herramientas de backup.

  💡 Sugerido por **@guilloking** en [GitHub Issue #5](https://github.com/MacRimi/ProxMenux/issues/5)


- **Detección de Locale al saltarse idiomas**  
  La función que deshabilita idiomas extra de APT incluye ahora:
  - Detección automática de locale (`LANG`)
  - Auto-generación de `en_US.UTF-8` si no se encuentra ninguno
  - Previene warnings durante ejecución de scripts debido a locale indefinido


### Mejorado

- **Lógica de saltado de idioma APT**  
  La gestión mejorada de locale asegura compatibilidad del sistema antes de deshabilitar traducciones:
  ```bash
  if ! locale -a | grep -qi "^${default_locale//-/_}$"; then
      echo "$default_locale UTF-8" >> /etc/locale.gen
      locale-gen "$default_locale"
  fi
  ```

- **Velocidad de System Update**  
  Los upgrades de sistema post-install son ahora más rápidos:  
  - El proceso de upgrade (`dist-upgrade`) está separado de las actualizaciones de índice de plantillas de contenedor.
  - El refresh de índice es ahora una función opcional seleccionada en el script.



## 2025-05-27

### Arreglado
- **URL de ISO de Kali Linux actualizada**  
  Arreglada la URL de descarga incorrecta para el ISO de Kali Linux en el módulo de instalador Linux. El nuevo path correcto es:  
  ```
  https://cdimage.kali.org/kali-2025.1c/kali-linux-2025.1c-installer-amd64.iso
  ```

### Mejorado
- **Transiciones de menú dialog más rápidas**  
  Mejorada la respuesta UI en todos los menús interactivos reemplazando `whiptail` por `dialog`, ofreciendo transiciones más rápidas y navegación más suave.

- **Soporte Coral USB en LXC**  
  Mejorada la lógica para configurar passthrough de Coral USB TPU en contenedores LXC:
  - Refactorizada la configuración en bloques modulares con mejor estructura y comentarios inline.
  - Separación clara de la lógica de Coral USB (`/dev/coral`) y Coral M.2 (`/dev/apex_0`).
  - Mantiene retrocompatibilidad con configuraciones LXC existentes.
  - Introducido passthrough Coral USB persistente usando una udev rule:
    ```bash
    # Create udev rule for Coral USB
    SUBSYSTEM=="usb", ATTRS{idVendor}=="18d1", ATTRS{idProduct}=="9302", MODE="0666", TAG+="uaccess", SYMLINK+="coral"
    
    # Map /dev/coral if it exists
    if [ -e /dev/coral ]; then
        echo "lxc.mount.entry: /dev/coral dev/coral none bind,optional,create=file" >> "$CONFIG_FILE"
    fi
    ```
  - Gracias especiales a **@Blaspt** por validar el passthrough Coral USB persistente y por sugerir el uso del symlink `/dev/coral`.


### Añadido
- **Soporte de passthrough Coral USB persistente**  
  Añadido soporte de udev rule para dispositivos Coral USB para mapearlos persistentemente como `/dev/coral`, habilitando passthrough consistente entre reboots. Este path se detecta y mapea automáticamente en la configuración del contenedor.

- **Integración de RSS Feed**  
  Añadido soporte para generar un RSS feed para el changelog, permitiendo a los usuarios mantenerse informados de updates a través de clientes de noticias.

- **Automatización del Release Service**  
  Implementado un nuevo servicio de gestión de release para automatizar la publicación y tagging de versiones, empezando con la versión **v1.1.2**.


## 2025-05-13

### Arreglado

- **Fix de startup en versiones recientes de Proxmox**\
  Arreglado un issue donde algunas instalaciones recientes de Proxmox carecían del directorio `/usr/local/bin`, causando errores al instalar el menú de ejecución. El script crea ahora el directorio si no existe antes de descargar el menú principal.\
  Gracias a **@danielmateos** por detectar y reportar este issue.

### Mejorado

- **Lógica de instalación de Lynis actualizada en Post-Install Settings**\
  La función `install_lynis()` se ha mejorado para instalar siempre la **última versión** de Lynis clonando el repositorio oficial de GitHub:
  ```
  https://github.com/CISOfy/lynis.git
  ```
  El proceso de instalación asegura ahora que siempre se obtenga la última versión y se enlace correctamente dentro del path del sistema.

  Gracias a **@Kamunhas** por reportar esta oportunidad de mejora.

- **Optimización de memoria equilibrada para sistemas con poca memoria**  
  Mejorados los ajustes de memoria por defecto para soportar mejor sistemas con RAM limitada. La configuración previa podía impedir que servidores de bajas specs arrancaran. Ahora se usa un conjunto más equilibrado de parámetros de kernel, y la compactación de memoria se habilita si el sistema la soporta.

  ```bash
  cat <<EOF | sudo tee /etc/sysctl.d/99-memory.conf
  # Balanced Memory Optimization
  vm.swappiness = 10
  vm.dirty_ratio = 15
  vm.dirty_background_ratio = 5
  vm.overcommit_memory = 1
  vm.max_map_count = 65530
  EOF

  # Enable memory compaction if supported by the system
  if [ -f /proc/sys/vm/compaction_proactiveness ]; then
    echo "vm.compaction_proactiveness = 20" | sudo tee -a /etc/sysctl.d/99-memory.conf
  fi

  # Apply settings
  sudo sysctl -p /etc/sysctl.d/99-memory.conf
  ```

  Estos valores ayudan a mantener la capacidad de respuesta y la estabilidad del sistema incluso en condiciones de memoria constreñidas.

  Gracias a **@chesspeto** por señalar este issue y ayudar a refinar la optimización.


## 2025-05-04

### Añadido
- **Menú interactivo Help & Info**  
  Añadido un nuevo script llamado `Help and Info`, que proporciona un menú interactivo de referencia de comandos para Proxmox VE a través de una interfaz basada en dialog.  
  Esta herramienta ofrece a los usuarios una forma rápida de navegar y copiar comandos útiles para gestionar y mantener su servidor Proxmox, todo en una ubicación centralizada.

  ![Help and Info Menu](https://macrimi.github.io/ProxMenux/help/help-info-menu.png)

  *Figura 1: Menú interactivo de referencia de comandos Help and Info.*

- **Uninstaller para utilidades Post-Install**  
  Se ha añadido un nuevo script al menú **Post-instalación**, permitiendo a los usuarios desinstalar utilidades o paquetes que se instalaron previamente a través del script post-install.

### Mejorado
- **Menú de selección de utilidades en el script de Post-instalación**  
  La sección `Install Common System Utilities` incluye ahora un menú donde los usuarios pueden elegir qué utilidades instalar, en lugar de instalar todas por defecto. Esto da más control sobre lo que se añade al sistema.

- **Detección de PV Header antiguo y auto-fix**  
  Tras actualizar el sistema, el script post-update incluye ahora una comprobación de seguridad para discos físicos con headers LVM PV (Physical Volume) obsoletos.  
  Este issue puede ocurrir cuando las máquinas virtuales tienen acceso passthrough a discos y modifican involuntariamente la metadata del volumen. El script detecta y actualiza ahora automáticamente estos headers.  
  Si ocurre algún error durante el proceso, se muestra un warning al usuario.

- **Traducciones más rápidas en menús**  
  Varios menús de post-instalación con auto-traducciones se han optimizado para reducir tiempos de carga y mejorar la experiencia de usuario.


## 2025-04-14

### Añadido
- **Nuevo script: Disk Passthrough a un CT**
Introducido un nuevo script que permite asignar un disco físico dedicado a un contenedor (CT) en Proxmox VE.
Esta utilidad lista los discos físicos disponibles (excluyendo los discos de sistema y montados), permite al usuario seleccionar un contenedor y un disco, y luego formatea o reutiliza el disco antes de montarlo dentro del CT en un path especificado.
Soporta detección de filesystems existentes y asegura que los permisos estén correctamente configurados. Ideal para casos de uso como contenedores Samba, Nextcloud, o de videovigilancia.

### Mejorado  
- Identificación visual de discos para passthrough a VMs
Mejorada la lógica de detección de discos en el script Disk Passthrough a una VM incluyendo indicadores visuales y metadata.
Los discos muestran ahora tags como ⚠ In use, ⚠ RAID, ⚠ LVM, o ⚠ ZFS, facilitando reconocer su estado actual de un vistazo. Esto ayuda a prevenir errores de selección y mejora la claridad para el usuario.

## 2025-03-24  
### Mejorado  
- Mejorada la lógica para detectar discos físicos en el script **Disk Passthrough a una VM**. Anteriormente, el script mostraba en algunos setups discos que ya estaban montados en el sistema. Esta actualización asegura que solo se muestren discos no montados en Proxmox, previniendo confusión y conflictos potenciales.  

- Esta mejora asegura que los discos ya montados o asignados a otras VMs se excluyan de la lista de discos disponibles, proporcionando un proceso de selección más preciso y fiable.

## [1.1.1] - 2025-03-21
### Mejorado
- Mejorada la lógica del script post-install para prevenir sobrescribir o añadir ajustes duplicados si ajustes similares ya están configurados por el usuario.
- Añadida una nota de warning a la documentación explicando que usar diferentes scripts post-instalación no se recomienda para evitar conflictos y ajustes duplicados.

### Añadido
- **Crear VM Synology DSM**:  
  Un nuevo script que crea una VM para instalar Synology DSM. El script automatiza el proceso de descargar tres loaders distintos con la opción de usar un loader custom proporcionado por el usuario desde las opciones de almacenamiento local.  
  Además, permite el uso tanto de discos virtuales como físicos, que son asignados automáticamente por el script.  

  ![VM description](https://macrimi.github.io/ProxMenux/vm/synology/dsm_desc.png)
  
  *Figura 1: Resumen del setup de la VM Synology DSM.*

- **Nuevo menú VM Creation**:  
  Se ha creado un nuevo menú para habilitar la creación de VM desde plantillas o scripts custom.

- **Actualización del menú principal**:  
  Añadida una nueva entrada al menú principal para acceder al menú de creación de VM desde plantillas o scripts.

## 2025-03-06
### Añadido
- Completada la sección de documentación web para ampliar la información sobre scripts actualizados.

## [1.1.0] - 2025-03-04
### Añadido
- Creado un script post-install personalizable para Proxmox con 10 secciones y 35 opciones seleccionables distintas.

## [1.0.7] - 2025-02-17
### Añadido
- Creado un menú con scripts esenciales de la comunidad Proxmox VE Helper-Scripts.

## [1.0.6] - 2025-02-10
### Añadido
- Añadido soporte de traducción en tiempo real usando Google Translate.
- Modificados los scripts existentes para soportar múltiples idiomas.
- Actualizado el script de instalación para instalar y configurar:
  - `jq` (para gestionar datos JSON)
  - Python 3 y virtual environment (requerido para traducciones)
  - Google Translate (`googletrans`) (para soporte multi-idioma)
- Introducido soporte para los siguientes idiomas:
  - English
  - Spanish
  - French
  - German
  - Italian
  - Portuguese
- Creado un script de utilidad para funciones auxiliares que soportan la ejecución de menús y scripts.

## [1.0.5] - 2025-01-31
### Añadido
- Añadido el script **Repair Network**, que incluye:
  - Verify Network
  - Show IP Information
- Creado el **Network Menu** para gestionar funciones relacionadas con la red.

## [1.0.4] - 2025-01-20
### Añadido
- Creado un script para añadir un disco passthrough a una VM.
- Creado el **Storage Menu** para gestionar funciones relacionadas con almacenamiento.

## [1.0.3] - 2025-01-13
### Añadido
- Creado un script para importar imágenes de disco en una VM.

## [1.0.2] - 2025-01-09
### Modificado
- Actualizado el **script de configuración de Coral TPU** para:
  - Incluir también el setup de Intel iGPU.
  - Instalar drivers de GPU para aplicaciones de videovigilancia para soportar VAAPI y QuickSync.
- Añadida una función para **desinstalar ProxMenux**.

## [1.0.1] - 2025-01-03
### Añadido
- Creado un script para añadir **soporte Coral TPU en un LXC** para uso en programas de videovigilancia.

## [1.0.0] - 2024-12-18
### Añadido
- Release inicial de **ProxMenux**.
- Creado un script para añadir **drivers Coral TPU** a Proxmox.
