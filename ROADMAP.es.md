# <img src="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo.png" alt="ProxMenux logo" width="40"/>   ProxMenux — Roadmap

> Última actualización: **2026-05-20** · Versión actual: **1.2.1.2-beta**
> 🇬🇧 English version: [ROADMAP.md](ROADMAP.md)

Este documento es la hoja de ruta para llevar ProxMenux y
ProxMenux Monitor a un estado **listo para producción**. Está basado
en las dos infografías que un colaborador preparó y enriquecido con
una auditoría real del código actual.

## 🖼️ Infografías de origen

Las dos infografías son obra de
**[@pitiriguisvi](https://github.com/pitiriguisvi)** y resumen
visualmente las dos grandes áreas de trabajo — gracias por dedicarle
el tiempo:

| ProxMenux Monitor (Dashboard) | ProxMenux (Scripts) |
|---|---|
| <img src="images/proxmenux_phases_1.png" alt="Fases ProxMenux Monitor" width="380"/> | <img src="images/proxmenux_phases_2.png" alt="Fases ProxMenux" width="380"/> |
| *Mejoras recomendadas para hacerlo más seguro, útil y apto para producción* | *Mejoras recomendadas para hacerlo más seguro, auditable y apto para producción* |

**¿Qué se muestra?:**

* La tabla **Estado actual** refleja lo que YA existe hoy.
* El **Plan por versión** marca qué entra en cada release.
* La sección **Cambios publicados** se va rellenando a medida que
  se cierren items, con la versión en la que se entregó.

Símbolos:

* 🟢 — Hecho y en producción
* 🟡 — Parcial (existe la base, falta UI o feature completa)
* 🔴 — Pendiente

---

## 🎯 Visión

> *"La prioridad no es añadir más métricas ni más scripts, sino mejorar
> seguridad, alertas, permisos, auditabilidad e integración real con
> Proxmox."*

ProxMenux ya es una herramienta para gestionar los nodos. El siguiente salto es convertirlo en una
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
| Último backup por VM/LXC | 🔴 | No se muestra en ningún sitio; tampoco hay integración con PBS para listar/consultar backups |
| VMs sin backup y jobs fallidos | 🟡 | Detección **pasiva** de líneas `vzdump .* finished` en syslog (notificación), pero **no hay vista** de "VMs sin job de backup" ni integración con la API de jobs de PVE |
| Quorum, nodos, estado global | 🟡 | Detección **pasiva** de `quorum lost` / `split brain` en syslog. **No hay** panel de cluster ni consulta activa a la API (`pvecm status`, `/cluster/status`) |
| Dashboard de salud del entorno | 🔴 | El Health tab es del **nodo local**. No existe vista multi-nodo del cluster |

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


## 📦 Cambios publicados

> Esta sección se actualiza con cada release.
> Aquí se anota qué pasó de pendiente (🔴 / 🟡) a hecho (🟢)
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

Cualquier persona puede:

* Comentar en el item que considere prioritario o que falte.
* Proponer un nuevo item con el formato de la tabla
  (categoría + descripción + por qué importa).
* Sugerir mover items entre versiones si el orden no encaja con
  su uso real.

El roadmap es vivo y se reordena. La única regla es: **los items
solo cambian de estado 🔴/🟡 → 🟢 cuando hay código que los respalda
en una release publicada**.
