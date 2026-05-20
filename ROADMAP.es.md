# <img src="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo.png" alt="ProxMenux logo" width="40"/>   ProxMenux — Roadmap

> Última actualización: **2026-05-20** · Versión actual: **1.2.1.2-beta**
> 🇬🇧 English version: [ROADMAP.md](ROADMAP.md)

Este documento es nuestra hoja de ruta para llevar ProxMenux y
ProxMenux Monitor a un estado **listo para producción**. Está basado
en las dos infografías que un colaborador preparó y enriquecido con
una auditoría real del código actual.

## 🖼️ Infografías de origen

Las dos infografías que sirvieron de punto de partida son obra de
**[@pitiriguisvi](https://github.com/pitiriguisvi)** y resumen
visualmente las dos grandes áreas de trabajo — gracias por dedicarle
el tiempo y darnos un punto de partida tan claro:

| ProxMenux Monitor (Dashboard) | ProxMenux (Scripts) |
|---|---|
| <img src="images/proxmenux_phases_1.png" alt="Fases ProxMenux Monitor" width="380"/> | <img src="images/proxmenux_phases_2.png" alt="Fases ProxMenux" width="380"/> |
| *Mejoras recomendadas para hacerlo más seguro, útil y apto para producción* | *Mejoras recomendadas para hacerlo más seguro, auditable y apto para producción* |

**Cómo lo usamos:**

* La tabla **Estado actual** refleja lo que YA tenemos hoy.
* El **Plan por versión** marca qué entra en cada release.
* La sección **Cambios publicados** se va rellenando a medida que
  cerramos items, con la versión en la que se entregó.

Símbolos:

* 🟢 — Hecho y en producción
* 🟡 — Parcial (existe la base, falta UI o feature completa)
* 🔴 — Pendiente

---

## 🎯 Visión

> *"La prioridad no es añadir más métricas ni más scripts, sino mejorar
> seguridad, alertas, permisos, auditabilidad e integración real con
> Proxmox."*

ProxMenux ya es una herramienta potente para administradores que
gestionan su propio nodo. El siguiente salto es convertirlo en una
herramienta **apta para entornos de producción y para clientes**:

* El operador tiene que poder dar **acceso de solo lectura** a
  terceros sin miedo a que toquen nada.
* Tiene que existir un **historial auditable** de qué pasó y quién
  lo hizo.
* Los cambios destructivos tienen que poder **previsualizarse y
  revertirse**.
* La instalación tiene que poder operarse en **modo conservador**
  cuando el nodo no es un laboratorio.

---

## 📊 Estado actual

### ProxMenux Monitor (Dashboard)

#### 1️⃣ Modo solo lectura
| Item | Estado | Notas |
|---|---|---|
| Separar monitorizar de controlar | 🔴 | El dashboard mezcla ambos hoy |
| Dashboard 100 % read-only | 🟡 | El scope `read_only` existe en los API tokens, falta exponerlo al usuario web |
| Sin acciones de start/stop por defecto | 🔴 | Requiere lo anterior |
| Ideal para clientes y producción | 🔴 | Llega cuando el modo solo lectura esté completo |

#### 2️⃣ Permisos y tokens
| Item | Estado | Notas |
|---|---|---|
| Roles viewer / operator / admin | 🔴 | Single-user hoy |
| Tokens con scopes | 🟡 | 2 scopes (`read_only`, `full_admin`), no granulares |
| Caducidad configurable | 🟡 | Hoy fija en 365 días |
| Tokens de solo lectura para NA / homepage | 🟢 | Cubierto por `scope=read_only` |

#### 3️⃣ Seguridad web
| Item | Estado | Notas |
|---|---|---|
| Bind a localhost o LAN | 🔴 | El backend escucha en `0.0.0.0:8008` |
| HTTPS y proxy inverso guiado | 🟢 | Documentado, ACME + self-signed CA trust |
| Allowlist IP opcional | 🔴 | No existe |
| Rate limits y bloqueo anti-fuerza bruta | 🟡 | Hay cooldown en login; no es un panel configurable. Fail2Ban es opcional |

#### 4️⃣ Logs y auditoría
| Item | Estado | Notas |
|---|---|---|
| Registrar login, logout e intentos fallidos | 🟡 | Se notifica `auth_fail`; no hay panel histórico |
| Guardar IP, usuario y token usado | 🟡 | Llega a notificación, no se persiste para auditar |
| Auditar accesos sobre VM/LXC | 🔴 | Las acciones de control no se registran |
| Historial claro con resultado y error | 🔴 | No hay pestaña "Audit" |

#### 5️⃣ Alertas útiles
| Item | Estado | Notas |
|---|---|---|
| CPU, RAM, disco y temperatura altos | 🟢 | Health Monitor + thresholds configurables |
| Snapshot / backup confirmado | 🟢 | Eventos `vzdump_complete` |
| SMART warnings y predicción | 🟢 | `disk_failure_predicted` + tiers de `disk_io_error` (1.2.1.2) |
| Telegram, Gotify, ntfy, email, webhook | 🟢 | 7 canales activos |

#### 6️⃣ PBS y cluster
| Item | Estado | Notas |
|---|---|---|
| Último backup por VM/LXC | 🟢 | Visible en el modal de cada VM/CT |
| VMs sin backup y jobs fallidos | 🟡 | `vzdump_failed` se notifica; falta una vista agregada |
| Quorum, nodos, estado global | 🟢 | Health tab + eventos de cluster |
| Dashboard de salud del entorno | 🟢 | Health tab |

---

### ProxMenux (Scripts y Post-install)

#### 1️⃣ Seguridad operativa
| Item | Estado | Notas |
|---|---|---|
| Dry-run / previsualización antes de aplicar | 🔴 | No existe como flag general |
| Avisos delante de cambios críticos | 🟡 | Algunos diálogos, no uniforme |
| Verificación posterior de la acción | 🟡 | `update_component_status` registra el resultado |
| Confirmación reforzada en tareas sensibles | 🟡 | Hay `whiptail --yesno` en algunos scripts; no es regla |

#### 2️⃣ Rollback y recuperación
| Item | Estado | Notas |
|---|---|---|
| Restaurar última configuración válida | 🟢 | Sistema `backup_restore/` completo (host backup + `apply_pending_restore`) |
| Menú de recuperación antes de fallos | 🟡 | Existe el restore manual, falta un wizard preventivo |
| Revertir red / postinstall / grupos | 🟡 | El backup snapshotea, no hay rollback granular por subsistema |
| Empaquetado para diagnóstico (`bug-report`) | 🔴 | No existe el bundle |

#### 3️⃣ Scripts externos
| Item | Estado | Notas |
|---|---|---|
| Listas, hashes y firma | 🔴 | Se ejecutan sin verificación |
| Fijar versión / commit / hash | 🔴 | Helper-scripts traídos en vivo del upstream |
| Etiquetar nivel de riesgo | 🟡 | El menú nuevo añadió "richer context"; falta etiqueta formal |
| Mostrar script antes de ejecutarlo | 🔴 | Sin paso de preview |

#### 4️⃣ Logs y trazabilidad
| Item | Estado | Notas |
|---|---|---|
| Registrar acción, usuario y fecha | 🟡 | Logs en `/var/log/proxmenux/`, no estructurados |
| Guardar comandos y archivos modificados | 🔴 | No hay tracking de qué tocó cada script |
| Errores claros con código de salida | 🟡 | Algunos scripts sí; no es regla |
| Historial de cambios reciente | 🔴 | No hay UI "qué hizo ProxMenux en este host" |

#### 5️⃣ Modo producción
| Item | Estado | Notas |
|---|---|---|
| Perfil conservador para todo el nodo | 🔴 | El concepto no existe |
| Bloquear acciones destructivas por defecto | 🔴 | Tampoco |
| Limitar cambios de red sin confirmación | 🟡 | Algunos scripts piden confirmación |
| Más validaciones y avisos | 🟡 | Mejoras incrementales, no como modo |

#### 6️⃣ Entornos reales
| Item | Estado | Notas |
|---|---|---|
| Salida tipo "esto pasó" clara y multilingüe | 🟡 | `translate()` + `msg_*` funcionan; falta resumen final |
| Visibilidad de quorum / almacenamiento | 🔴 | El Monitor lo muestra, pero los **scripts** no inspeccionan ni reportan el estado de quorum/almacenamiento antes de actuar |
| Postinstall Proxmox Backup Server | 🔴 | No existe un script de instalación/configuración de PBS (sí existe el `Proxmox_Backup_Client.AppImage` que es el cliente, no el servidor) |
| Detector de fallos rápido para escenarios | 🟡 | Health Monitor; falta "preflight" antes de cada cambio |

---

## 🗺️ Plan por versión

> Los items se agrupan por relación **valor / esfuerzo**, no por
> orden estricto. El plan se puede reordenar según feedback de
> testers del grupo.

### v1.2.2-beta — *Lo barato y de alto impacto*

Objetivo: cerrar los huecos que ya tienen base en el código y dan
mejora visible de seguridad sin tocar arquitectura.

* [ ] **Modo solo lectura del usuario web.** Bindeo del scope
      `read_only` ya existente del JWT a la sesión interactiva. La
      UI esconde los botones de acción (start/stop, ejecutar
      scripts, terminal) cuando el scope no es `full_admin`.
* [ ] **Tabla de audit log + pestaña en el dashboard.** Nueva tabla
      SQLite `audit_log(ts, user, ip, action, target, result, error)`.
      Hookear desde `flask_security_routes` y `flask_script_runner`.
      Render simple en una pestaña "Audit".
* [ ] **Allowlist IP.** Campo nuevo en `Settings → Security →
      "Limitar acceso a estas IPs"`. Decorator `@require_allowed_ip`
      aplicado a todas las blueprints.
* [ ] **Caducidad configurable de tokens API.** Campo `expires_at`
      en la metadata del token; honrarlo en `verify_token`.

### v1.2.3-beta — *Lo medio*

Objetivo: dar herramientas serias de operación antes de aplicar
cambios.

* [ ] **Tokens con scope granular.** Mínimo cuatro: `read_only`,
      `vm_control`, `script_runner`, `full_admin`. El frontend
      enseña qué scopes tiene el token actual.
* [ ] **Dry-run en scripts post-install.** Flag `--dry-run`
      compatible con todos los scripts de `scripts/post_install/`.
      La salida muestra exactamente qué cambiaría sin tocar el host.
* [ ] **Bundle de diagnóstico (`proxmenux bug-report`).** Comprime
      `/var/log/proxmenux/`, `journalctl -u proxmenux-monitor`,
      `dmesg --since=24h`, `dpkg -l | grep -i proxmenux`,
      `managed_installs.json` y los `errors`/`disk_observations` de
      la base de datos en un único `.tar.gz`. Output ofuscado de
      tokens y secrets.
* [ ] **Vista agregada "VMs sin backup".** Una nueva tarjeta en el
      tab de Backups que liste todas las VM/CT sin job de backup
      reciente, con accesos directos al PBS.

### v1.3.0 — *Lo grande*

Objetivo: el salto a producción. Requiere release mayor por cambios
de modelo de datos y de UX.

* [ ] **RBAC con roles viewer / operator / admin.** Multi-usuario,
      contraseña por usuario, role por sesión. Migración de
      `auth.json` a tabla `users(id, username, password_hash, role,
      created_at, last_login)`. Revisión de todas las blueprints para
      mapear endpoints → role mínimo.
* [ ] **Modo producción.** Flag global en `/etc/proxmenux/profile`
      que conmuta:
  * Confirmaciones reforzadas
  * Anti-cascade más agresivo
  * Acciones destructivas ocultas o deshabilitadas
  * Allowlist IP forzada a no-vacía
  * Tokens `full_admin` deshabilitados en favor de `vm_control` + ack
* [ ] **Rollback granular por subsistema.** Sobre la infraestructura
      `backup_restore` existente, permitir revertir solo "Red", solo
      "Post-install", solo "Grupos y permisos", etc.
* [ ] **Historial de cambios visible en el Monitor.** Pestaña
      "Changes" que liste cada modificación que ProxMenux hizo sobre
      el host (archivo, antes / después, script responsable).

### Probablemente fuera de scope

* **Firma criptográfica de scripts upstream.** Depende del
  comportamiento de community-scripts (no controlamos su pipeline).
  Mantener un mirror firmado propio sería mucho trabajo para poco
  beneficio. Cerrado salvo decisión externa.

---

## 📦 Cambios publicados

> Esta sección se actualiza con cada release. Sin tocar el plan de
> arriba: aquí se anota qué pasó de pendiente (🔴 / 🟡) a hecho (🟢)
> y en qué versión.

| Fecha | Versión | Item | Notas |
|---|---|---|---|
| — | — | — | Aún no hay items cerrados de este roadmap |

---

## 🙏 Agradecimientos

* **[@pitiriguisvi](https://github.com/pitiriguisvi)** — autor de las
  dos infografías originales sobre las que se construye este roadmap.

---

## 💬 Cómo aportar

Cualquier persona del grupo puede:

* Comentar en el item que considere prioritario o que falte.
* Proponer un nuevo item con el formato de la tabla
  (categoría + descripción + por qué importa).
* Sugerir mover items entre versiones si el orden no encaja con
  su uso real.

El roadmap es vivo y se reordena. La única regla es: **los items
solo cambian de estado 🔴/🟡 → 🟢 cuando hay código que los respalda
en una release publicada**.
