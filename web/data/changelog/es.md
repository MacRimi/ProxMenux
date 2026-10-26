## 2026-10-26

### Nueva versión ProxMenux v1.2.7

ProxMenux 1.2.7 incorpora dos herramientas nuevas. **Audit & Report** (Auditoría e informes), una página nueva en Admin de ProxMenux Monitor, documenta un nodo Proxmox, lo evalúa frente a cuarenta y tres comprobaciones e imprime el resultado como un informe que puedes entregar a otra persona, junto a un registro de todo lo que el propio ProxMenux ha cambiado en el host. **OCI manager Apps**, una entrada nueva del menú principal, instala aplicaciones directamente desde sus imágenes oficiales de contenedor como contenedores LXC nativos de Proxmox, sin ningún motor Docker: un catálogo de 464 aplicaciones, aplicaciones multicontenedor como Immich, Nextcloud y Paperless, perfiles de aceleración por hardware, actualizaciones que conservan los datos y recuperación tras una restauración o en otro host, todo ello gestionable también desde el Monitor.

A su alrededor: una **búsqueda en el menú principal** entre las opciones de ProxMenux, las aplicaciones OCI y los Helper-Scripts, **ProxMenux en Proxmox Backup Server**, los **trabajos de backup de VM y CT** gestionados desde ProxMenux, tokens de API de solo lectura que solo pueden leer, notificaciones escritas en el idioma de quien las lee, aplicaciones Docker registradas con su propia identidad, un historial de discos que sigue a cada disco por su número de serie y una larga lista de mejoras en backups, notificaciones, el Monitor, el instalador y las traducciones, en ocho idiomas.

Esta versión reúne todo lo que aportaron las betas 1.2.6.1 y 1.2.6.2. Un agradecimiento especial a [@Vaso73](https://github.com/Vaso73), [@f3rs3n](https://github.com/f3rs3n) y [@jcastro](https://github.com/jcastro). Entre los tres aportaron más de cien pull requests durante este ciclo: instalaciones reales comparadas con sus originales de Docker, ProxMenux en Proxmox Backup Server, registros privados y operaciones más rápidas en OCI manager, correcciones en el Monitor, los backups y las notificaciones, una revisión de cientos de mensajes para que cada uno diga exactamente lo que ha pasado, la documentación revisada en todos los idiomas, y el eslovaco y el italiano de todo lo nuevo. Sus pruebas y su depuración son en gran parte la razón de que esta versión esté disponible.

---

## 🔎 Audit & Report — una página nueva en Admin

La página reúne tres vistas, y todas ellas solo leen: una evaluación nunca modifica el host.

**Evaluación** analiza el nodo y enumera lo que encuentra. **Cambios** muestra lo que ProxMenux le ha hecho. **Política** es donde declaras lo que se supone que debe ser el host, que es lo que convierte una descripción en un juicio.

### La evaluación

- **Cuarenta y tres comprobaciones específicas de Proxmox** en backup, sistema, guests, seguridad, almacenamiento, red y hardware. Entre ellas: qué guests no cubre ningún trabajo de backup habilitado y qué antigüedad tienen los backups que realmente guardan los destinos; si Proxmox Backup Server verificó el backup más reciente de cada guest; cómo terminaron las ejecuciones de backup registradas; el espacio *y los inodos* de los sistemas de archivos que necesita el propio nodo; la integridad de los pools ZFS y los contadores de errores de los dispositivos; la redundancia del RAID por software y de multipath; el veredicto del propio Ceph; el quórum del clúster y los enlaces corosync que lo sostienen; la alta disponibilidad allí donde el quórum no puede responder; las particiones EFI que arrancarían el kernel; los servicios esenciales y las unidades que systemd dio por perdidas; la validez de los certificados; cómo admite SSH a root; la cadena de actualizaciones; y si funcionan los propios canales que te avisarían.
- **Cada hallazgo lleva la evidencia en la que se basa** — la salida del comando o el fragmento de configuración — junto con lo que examina la comprobación y de dónde procede la lectura. La evidencia se presenta en tablas y valores etiquetados, con nombres de campo legibles y cifras formateadas según lo que son: los bytes como tamaño, las horas como duración, un instante como fecha en tu propia configuración regional.
- **Seis resultados, cada uno con una definición que tiene que ganarse.** *Crítico* es una interrupción o una amenaza urgente para la disponibilidad, la integridad o la recuperabilidad, con evidencia. *Advertencia* es una degradación verificada, una protección esperada que no está o una política declarada que no se cumple. *Observación* es configuración, un límite o información de planificación. *Conforme* significa que el criterio se verificó y se cumple. *Sin verificar* significa que no había información suficiente para concluir. *No aplicable* significa que no había nada que evaluar.
- **Una comprobación que no se pudo evaluar dice qué no pudo leer** — el destino que rechazó la conexión, el comando que falló — junto al resultado, en lugar de en dos paneles plegados debajo de él. La falta de evidencia nunca cuenta como un resultado favorable.
- **La gravedad pertenece a la situación, no a la comprobación.** Un almacenamiento al 90 % de su capacidad y un almacenamiento inaccesible salen de la misma comprobación y ya no comparten gravedad; un hallazgo toma la gravedad más alta de los objetos sobre los que informa.
- **Los riesgos aceptados** se registran sobre un hallazgo con un motivo obligatorio y un periodo de revisión opcional. La clasificación técnica se mantiene y la decisión queda a su lado, de modo que un informe sigue mostrando que un hallazgo crítico se aceptó y quién lo aceptó. Cuando termina el periodo, el hallazgo vuelve al conjunto activo.
- **Un riesgo aceptado puede llevar una fecha de revisión sin caducidad** ([#343](https://github.com/MacRimi/ProxMenux/discussions/343), con [@Vaso73](https://github.com/Vaso73)): la decisión sigue vigente y vuelve para que se revise.
- **La evaluación describe con precisión sus propios efectos** ([PR #352](https://github.com/MacRimi/ProxMenux/pull/352), aportado por [@f3rs3n](https://github.com/f3rs3n)), y la eliminación de Lynis dice lo que ha pasado ([PR #404](https://github.com/MacRimi/ProxMenux/pull/404)).
- **Lynis se lee, no se reimplementa.** Sus advertencias conservan sus identificadores de prueba y se agrupan en una fila por cada advertencia distinta, con el número de veces que se emitió. Si Lynis está instalado pero no tiene un informe utilizable, la evaluación ofrece ejecutar uno antes de empezar, así que la decisión de invertir ese minuto es tuya.
- Los hallazgos guardan la identidad de su mensaje y sus valores en lugar de una frase ya redactada, de modo que un informe se lee en el idioma de quien lo abre.

### Cambios — lo que ProxMenux hizo en este host

La queja que más pesa contra una herramienta como esta no es que cambie cosas: es que después nadie sabe decir qué cambió. Leer el script tampoco lo resuelve — una función de cuatrocientas líneas puede alterar dos valores, y quien la lee no tiene forma de saber cuáles.

- **Tres bloques responden a las tres preguntas que de verdad se hace un administrador**: qué dejó configurado la post-instalación, qué scripts de ProxMenux escribieron en el host y qué cambió cada uno, y qué paquetes y utilidades hay ahora instalados. Cada entrada indica el script del que procede, así que un cambio se puede rastrear hasta el menú que lo hizo.
- **Solo se muestra el cambio.** `optimize_logrotate` se lee como `rotate 7` → `rotate 14`, no como cuarenta líneas de shell. Lo que se sustituyó se guarda en un almacén de contenido indexado por digest, así que sobrevive a que alguien ordene `/etc`.
- **Lo que se cambió se separa de lo que se ejecutó.** Una función que reescribe un archivo es la autora de ese cambio; una actualización lanzada desde un menú no lo es — apt decidió qué cambiaba. Ambas cosas se registran, en clases distintas, y la interfaz lo indica.
- **Cada entrada indica hasta qué punto se conoce el estado anterior**: capturado en el momento, capturado al volver a aplicarse sobre un host ya modificado, o nunca capturado porque es anterior al registro. Cada entrada declara además con qué exactitud podría deshacerse: exacta, parcial o de ninguna manera.
- **Las instalaciones registran la diferencia que produjeron**, no el nombre que se pidió: los paquetes que no estaban y ahora están, dependencias incluidas.
- **El registro muestra el host tal como está ahora**, no un log de cada vez que se ejecutó un script. Volver a ejecutar la post-instalación, pasar entre los canales estable y beta o reinstalar una utilidad actualiza la entrada existente en su sitio, con el estado de origen a un lado y el estado actual al otro.
- **Registrar nunca cuesta una operación.** Un pequeño archivo JSON escrito entero en una cola que el Monitor consolida: sin base de datos, sin Python y sin red en el lado que escribe. Si el registro no se puede escribir en absoluto, el cambio se hace igualmente.
- **La post-instalación personalizable aparece con su propia opción.** Figurine, Fastfetch y las demás opciones aplicadas desde ese menú aparecen en la sección de post-instalación con su nombre, junto a las de la post-instalación automática.
- El registro tiene su propia sección en el informe imprimible, que es donde defiende a un host.

### Política — declarar lo que se espera

- **Una evaluación puede ver lo que hace un host, no para qué sirve.** Si un guest necesita backup, si un servicio debe volver a arrancar por sí solo, si un almacenamiento es esencial: nada de eso se puede descubrir, y adivinarlo convierte configuraciones normales en alarmas. Un host sin nada declarado produce un informe completo que describe en lugar de juzgar.
- **Declarar es elegir entre lo que hay.** Los guests y los almacenamientos se listan a partir del inventario de este nodo, en lugar de escribirse por su identificador. Por guest: si se exige un backup, si se espera que arranque con el host y un objetivo de recuperación en horas cuando la carga de trabajo lo tiene. Por almacenamiento: esencial, opcional o sin especificar. Además, cada umbral con el que miden las comprobaciones, cada uno con el valor de serie como texto de ejemplo: dejar un campo vacío conserva ese valor.
- **La herencia es explícita.** *Heredar* muestra el valor predeterminado del sitio y elimina la excepción por recurso; *Sin especificar* se guarda como tal, así que no puede reactivar en silencio un requisito heredado.
- **Un guest exento sigue visible**, con la decisión que lo sacó del recuento: *excluido por política*, que es algo distinto de un riesgo aceptado. El informe indica también qué política aplicó, así que dos informes del mismo host — uno medido frente a expectativas declaradas y otro frente a ninguna — ya no se leen igual.

### Qué ha cambiado desde la última vez

- **Una evaluación tiene ahora un antes.** Cualquier ejecución puede marcarse como referencia, y cada una de las siguientes se lee frente a ella.
- **Corregido no es lo mismo que aceptado.** Un hallazgo que dejó de aparecer porque el host cambió y otro que dejó de aparecer porque alguien aceptó el riesgo salen ambos de la lista, y solo el primero es un avance. Se cuentan por separado.
- **La comparación dice hacia dónde se movió un hallazgo** ([#343](https://github.com/MacRimi/ProxMenux/discussions/343), con [@Vaso73](https://github.com/Vaso73)): peor, mejor o igual, en la vista y en el informe impreso.
- **Una comprobación que desaparece se indica como ya no evaluada**, no como resuelta: nada verificó que dejara de fallar, solo que se dejó de preguntar.

### Informes

- **Un informe responde a una pregunta**, así que el perfil selecciona tanto las comprobaciones que se ejecutan como las secciones que lleva el documento: *Auditoría completa*, *Inventario*, *Revisión de seguridad*, *Garantía de backups*, *Capacidad y desgaste* y *Diagnóstico rápido*. Cada informe específico empieza con su propia cabecera de situación. Las secciones que un perfil no pidió no aparecen, en lugar de aparecer vacías, para que una omisión nunca se lea como un resultado.
- **El documento describe el nodo antes de juzgarlo.** Primero van la identidad, el clúster, la arquitectura, los discos, la red, el almacenamiento, los guests, el passthrough y el software gestionado; después vienen los hallazgos, porque un hallazgo sobre un bridge significa poco para un lector al que no se le ha mostrado ese bridge.
- **Los diagramas recogen las relaciones, no las listas**: el procesador y la memoria en sus slots y lo que cuelga de cada controlador; el camino desde el cable hasta cada guest a través del adaptador, el bond y el bridge; dónde viven los discos de los guests y qué destino hace su backup; la pertenencia al clúster sobre los enlaces corosync que lo unen. Todos los diagramas son SVG en línea, así que se imprimen como vectores y el documento sigue siendo autónomo.
- **Diagnóstico rápido recoge solo lo que pide una decisión** — los hallazgos críticos y de advertencia con la evidencia necesaria para actuar sobre ellos, y las lecturas que no se pudieron tomar. Se siguen ejecutando todas las comprobaciones: un informe corto que se saltara comprobaciones sería rápido y poco fiable.
- **El perfil Inventario no ejecuta ninguna comprobación**, así que un nodo que nunca se ha evaluado puede generar igualmente su documento estructural: la memoria módulo a módulo con slot, tipo, velocidad y número de pieza; los discos físicos con modelo, número de serie, bus y estado SMART; los adaptadores con velocidad de enlace, driver y dirección PCI; el passthrough PCI con su grupo IOMMU; y la latencia de red por destino.
- **La sección de discos lleva el registro de observaciones**: lo que ha pasado a lo largo del tiempo, incluidos los eventos de los que un disco se recuperó, con tipo, gravedad, recuento y la primera y la última vez que se vio cada uno.
- Los informes de SMART, Lynis, latencia y auditoría comparten ahora un mismo armazón: la misma cabecera, secciones numeradas, tarjetas y avisos destacados, y una barra de acciones solo con iconos que desaparece al imprimir la página.
- **Los hallazgos de auditoría y los informes imprimibles se adaptan a pantallas estrechas** ([PR #399](https://github.com/MacRimi/ProxMenux/pull/399), aportado por [@f3rs3n](https://github.com/f3rs3n)).
- **Toda la página funciona en un móvil.** Las tablas densas se apilan en bloques en los que el encabezado acompaña al valor en lugar de desplazarse en horizontal, los controles ocupan una fila cada uno por debajo del punto de corte pequeño, y el informe se abre como una navegación real, de modo que una aplicación web instalada conserva sus propios controles para volver y cerrar.

---

## 📦 OCI manager Apps (Technology Preview) — imágenes oficiales de contenedor como LXC nativos de Proxmox

ProxMenux no construye sus propios contenedores para estas aplicaciones: lee la receta publicada de cada una y la convierte en un LXC OCI nativo de Proxmox. OCI manager Apps lleva la etiqueta Technology Preview que Proxmox VE da a los contenedores de aplicaciones creados a partir de imágenes OCI, hasta que Proxmox VE los marque como estables.

### El catálogo

- **464 aplicaciones** de LinuxServer.io, de otros repositorios públicos de imágenes y de recetas escritas para ProxMenux, con la misma disposición que los Helper-Scripts: una búsqueda, la lista completa, 29 categorías y las aplicaciones instaladas. Cada aplicación lleva su icono y las arquitecturas que admite su imagen.
- **Una ✓ marca lo que se ha probado de verdad.** 43 aplicaciones muestran *Verificado*: 41 probadas en el laboratorio de ProxMenux, y PocketBase y Glances probadas por la comunidad, por [@Vaso73](https://github.com/Vaso73). Un formulario de issue registra una prueba nueva, y quien la hace aparece en los créditos de `oci/VALIDATION.md`.
- **Files & Sharing es una categoría propia**, con las dieciséis aplicaciones que sirven o sincronizan archivos. Entre ellas está **ShareCoveX**, un servidor de archivos con panel web que publica directorios por SMB, NFS o ambos, con usuarios de Samba y destinos de Time Machine.
- **También se puede instalar una imagen que no está en el catálogo**, a partir de su archivo Compose, un comando `docker run` o su referencia, con el resultado a la vista para revisarlo antes de crear ningún LXC.
- **Se puede instalar un oci-compose escrito a mano.** *Instalar una imagen que no está en el catálogo* acepta el archivo JSON desde el que se instala una aplicación: pegado en la terminal, leído desde el host o descargado desde una dirección. El archivo indica la imagen, sus puertos, variables y volúmenes, y lo que pregunta la instalación; ProxMenux completa el resto, lo comprueba y señala cada error por su campo. `oci/README.md` describe el formato bloque a bloque, con dos ejemplos en `oci/examples/`.

### Instalar una aplicación

- **Los menús de OCI manager Apps numeran sus opciones**, como hace el resto de ProxMenux, así que cada descripción dispone de todo el ancho; un almacenamiento, un bridge o un dispositivo conserva su nombre.
- **OCI manager Apps se abre en Proxmox VE 9.1 o posterior**, la primera versión que ejecuta imágenes OCI como contenedores LXC. En un host más antiguo lo indica, con la versión instalada, antes de instalar nada.
- **La página de una aplicación muestra lo que va a crear antes de instalar nada**: su imagen, la dirección en la que responderá, dónde van sus datos persistentes, los perfiles de aceleración que ofrece y, en una aplicación multicontenedor, cada contenedor del conjunto.
- **Dos formas de instalar.** La predeterminada pregunta lo que decide cualquier instalación (almacenamiento, dónde van sus datos, DHCP o dirección estática, cómo arranca) y toma el resto de la receta. La avanzada abre todas las decisiones en orden: VMID y recursos, cada ruta de datos con su ubicación, almacenamiento y tamaño, rutas y dispositivos adicionales, la red, los ajustes de la aplicación, la GPU y cómo arranca.
- **Cada pregunta dice lo que pide**, con un ejemplo o un valor propuesto. Una aplicación que necesita una base de datos o un servidor Redis ya en marcha, como BookStack, NetBox o Manyfold, lo indica primero, con la dirección de la documentación de su imagen.
- **A una aplicación no se le pregunta su propia dirección.** BookStack, Healthchecks, Speedtest Tracker y NetBox reciben la dirección del contenedor: la fija o la que asigna DHCP, obtenida antes de que la aplicación arranque por primera vez.
- **Las carpetas de datos pertenecen a la aplicación.** Descargas, series, música, libros y backups se crean para el usuario con el que se ejecuta la aplicación, como volumen del contenedor o como directorio del host, y un volumen nuevo empieza con lo que la imagen contiene en esa ruta.
- **FileBrowser Quantum abre la carpeta que se le indica.** Arranca con la configuración de su receta, escrita para la versión 2 de la aplicación, que sirve la carpeta elegida en la instalación. El archivo inicial que escribe una receta sustituye a la copia que trae la imagen en un volumen nuevo, y nunca a un archivo que ya estuviera allí.
- **Las imágenes de registros privados se instalan y se actualizan** ([PR #460](https://github.com/MacRimi/ProxMenux/pull/460), aportado por [@jcastro](https://github.com/jcastro), y solicitado por varios usuarios). *Cuentas de registro* guarda una cuenta en cuanto el registro la acepta, y un registro que rechaza una imagen ofrece iniciar sesión en ese mismo momento. Las cuentas se guardan en `/etc/pve/priv` para todos los nodos del clúster, y las usan las actualizaciones, la vigilancia y el Monitor.
- **Los dispositivos USB y serie se eligen de una lista**, por nombre y tipo, y todas las aplicaciones aceptan rutas y dispositivos adicionales en la instalación avanzada.
- **Las aplicaciones arrancan con la memoria que necesitan**: 1024 MB, salvo que la receta pida más o fije un límite.
- **El resumen termina con lo necesario para usar la aplicación**: su dirección, y el usuario y la contraseña con los que iniciar sesión. Un servicio sin interfaz web, como MariaDB, PostgreSQL o un servidor SSH, se indica por su dirección y su puerto.
- **Un valor mal escrito vuelve a hacer la misma pregunta**, no se acepta una dirección estática que ya esté en uso en la red, y la creación del contenedor muestra su progreso mientras se desempaqueta una imagen grande.
- **Se instalan las imágenes construidas desde cero con un usuario numérico**, como ddns-updater: el contenedor se crea a partir de una copia de la imagen que añade los `/etc/passwd` y `/etc/group` que necesita Proxmox VE, y la aplicación se ejecuta con el usuario y el grupo que declara la imagen. La imagen descargada se conserva tal como estaba.
- **La imagen descargada se puede eliminar al terminar la instalación**, y las imágenes que no usa ninguna instalación se eliminan solas.

### Aplicaciones formadas por varios contenedores

- **Un LXC por servicio**, conectados a través de un bridge privado propio y arrancados en orden. Immich, Nextcloud, Paperless y Tandoor tienen sus propias recetas, otras diez proceden de su archivo Compose publicado, y la suite Arr instala cada aplicación como un LXC independiente conectado con los demás.
- **Immich pregunta qué ejecuta su vídeo y su reconocimiento**: la CPU o cada GPU del host, juntas o repartidas entre dos GPU, con VA-API o NVENC para el vídeo y OpenVINO, ROCm o CUDA para el reconocimiento.
- **La dirección que se ofrece es la que puede alcanzar un navegador**: la dirección de LAN del contenedor, en el resumen y en sus notas de Proxmox.

### Aceleración por hardware

- **El menú de aceleración ofrece solo lo que el host puede ejecutar**: NVIDIA con el driver y el Container Toolkit, Intel o AMD donde esa GPU está presente. El render node propuesto es el de esa GPU.
- **Las aplicaciones de IA usan la imagen construida para la GPU elegida.** Ollama incorpora un perfil AMD (ROCm), llama.cpp ofrece CPU, CUDA, ROCm y SYCL, y Faster Whisper y Piper ofrecen NVIDIA.
- **Frigate detecta objetos con una GPU AMD, una NPU Intel o un Coral** (NPU y Coral sugeridos por [@jcastro](https://github.com/jcastro)), y su detector de CPU funciona en procesadores AMD.
- **ROCm se ofrece según la generación de la GPU AMD**, como opción experimental en aquellas para las que la imagen no trae kernels, e Immich comprueba la GPU con una inferencia real antes de aceptarla.

### Almacenamiento y directorios compartidos

- **Un directorio del host que ya existe se puede abrir a la aplicación que lo comparte**, con reglas de acceso (ACL) que dejan intacto el propietario de los archivos.
- **Un directorio compartido del host muestra lo que el host tiene montado dentro de él**: recursos compartidos de red, discos y datasets ZFS, también los que se montan mientras el contenedor está en marcha.
- **Un directorio compartido del host se reconoce por su sistema de archivos**, así que una aplicación se sigue actualizando después de que el host se reinicie o de que un disco vuelva con otro nombre de dispositivo (reportado por Charly Silva).

### Actualizar, modificar y recrear

- **Una actualización sustituye la imagen y conserva los datos.** Se hace un backup del contenedor, se reconstruye a partir de la imagen nueva y se le pide que responda antes de dar la operación por buena; si no responde, todo vuelve a como estaba. Los cambios de recursos hechos desde Proxmox se mantienen.
- **Todas las aplicaciones instaladas se pueden actualizar y modificar**, incluidos los contenedores privilegiados, los monitores del host y las aplicaciones de la suite Arr.
- **Modificar** cambia los ajustes de una aplicación instalada; en una multicontenedor añade o elimina rutas y dispositivos adicionales sin reconstruir nada, y cambia lo que ejecuta el reconocimiento en Immich.
- **Una aplicación multicontenedor se puede reconstruir tal como está** ([PR #423](https://github.com/MacRimi/ProxMenux/pull/423), aportado por [@Vaso73](https://github.com/Vaso73)). *Recrear todos los contenedores con su configuración guardada* reconstruye cada contenedor a partir de la imagen con la que se instaló.
- **Las etiquetas de Proxmox se pueden cambiar libremente** ([PR #473](https://github.com/MacRimi/ProxMenux/pull/473), aportado por [@jcastro](https://github.com/jcastro)): Actualizar, Modificar y Recrear conservan las etiquetas que tiene un contenedor, o ninguna si se eliminaron, también en los contenedores de una aplicación multicontenedor.
- **Un volumen montado en solo lectura se deja tal como está** al reconstruir un contenedor ([PR #494](https://github.com/MacRimi/ProxMenux/pull/494), aportado por [@jcastro](https://github.com/jcastro)), como `/run/secrets`; no se tocan sus archivos, su propietario ni sus permisos.
- **Una aplicación que se ejecuta con un usuario que su imagen no incluye recibe `/` como directorio personal** ([PR #496](https://github.com/MacRimi/ProxMenux/pull/496), aportado por [@Vaso73](https://github.com/Vaso73)), como hace Docker, y el archivo de usuarios de la imagen se lee sin seguir enlaces.
- **Los servicios que no son páginas web se actualizan y se recuperan como los demás**: MariaDB, SSH o un servidor de voz responden por su propio protocolo, y Actualizar, Modificar y Recuperar toman esa respuesta como señal de que el servicio está en marcha.
- **El backup de una operación se puede hacer en otro almacenamiento** cuando no cabe en el disco del sistema, y una operación que no tiene espacio lo indica antes de detener nada.
- **Una descarga de imagen o un backup de trabajo dañados se escriben una segunda vez** antes de que nada falle, y una actualización fallida no deja ningún contenedor temporal.
- **Modificar es un menú de ajustes** ([PR #495](https://github.com/MacRimi/ProxMenux/pull/495), aportado por [@jcastro](https://github.com/jcastro)): cada fila muestra el valor actual, solo se edita el ajuste elegido, y los cambios se guardan hasta que se revisan y se aplican juntos, o se descartan. Actualizar las opciones del catálogo es una entrada más del menú.
- **Gestionar se abre al instante** ([PR #493](https://github.com/MacRimi/ProxMenux/pull/493), aportado por [@jcastro](https://github.com/jcastro)): la configuración de cada aplicación solo se vuelve a leer cuando ha cambiado, así que un host con 26 aplicaciones pasa de 15 segundos a una fracción de segundo.
- **Modificar y Actualizar se abren sin esperas** ([PR #498](https://github.com/MacRimi/ProxMenux/pull/498), aportado por [@jcastro](https://github.com/jcastro)): el espacio para el backup se comprueba una vez aceptada la operación, y la tecla Esc vuelve atrás al instante.
- **Modificar cambia el contenedor en marcha cuando puede** ([PR #497](https://github.com/MacRimi/ProxMenux/pull/497), aportado por [@jcastro](https://github.com/jcastro)): la CPU y la memoria se aplican en caliente, y la red, las variables, las rutas del host y los dispositivos se cambian en su sitio, con marcha atrás si falla un paso. Solo lo que no se puede cambiar en su sitio reconstruye el contenedor.
- **Las variables cambiadas en Proxmox se conservan.** Una contraseña cambiada tras el primer inicio de sesión, o una variable añadida desde Proxmox, se muestra por su nombre, sin su valor, y se guarda en el oci-compose antes de que Actualizar o Modificar continúen.
- **La imagen descargada solo se ofrece para eliminarla después de reconstruir un contenedor a partir de ella**, no después de un cambio aplicado al contenedor en marcha.
- **La lista de aplicaciones instaladas vuelve después de cada operación**, ya sea una actualización, un cambio o una eliminación, sin volver a leer todas las aplicaciones.

### Vigilancia, backups y clústeres

- **Una aplicación se puede poner bajo vigilancia.** Proxmox no tiene política de reinicio; con la vigilancia activada, una aplicación que se detiene por sí sola se vuelve a arrancar, con una notificación. Nunca se deshace una parada pedida por el usuario, un backup, una migración o una operación de ProxMenux.
- **Una aplicación multicontenedor arranca mientras se hace el backup de uno de sus contenedores.** Su arranque espera a que vzdump libere ese contenedor y después continúa, y la vigilancia también espera. Al actualizar ProxMenux, las aplicaciones ya instaladas reciben el nuevo hook de arranque.
- **El registro de una aplicación viaja con su contenedor.** Una copia vive dentro de él y otra en `/etc/pve`, así que un backup de vzdump o de PBS siempre lo lleva.
- **Se ofrece recuperar una aplicación restaurada**, en una instalación nueva de Proxmox, en otro host o con otro ID. La recuperación repone lo que el host guardaba para ella, como la red privada de una aplicación multicontenedor, y lo comprueba todo antes de modificar el host.
- **En un clúster, el registro sigue al contenedor.** Una aplicación de un solo contenedor migrada o movida por HA arranca y se registra en el nodo al que llega.
- **Un contenedor que se reinicia a sí mismo conserva su dirección DHCP**, como hace Home Assistant OS desde sus ajustes.

### Eliminar una aplicación

- **Todo lo que la instalación guardó en el host se elimina con ella** y el resultado indica si algo quedó sin hacer ([PR #402](https://github.com/MacRimi/ProxMenux/pull/402), aportado por [@f3rs3n](https://github.com/f3rs3n)). Los directorios del host se conservan, y una aplicación de la suite Arr se elimina por separado.

### Probadas frente a sus originales de Docker (aportado por [@Vaso73](https://github.com/Vaso73))

Instalaciones reales comparadas una junto a otra con las mismas imágenes en Docker, y lo que aportaron:

- **Los datos iniciales de una imagen llegan a su volumen nuevo** ([PR #394](https://github.com/MacRimi/ProxMenux/pull/394)), como necesita PocketBase.
- **Un monitor del host es accesible a través del firewall, si se pide** ([PR #393](https://github.com/MacRimi/ProxMenux/pull/393), [PR #395](https://github.com/MacRimi/ProxMenux/pull/395)): Glances recibe una regla acotada, que se confirma por separado y se elimina con la aplicación.
- **Los miembros de una pila guardan sus datos en un volumen preparado** ([PR #410](https://github.com/MacRimi/ProxMenux/pull/410)), incluida la ruta de datos de las imágenes actuales de PostgreSQL.
- **Stremio, Uptime Kuma y las imágenes que necesitan un directorio personal arrancan como en Docker** ([PR #411](https://github.com/MacRimi/ProxMenux/pull/411), [PR #412](https://github.com/MacRimi/ProxMenux/pull/412), [PR #413](https://github.com/MacRimi/ProxMenux/pull/413)).

---

## 📱 Aplicaciones OCI en ProxMenux Monitor

- **La pestaña App registra lo que instaló ProxMenux.** La aplicación de un contenedor OCI se registra sola con su nombre, logotipo, dirección y seguimiento de versiones, leídos del registro de la instalación, también mientras el contenedor está detenido. Cada servicio que sirve una aplicación tiene su propio enlace, y un servicio sin interfaz web muestra su dirección y su puerto como texto.
- **Una aplicación instalada desde el menú aparece sola en el Monitor.** La página Apps y la lista de contenedores la registran a los pocos segundos de terminar su instalación, sin abrir su contenedor.
- **Las actualizaciones se siguen por la imagen.** La tarjeta muestra la versión de la aplicación y la imagen que ejecuta, con su fecha de compilación y su digest; una imagen nueva con la misma etiqueta es una actualización.
- **La pestaña Actualizaciones actualiza y modifica el contenedor.** **Actualizar** y **Modificar** abren la terminal del Monitor con el mismo flujo que el menú OCI. El backup hecho antes de actualizar se puede conservar, las actualizaciones de imagen se pueden programar, una aplicación multicontenedor se actualiza desde su contenedor principal y una aplicación restaurada muestra un botón **Recuperar**.
- **Una pestaña Registros nueva muestra lo que la aplicación escribe en su consola**, guardado en el host desde el primer arranque: las últimas líneas desde el último arranque, seguidas en directo, con un filtro y una descarga.
- **La consola de Proxmox de un contenedor OCI abre una shell**, el equivalente a `docker exec`, siempre que la imagen incluya una.
- **El interruptor Vigilancia** está en el modal del contenedor, debajo de Iniciar al arrancar.
- **Una operación OCI envía una sola notificación con su resultado**, en lugar de una por paso. Modificar y la reconstrucción de una aplicación multicontenedor tienen notificaciones propias.
- **El icono de actualización de la página Apps abre la pestaña Actualizaciones** de ese contenedor.

---

## 🔎 Búsqueda en el menú principal

- **El menú principal se abre con Buscar opciones y aplicaciones.** Un nombre o una parte de él encuentra una opción de ProxMenux, una aplicación del catálogo OCI o un Helper-Script, en ese orden, primero por nombre y después por categoría.
- **Cada resultado abre lo que dice su nombre**: un script en su primera pantalla, una aplicación en su página, una opción de la post-instalación o una utilidad del sistema en su lista, ya marcada. La búsqueda en sí no ejecuta nada.
- **El catálogo de Helper-Scripts se guarda en el host** y se actualiza una vez al día, así que la búsqueda responde también sin conexión.

---

## 🧩 Los addons de Helper-Scripts se ejecutan donde corresponde

- **Un addon se ejecuta donde indica su catálogo**: en el host Proxmox, dentro de un LXC elegido de una lista, o donde se elija cuando puede ser en ambos. Un LXC detenido se arranca tras confirmarlo, y los contenedores OCI quedan fuera.
- **Las descripciones y las notas se muestran como texto plano**, y un script se descarga completo antes de ejecutar nada.

---

## 🗄 ProxMenux en Proxmox Backup Server ([PR #467](https://github.com/MacRimi/ProxMenux/pull/467), aportado por [@jcastro](https://github.com/jcastro))

- **ProxMenux se instala en un Proxmox Backup Server** con el mismo comando que en PVE, y abre un menú propio: versión y paquetes, datastores, tareas recientes, utilidades del sistema y una actualización de paquetes que muestra su plan antes de aplicarlo.
- **El menú de post-instalación funciona en PBS**: Automático, Personalizable, actualizaciones y desinstalación, con las opciones que tienen sentido en un servidor de backups. Sin suscripción, ofrece el repositorio no-subscription antes de actualizar, y Scripts comunitarios muestra la post-instalación de PBS y el microcódigo de los Helper-Scripts.
- **El Monitor de un PBS tiene el diseño del de PVE**: la misma cabecera, salud y administración, gráficas de CPU, memoria y red a partir del histórico que guarda PBS, una pestaña Datastores con el uso de cada datastore y los discos y pools del servidor, y una pestaña Tareas con las tareas recientes y las programaciones de mantenimiento. Lo que solo aplica a PVE queda fuera, ajustes incluidos.
- **Los trabajos de mantenimiento de un PBS muestran el estado de su última ejecución** también en su propio Monitor, leído de la API de PBS como en un PBS remoto.
- **Log2RAM comprime al momento los logs rotados**: el log rotado más reciente ya no se queda sin comprimir en `/var/log`, algo que en un PBS con mucha actividad llenaba un Log2RAM de 128M e impedía registrar sus tareas. A los hosts que ya tienen Log2RAM o la optimización de logrotate se les ofrece la actualización en *Ajustes → ProxMenux Optimizations*.
- **Un PBS remoto se puede vigilar desde PVE** en *Backup → Proxmox Backup Server*. Al iniciar sesión con un usuario y una contraseña de PBS se crea un token de API de solo lectura para el Monitor y solo se guarda ese token, o se puede introducir un token existente. La huella del certificado se comprueba antes de enviar ninguna credencial. Los servidores PBS configurados como almacenamiento se ofrecen con su dirección y su huella ya rellenadas, y un PBS instalado en el mismo host se lee directamente, sin token.

---

## 💾 Trabajos de backup de VM y CT gestionados desde ProxMenux ([PR #421](https://github.com/MacRimi/ProxMenux/pull/421), aportado por [@MattiaC46](https://github.com/MattiaC46))

- **La pestaña Backup del Monitor tiene dos vistas, «Host» y «VM y LXC».** La segunda, y el menú Backup y restauración del host, listan los trabajos programados de Proxmox, los mismos que Datacenter → Backup, y los crean, editan, habilitan, deshabilitan, eliminan y ejecutan a través de la API de Proxmox.
- **Ejecutar ahora inicia una tarea de Proxmox en cada nodo que tiene un guest del trabajo.** Cambiar un trabajo requiere una sesión de administrador; un token de API de solo lectura solo puede listarlos.

---

## 💾 Backups y restauración

- **Los backups de VM y CT se pueden seleccionar y eliminar desde el Monitor** ([PR #461](https://github.com/MacRimi/ProxMenux/pull/461), aportado por [@jcastro](https://github.com/jcastro)): hasta 20 a la vez, tras una confirmación, a través del propio Proxmox. Un backup protegido no se puede seleccionar, y un lote que incluya uno se rechaza entero.
- **La retención de cada almacenamiento de backups se edita desde el Monitor** ([PR #462](https://github.com/MacRimi/ProxMenux/pull/462), aportado por [@jcastro](https://github.com/jcastro)): conservar todos, un número de backups por periodo o el valor predeterminado de Proxmox. Al guardar se cambia la política en Proxmox y no se elimina ningún backup.
- **Las notificaciones de backup dicen cómo terminó el trabajo** ([PR #406](https://github.com/MacRimi/ProxMenux/pull/406), aportado por [@f3rs3n](https://github.com/f3rs3n)): limpio, con advertencias, fallido o sin confirmar, indicando el guest que falló y manteniendo legibles los diagnósticos largos. El resumen de recuperación cuenta cada guest una sola vez ([PR #356](https://github.com/MacRimi/ProxMenux/pull/356)).
- **Un backup iniciado desde el Monitor se ejecuta en su propia unidad de systemd** y continúa pase lo que pase con el Monitor.
- **El backup del host funciona en un host con SELinux** ([#398](https://github.com/MacRimi/ProxMenux/issues/398), reportado por [@sbaghdadi](https://github.com/sbaghdadi)) y guarda todo el estado de ProxMenux en el host bajo `/var/lib/proxmenux`.
- **Se notifica cada ejecución del backup del host** ([#425](https://github.com/MacRimi/ProxMenux/discussions/425), reportado por @sahartford): cada ejecución se envía al terminar, como un backup de VM o CT, también en un canal con el resumen diario activado y con HTTPS activado en el Monitor.
- **Un repositorio Borg remoto se autentica con la clave guardada en su destino** ([#357](https://github.com/MacRimi/ProxMenux/issues/357), reportado por [@bartclone](https://github.com/bartclone)), ofreciendo solo esa clave, y conserva su ruta remota tal como se escribió.
- **La lista de backups del host muestra los backups de este nodo en un clúster** ([#445](https://github.com/MacRimi/ProxMenux/issues/445), solicitado por [@Joshua1264](https://github.com/Joshua1264)): una opción Este nodo / Todos los nodos, con un recuento que la acompaña, separa los backups de otros nodos guardados en un PBS o un repositorio Borg compartidos.
- **Un backup local del host hecho por un trabajo que ya no existe se marca como Trabajo anterior** ([#446](https://github.com/MacRimi/ProxMenux/issues/446), solicitado por [@Joshua1264](https://github.com/Joshua1264)), a partir del trabajo y el nodo registrados con el backup. Se conserva hasta que se elimina, y al eliminarlo se eliminan también su archivo de metadatos y su log.
- **Una restauración del host solo se programa cuando está completa** ([PR #341](https://github.com/MacRimi/ProxMenux/pull/341), aportado por [@f3rs3n](https://github.com/f3rs3n)): cada restauración se prepara en su propio directorio y pasa a ser la pendiente solo cuando todos los pasos han tenido éxito.

### 🔐 Restauración del certificado web del nodo ([#333](https://github.com/MacRimi/ProxMenux/issues/333), reportado por [@tropicaljoe](https://github.com/tropicaljoe))

- Los backups del host ya conservaban el par de certificados local del nodo; la restauración posterior al arranque lo asigna ahora del nodo de origen al actual, en lugar de dejar Proxmox con su certificado generado.
- Antes de instalarlo, ProxMenux valida el certificado, rechaza las claves privadas cifradas o no válidas y confirma que ambas claves públicas coinciden; un par incompleto deja intacto el certificado actual y añade una advertencia al resultado de la restauración. La instalación se hace mediante `pvenode cert set`, seguida de la verificación de la huella y del servicio, con vuelta al certificado anterior si esa verificación falla.

---

## 🟢 Instalador de NVIDIA y passthrough de GPU

- **El NVIDIA Container Toolkit se instala con el driver.** Es lo que permite que un contenedor vea la GPU del host. También se puede reinstalar por separado, y queda registrado en la vista Cambios de Audit & Report.
- **El selector de versiones ofrece los drivers que admiten la GPU y pueden compilarse para el kernel en uso**, y se abre en unos cinco segundos.
- **Se comprueba que una versión compila antes de eliminar el driver que funciona.** Una que no compila vuelve a la lista con el driver actual intacto, y la respuesta se recuerda para ese kernel.
- **El resultado indica lo que hace el driver**: un driver que se instala pero no controla la GPU se registra como fallido, con el motivo que da el propio kernel.
- **Añadir una GPU NVIDIA a una VM vuelve a escribir su regla VFIO cuando falta** (reportado por kn): un host al que se le eliminó la regla a mano la recupera, y se le pide reiniciar, en lugar de darlo por ya configurado.
- **Cambiar el modo de una GPU no afecta a sus vecinos** ([#435](https://github.com/MacRimi/ProxMenux/issues/435), reportado por [@LucasR3C3](https://github.com/LucasR3C3)). Una GPU es su propia función, el audio de su slot y los dispositivos de su grupo IOMMU. En una APU AMD, un controlador USB que comparte el slot de los gráficos integrados se queda en la VM a la que se pasó cuando la GPU vuelve al modo LXC o pasa a otra VM.
- **Los contenedores creados a partir de una imagen OCI quedan fuera de los menús LXC que instalan dentro de un contenedor**: propagación del driver, Añadir GPU a un LXC, Coral, discos y recursos compartidos. Sus dispositivos y rutas se cambian desde OCI manager Apps.

---

## 💽 Discos

- **Las observaciones de un disco pertenecen a su número de serie.** Un disco sustituido empieza con un historial limpio, el historial sigue a un disco a otro nombre de dispositivo y es permanente: la misma observación vista de nuevo suma a su recuento.
- **Los discos mecánicos pueden entrar en reposo** ([#347](https://github.com/MacRimi/ProxMenux/issues/347), reportado por [@spectante](https://github.com/spectante)). Un disco rotacional que no se está usando no se lee en absoluto, la vista de almacenamiento muestra *Inactivo* o *Excluido* junto a *En reposo*, y *Ajustes → Exclusiones de discos* deja un disco fuera de todas las lecturas programadas.
- **Las comprobaciones de LVM no tocan los discos excluidos ni los inactivos** ([PR #464](https://github.com/MacRimi/ProxMenux/pull/464), aportado por [@jcastro](https://github.com/jcastro)): mientras un disco está excluido, inactivo o dormido, el análisis lee solo los volúmenes físicos LVM de los demás discos, y sus propias lecturas no hacen que un disco se siga contando como ocupado.
- **El formateo de discos conserva lo que promete conservar** ([PR #339](https://github.com/MacRimi/ProxMenux/pull/339), [PR #340](https://github.com/MacRimi/ProxMenux/pull/340), aportado por [@f3rs3n](https://github.com/f3rs3n)): eliminar firmas deja intacta la tabla de particiones, y el disco del sistema se reconoce a través de LVM, RAID o ZFS apilados.
- **El resumen de almacenamiento distingue las temperaturas de disco no disponibles y matiza el estado SMART** ([PR #365](https://github.com/MacRimi/ProxMenux/pull/365), [PR #372](https://github.com/MacRimi/ProxMenux/pull/372), aportado por [@f3rs3n](https://github.com/f3rs3n)).
- **Un aviso de smartd sobre su propia configuración, o de fstrim en un disco que no admite discard, no se notifica como un fallo.**
- **Los puntos de montaje de volúmenes en almacenamiento de bloques muestran su uso** en la pestaña Puntos de montaje.

---

## 🔔 Notificaciones

- **Notificaciones en el idioma de quien las lee** ([PR #348](https://github.com/MacRimi/ProxMenux/pull/348), aportado por [@Vaso73](https://github.com/Vaso73)): los títulos, los cuerpos, las etiquetas de canal y los resúmenes diarios siguen el idioma elegido para las notificaciones, los mensajes largos de Telegram se dividen sin romper su formato y la redacción se revisó a mano.
- **Las alertas de temperatura y de salud incluyen sus valores** ([PR #408](https://github.com/MacRimi/ProxMenux/pull/408), aportado por [@f3rs3n](https://github.com/f3rs3n)): la lectura, el umbral y la categoría en el idioma de quien las lee.
- **Una notificación de evento del clúster dice lo que ha pasado** ([PR #403](https://github.com/MacRimi/ProxMenux/pull/403), aportado por [@f3rs3n](https://github.com/f3rs3n)), con el mensaje original de Proxmox.
- **Un nodo del clúster que cae o vuelve se notifica por su nombre** ([PR #444](https://github.com/MacRimi/ProxMenux/pull/444), aportado por [@fklnc94](https://github.com/fklnc94)), a partir de los cambios de pertenencia que corosync informa en los demás nodos.
- **Un problema de salud que vuelve se notifica de nuevo** ([PR #443](https://github.com/MacRimi/ProxMenux/pull/443), aportado por [@f3rs3n](https://github.com/f3rs3n)): una condición que se resolvió y reaparece es un episodio nuevo, que aparece como activo y se notifica una vez. Los descartes, también los permanentes, se mantienen tal como se establecieron.
- **Apprise explica cómo configurar Slack y Matrix** ([PR #463](https://github.com/MacRimi/ProxMenux/pull/463), aportado por [@jcastro](https://github.com/jcastro)), con direcciones de ejemplo y su documentación, y una recuperación se envía como éxito, en verde, como en los demás canales.
- **Los ajustes de notificaciones muestran el historial de entregas** ([#425](https://github.com/MacRimi/ProxMenux/discussions/425), reportado por @sahartford): las últimas 20 notificaciones con el resultado de cada envío, el error cuando alguno falló y cada ejecución del resumen diario, también los días sin nada que enviar.
- **Las notificaciones de Proxmox llegan con HTTPS activado en el Monitor**, a través de un listener local que solo responde al webhook de notificaciones.
- **El Monitor no toca `/etc/pve` mientras Proxmox reinicia su servicio de clúster** ([#427](https://github.com/MacRimi/ProxMenux/issues/427), reportado por [@shtefko](https://github.com/shtefko)). Los ajustes de notificaciones solo se escriben mientras `/etc/pve` está montado y solo cuando cambian, sus copias se guardan con ProxMenux, y al desinstalar el Monitor se elimina su destino de Proxmox.
- **Un patrón de log solo se notifica como persistente mientras sigue repitiéndose** ([#386](https://github.com/MacRimi/ProxMenux/issues/386), reportado por [@Joshua1264](https://github.com/Joshua1264)).
- **Una alerta descartada de forma permanente sigue descartada** (reportado por Maragath): mientras dure la condición, cuando se recupera y vuelve, y al guardar los ajustes de supresión, hasta que se vuelve a activar desde Supresiones activas.
- **Los almacenamientos excluidos quedan fuera de la alerta de capacidad** (reportado por @christiannieveslauz), y un almacenamiento que se está llenando indica cuánto está ocupado.
- **Un bridge privado sin nada conectado no se notifica como caído.**
- **Los iconos de los campos de una notificación también se muestran en francés** ([PR #523](https://github.com/MacRimi/ProxMenux/pull/523), aportado por [@f3rs3n](https://github.com/f3rs3n)), donde un espacio de no separación precede a los dos puntos de cada etiqueta.

### 📦 Notificaciones agrupadas de actualizaciones de aplicaciones

- **Una comprobación automática produce ahora una notificación completa en lugar de un mensaje por aplicación.** Las actualizaciones pendientes se agrupan por LXC y conservan el nombre de la aplicación y las versiones instalada y disponible, así que una bandeja de entrada más tranquila no te cuesta el detalle.
- Un análisis con una sola aplicación pendiente mantiene la notificación individual, y las comprobaciones explícitas que haces tú siguen siendo individuales. El ajuste existente **Actualización de aplicación disponible** controla ambas formas, y se siguen respetando las exclusiones por aplicación.

### 🧭 Notificaciones de salud de guests según el nodo propietario en el clúster

- **La capacidad del rootfs de los LXC y de los sistemas de archivos de las VM la evalúa solo el nodo que es propietario del guest en ese momento**, así que varias instancias del Monitor en un clúster ya no registran ni notifican la misma condición por separado. Las actualizaciones de disco del Guest Agent siguen el mismo límite.
- Un guest que se mueve entre nodos se retira en silencio en el anterior. Una migración no se notifica como una recuperación; el nuevo propietario es responsable de la condición actual.

### ⚙️ Diagnósticos del kernel atribuibles

- **Un diagnóstico del kernel se notifica por la línea que lo explica.** Las advertencias del kernel, las tareas bloqueadas, los lockups, los fallos de protección, los oops y los diagnósticos de seguridad de memoria indican ahora el tipo de diagnóstico, el proceso y el componente cuando están presentes, e incluyen el fragmento del journal que los rodea — en lugar de un simple marcador `Call Trace:` que no identifica nada y podía contar un incidente dos veces.
- **Las advertencias del kernel y las trazas de diagnóstico tienen su propio interruptor por canal**, y los resúmenes ocultos de ráfagas heredan la categoría del evento que resumen, así que silenciar un evento silencia también su `+N more`.

### 📮 Entrega de notificaciones

- **Los eventos retenidos durante las Horas tranquilas se liberan cuando se cierra la franja**, y la liberación se registra como cualquier otra entrega, así que aparece en el historial y en los contadores en lugar de llegar al canal sin dejar rastro. El búfer solo se vacía cuando el canal confirma la entrega, así que una franja nocturna nunca se descarta por un resumen que nadie recibió.
- El resumen de 24 horas se compone y se entrega de la misma forma.
- **Las actualizaciones pendientes de optimizaciones de ProxMenux se vuelven a notificar al reiniciar el Monitor** junto con el resto de informes de actualización, así que un host con optimizaciones que nunca aplicó vuelve a mostrarlas tras una actualización o un reinicio. Cada versión se sigue anunciando una sola vez por vida del servicio.

---

## 🔐 Los tokens de API de solo lectura solo leen (reportado por [@f3rs3n](https://github.com/f3rs3n))

- **Toda acción de la API que cambia algo requiere un token de administrador completo**: controlar guests, iniciar backups y pruebas SMART, ejecutar scripts, editar el firewall, Fail2Ban o SSL, y gestionar la 2FA y los tokens de API. Un token de solo lectura sigue leyendo paneles y métricas, y la sesión de la interfaz funciona como antes.
- **Leer los datos de salud requiere un token una vez configurada la autenticación**, y cada ruta del Monitor de Salud que cambia algo requiere un token de administrador completo. `/api/system-info` sigue siendo pública para sondas externas como Uptime Kuma.
- **Abrir una terminal del Monitor y desactivar la autenticación requieren un token de administrador completo.** Tanto la ruta del ticket de terminal como el endpoint que desactiva la autenticación están protegidos por la misma comprobación de ámbito de administrador que usan las demás rutas privilegiadas, y el WebSocket de la terminal sigue aceptando solo un ticket nuevo de un solo uso — que ahora se emite exclusivamente a quien llama con permisos de administrador completo.
- **Leer en claro una credencial guardada también requiere un token de administrador completo.** La página de ajustes enmascara todos los secretos guardados, y la única ruta que devuelve un valor — el botón del ojo junto a un campo — está protegida de la misma forma. Un token de solo lectura emitido para una integración de monitorización no llega a ninguno de ellos: el token de GitHub, el token del bot de Telegram, la contraseña del correo, las claves de los proveedores de IA, el webhook de Discord. Un inicio de sesión lleva implícito el administrador completo, así que el botón se comporta como antes para quien usa la interfaz.
- **El diálogo de tokens de API pregunta ahora qué ámbito crear.** Solo lectura es el valor predeterminado y basta para paneles y métricas; administrador completo está para las integraciones que manejan la Actions API, y el diálogo dice claramente a qué puede llegar cada uno.
- **La tarjeta API de GitHub indica el token que necesita**: ese token solo sirve para aumentar el límite anónimo de peticiones al comprobar las versiones upstream de las aplicaciones registradas, y cada llamada hecha con él lee datos públicos, así que basta con un token fine-grained con acceso de solo lectura a repositorios públicos y sin permisos de cuenta.

---

## 🐳 Aplicaciones Docker — una identidad, un estado de actualización

- **Las aplicaciones que se ejecutan dentro de Docker se pueden registrar en la pestaña App** con su propio nombre, logotipo, enlaces web y versión instalada, mientras sus actualizaciones siguen ligadas a la imagen Docker. Ya no aparecen dos veces en Actualizaciones: Portainer, Arcane y sus equivalentes conservan su entrada en App, y la fila de la imagen lleva las versiones.
- **Las versiones disponibles se pueden leer de los metadatos de la imagen** en Docker Hub, GHCR y otros registros compatibles cuando la imagen publica una etiqueta de versión utilizable — que describe lo que instalaría la etiqueta seleccionada, no necesariamente la última release upstream. La detección por digest sigue disponible cuando no se puede leer ninguna etiqueta.
- **Las versiones instaladas siguen la imagen que usa realmente el contenedor**, también tras una recreación o cuando una imagen descargada todavía no se ha aplicado, y los alias de imagen se emparejan con la referencia configurada de la carga de trabajo.
- Los metadatos de imagen se resuelven en segundo plano sin retrasar el inventario, y App y Actualizaciones comparten el resultado.

Gracias a [@byGarcia](https://github.com/byGarcia) por la implementación, los detectores verificados y las pruebas detalladas en [PR #337](https://github.com/MacRimi/ProxMenux/pull/337) y [PR #338](https://github.com/MacRimi/ProxMenux/pull/338), a partir de la colaboración en la [discusión #206](https://github.com/MacRimi/ProxMenux/discussions/206).

### Enlaces web de Docker en la pestaña App

- **El inventario de VM y LXC sigue disponible mientras se cargan los datos de Docker.** Un inventario de Docker puede existir antes de que se cargue su registro opcional de aplicaciones, y ese estado es ahora una lista de aplicaciones vacía y no una lista de guests vacía.
- **Las cargas de trabajo Docker detenidas conservan sus enlaces registrables.** El descubrimiento lee la configuración persistente de puertos publicados de un contenedor cuando el mapeo en vivo está vacío, así que un servicio Compose detenido como HandBrake, MakeMKV o MKVToolNix conserva su nombre detectado y su puerto del host listos para registrarse.
- **Los LXC con Docker conservan todos los candidatos útiles**: los mapeos con nombre conservan su aplicación, su icono y sus puertos publicados, mientras que los puertos en escucha que no pertenecen a ningún mapeo — contenedores con red del host, servicios nativos en el mismo LXC — siguen disponibles como sugerencias de un clic, sin duplicar un puerto que ya cubre un mapeo con nombre.
- **Un enlace detectado que se añade se queda añadido.** La inserción del enlace y la respuesta diferida de la categoría del catálogo actualizan el editor por separado, así que la consulta de categoría ya no puede restaurar un estado anterior a la inserción.
- El descubrimiento sigue siendo solo una sugerencia: tú eliges qué puertos publicados exponen realmente una interfaz web y guardas solo esos.

---

## 🖥 ProxMenux Monitor

- **El nombre del nodo en la cabecera abre otros Monitores**: los nodos del clúster, los servidores PBS configurados y los nodos añadidos a mano, cada uno con su estado. Cada Monitor mantiene su propio inicio de sesión. Al llegar desde otro, se ofrece, en un solo diálogo, añadirlo junto con los Monitores que enlaza, así que tras visitar cada nodo una vez todos los Monitores pueden llegar a todos. Un Proxmox Backup Server sin Monitor se muestra como su interfaz web, un PBS instalado en el propio nodo se abre en la dirección en uso, y el formulario de nodos sigue el estilo de modo de edición de los demás formularios.
- **La terminal de un contenedor en el que no se puede entrar dice por qué** y se cierra: una imagen que no tiene shell, como la de PeaNUT, remite a su pestaña Registros, y un contenedor detenido muestra el motivo que da Proxmox.
- **Las terminales web envían Ctrl+D desde su menú Ctrl**, lo que termina un texto pegado en la terminal, como un archivo Compose o un oci-compose en OCI manager Apps, también desde un móvil o una tableta. Un solo Ctrl+D termina el pegado, también justo después de su última línea.
- **Una VM o un LXC editados desde Proxmox muestran sus ajustes actuales** la siguiente vez que se abre su modal: inicio al arrancar, etiquetas, núcleos, memoria, red y puntos de montaje.
- **Un LXC cambiado fuera del Monitor muestra sus datos actuales** ([PR #441](https://github.com/MacRimi/ProxMenux/pull/441), aportado por [@Vaso73](https://github.com/Vaso73)): una dirección DHCP nueva, un ajuste editado en Proxmox mientras su modal está abierto y el sistema operativo de un contenedor restaurado o reinstalado. La pestaña Actualizaciones marca como desactualizado un resultado de hace más de 48 horas, y la tarjeta sigue mostrando el número de actualizaciones pendientes.
- **Actualizar un LXC detenido conserva su resultado** ([PR #447](https://github.com/MacRimi/ProxMenux/pull/447), aportado por [@Vaso73](https://github.com/Vaso73)): sus paquetes y aplicaciones se leen antes de volver a detenerlo, así que la pestaña Actualizaciones muestra lo que se instaló y lo que sigue pendiente. Una ejecución que no llegó a arrancar el contenedor conserva el resultado anterior.
- **Comprobar e instalar paquetes de un LXC son pasos separados** ([PR #448](https://github.com/MacRimi/ProxMenux/pull/448), aportado por [@Vaso73](https://github.com/Vaso73)): Comprobar paquetes del sistema actualiza los índices de paquetes de un contenedor en marcha y cuenta lo que está pendiente sin instalar nada, e instalar requiere una comprobación correcta reciente. A un contenedor detenido se le pide arrancarlo primero, y conserva su último resultado con su fecha.
- **Una actualización programada deja detenido un LXC detenido** ([PR #456](https://github.com/MacRimi/ProxMenux/pull/456), aportado por [@Vaso73](https://github.com/Vaso73)): la ejecución se omite y la pestaña Actualizaciones indica el motivo, mientras el contenedor sigue detenido y después. Una actualización iniciada a mano sigue arrancándolo.
- **Buscar aplicaciones reconoce las aplicaciones instaladas a mano en un LXC** ([PR #492](https://github.com/MacRimi/ProxMenux/pull/492), aportado por [@Vaso73](https://github.com/Vaso73)): los servicios de systemd y OpenRC, los procesos y los puertos en escucha de programas en `/opt`, `/srv`, `/usr/local` o un directorio personal se proponen con su evidencia y su versión, y se registran tras confirmarlos en el editor.
- **JDownloader se abre por HTTPS y Prowlarr muestra su dirección de primer arranque** ([PR #506](https://github.com/MacRimi/ProxMenux/pull/506), aportado por [@Vaso73](https://github.com/Vaso73)), tal como los sirven sus imágenes.
- **Los backups en modo snapshot de las aplicaciones OCI funcionan en ZFS** ([PR #514](https://github.com/MacRimi/ProxMenux/pull/514), aportado por [@jcastro](https://github.com/jcastro)): los archivos que trae una imagen donde se monta un volumen de datos se guardan aparte dentro del contenedor, para que ZFS pueda montar cada snapshot durante un vzdump. Se conservan, nunca se eliminan, también tras una actualización o una recreación.
- **Las aplicaciones OCI arrancan tras una restauración directa de Proxmox** ([PR #507](https://github.com/MacRimi/ProxMenux/pull/507), aportado por [@Vaso73](https://github.com/Vaso73)): el `lost+found` vacío que crea una restauración en cada volumen de datos se elimina antes de que arranque la aplicación, también cuando ProxMenux recupera un contenedor en marcha.
- **El menú OCI muestra qué aplicaciones tienen una actualización y actualiza las seleccionadas** ([PR #504](https://github.com/MacRimi/ProxMenux/pull/504), aportado por [@jcastro](https://github.com/jcastro)): «Buscar actualizaciones» consulta a ProxMenux Monitor, que comprueba todas las aplicaciones a la vez y guarda el resultado que muestra la pestaña App; cada actualización seleccionada pasa por la revisión, el backup y la recuperación habituales, una tras otra, con el número de cada una en pantalla mientras se comprueba su contenedor.
- **El editor de App encuentra el icono real de una aplicación local** ([PR #503](https://github.com/MacRimi/ProxMenux/pull/503), aportado por [@Vaso73](https://github.com/Vaso73)): «Buscar icono» lee el puerto web elegido dentro del contenedor en marcha, desde la propia red del contenedor, y guarda una copia saneada que se sigue mostrando mientras el contenedor está detenido. La imagen la decodifica un proceso sin privilegios.
- **Buscar aplicaciones también muestra los contenedores Docker con puertos publicados** ([PR #505](https://github.com/MacRimi/ProxMenux/pull/505), aportado por [@Vaso73](https://github.com/Vaso73)): cada uno se puede registrar con su dirección web y su esquema ya rellenados, y registrarlo nunca configura actualizaciones.
- **Buscar aplicaciones en un LXC detenido dice por qué no puede buscar** ([PR #501](https://github.com/MacRimi/ProxMenux/pull/501), aportado por [@Vaso73](https://github.com/Vaso73)): la búsqueda necesita el contenedor en marcha, y se conservan las tarjetas y la evidencia encontradas antes.
- **Los botones de encendido de las VM y los LXC terminan cuando termina Proxmox** ([PR #449](https://github.com/MacRimi/ProxMenux/pull/449), aportado por [@Vaso73](https://github.com/Vaso73)): iniciar, apagar, reiniciar y parar siguen su tarea de Proxmox, también en los guests gestionados por HA, y el guest queda libre para otras acciones cuando termina.
- **La búsqueda de VM y LXC encuentra un contenedor por cualquiera de sus direcciones** ([PR #385](https://github.com/MacRimi/ProxMenux/pull/385), aportado por [@Vaso73](https://github.com/Vaso73)), y la tarjeta muestra cuántas más tiene.
- **Las actualizaciones disponibles en la vista general siguen al host** ([#359](https://github.com/MacRimi/ProxMenux/issues/359), reportado por [@ash34](https://github.com/ash34)), se hayan instalado los paquetes de la forma que sea.
- **El log de actualización de Proxmox dice qué se actualizó** ([#358](https://github.com/MacRimi/ProxMenux/issues/358), reportado por [@ash34](https://github.com/ash34)), y la lista de paquetes se muestra antes de aceptar la actualización.
- **Un aviso de montaje remoto descartado deja de contar en el estado de salud** ([PR #453](https://github.com/MacRimi/ProxMenux/pull/453), aportado por [@wolly6973](https://github.com/wolly6973)): un montaje NFS/CIFS obsoleto o de solo lectura, en el host o dentro de un LXC, se puede descartar desde su fila en Salud, y el estado general vuelve a ser correcto.
- **Los contenedores Docker anclados por digest se mantienen en el inventario** ([#206](https://github.com/MacRimi/ProxMenux/discussions/206), reportado por [@byGarcia](https://github.com/byGarcia)), marcados como *Anclada a un digest* y sin que se les ofrezca nunca una actualización.
- **LazyLibrarian y PeaNUT se incorporan al catálogo de aplicaciones LXC** (con [@pdafoto](https://github.com/pdafoto)); LazyLibrarian es la primera entrada con seguimiento por commit.
- **El nombre del nodo se lee sin esperar a la API de Proxmox** ([#438](https://github.com/MacRimi/ProxMenux/issues/438), reportado por [@sponger544](https://github.com/sponger544)), en el Monitor y en su comprobación de almacenamiento, así que a un host en el que `pvesh` responde despacio no se le pregunta en cada petición.
- **Secure Gateway muestra el mismo estado de actualización** en la página Seguridad y en la pestaña Actualizaciones de su contenedor.
- **Escribir un número en la terminal de un script mantiene la sesión abierta.**
- **El umbral RAM Crítico definido en Ajustes se aplica a la comprobación de RAM.**
- **`/api/health` informa de la versión instalada de ProxMenux**, y las métricas de disco de Prometheus se exportan en bytes, como indican sus nombres.
- **Un backup iniciado desde una VM o un LXC notifica según los ajustes de notificaciones**, igual que cualquier otro backup; su diálogo ya no tiene un menú de notificaciones propio.
- **Cada canal de notificaciones conserva su propia reescritura por IA**, y un correo detallado adjunta el mensaje original solo cuando la IA lo ha reescrito.

### 🛠 Selección explícita del actualizador de aplicaciones (comentarios de [@SystemIdleProcess](https://github.com/MacRimi/ProxMenux/discussions/306))

- **Registrar una aplicación ya no activa un actualizador por ti.** Elige y guarda **Helper-Scripts** o **Comando personalizado** antes de ejecutar una actualización; el seguimiento de versiones es independiente de esa elección.
- Cada aplicación tiene su propia elección, también en los LXC con varias aplicaciones, y un comando personalizado sustituye al helper de esa aplicación en lugar de ejecutarse ambos.
- **Al editar se muestra el comando que se ejecutará realmente** — el lanzador detectado o tu comando personalizado guardado. Modificar un lanzador del helper cambia a Comando personalizado, para que tus cambios se usen en las ejecuciones manuales, en bloque y programadas; dejarlo sin tocar mantiene el método oficial.
- **Una descarga del actualizador fallida o vacía se detiene antes de la ejecución**, así que un comando de shell vacío ya no puede notificarse como una actualización correcta.
- Los diálogos de información explican ambas opciones, enlazan a la documentación y al código fuente de cada aplicación e incluyen ejemplos para adaptar — que nunca rellenan ni ejecutan nada por sí mismos.

### 🔍 Lista de VM y LXC — búsqueda instantánea y filtro de actualizaciones ([PR #334](https://github.com/MacRimi/ProxMenux/pull/334), aportado por [@Vaso73](https://github.com/Vaso73))

- **Un cuadro de búsqueda que coincide con el nombre, el ID, el tipo de guest, las etiquetas, la nota de PVE, la dirección IP y los nombres de las aplicaciones registradas.** Varios términos acotan juntos y la coincidencia ignora los acentos, así que `nuria` encuentra `Núria` y `virtualny` encuentra `virtuálny`.
- **Un filtro Actualizaciones** aísla los LXC con trabajo pendiente — los paquetes del sistema operativo, las aplicaciones registradas y las imágenes Docker cuentan para su insignia — y su estado se recuerda por dispositivo.
- **La búsqueda por tipo de guest funciona en todos los idiomas del Monitor**: `contenedor`, `conteneur`, `contenitore`, `contêiner`, `kontajner` y `Container` encuentran todos los LXC del nodo.

### 🗂 Puntos de montaje de LXC — destinos escritos con barra final ([PR #336](https://github.com/MacRimi/ProxMenux/pull/336), aportado por [@Vaso73](https://github.com/Vaso73))

- **Un bind mount configurado como `mp=/path/` se reconoce como montado.** Proxmox acepta la barra final mientras que la tabla de montajes del contenedor informa de la ruta sin ella; ahora ambas formas de escribirla corresponden al mismo punto de montaje. La ruta se muestra en pantalla exactamente como está escrita en la configuración del contenedor.
- La misma coincidencia se aplica a la detección ad hoc, así que un montaje configurado ya no aparece como uno no gestionado creado dentro del contenedor.

### 🔎 Detección de versiones de aplicaciones LXC — detectores verificados en ejecución ([PR #332](https://github.com/MacRimi/ProxMenux/pull/332), aportado por [@Vaso73](https://github.com/Vaso73))

- **Un conjunto de sustituciones integrado viaja dentro del Monitor** con detectores probados en contenedores reales, y tiene prioridad sobre el catálogo remoto. A propósito no se descarga en remoto, para que un Monitor instalado no pueda traer una entrada más antigua que resucite un marcador obsoleto sobre un detector ya verificado.
- **Los marcadores heredados del helper pasan a ser un fallback** en lugar de desaparecer, así que los contenedores instalados con estructuras antiguas conservan una fuente de versión válida, mientras que las instalaciones nuevas leen el binario, el paquete o el archivo de la propia aplicación.
- **Traefik** es la primera aplicación incorporada al nuevo conjunto, y **Changedetection.io** se incorpora al catálogo en este ciclo (sugerido por [@SystemIdleProcess](https://github.com/SystemIdleProcess) en la [discusión #306](https://github.com/MacRimi/ProxMenux/discussions/306)).
- Una actualización correcta con comando personalizado marca la versión informada como no verificada, así que la actualización de datos que sigue vuelve a leer la versión real en lugar de reafirmar la antigua.

### 📦 Actualizaciones de paquetes de LXC legibles ([#342](https://github.com/MacRimi/ProxMenux/issues/342), reportado por [@ash34](https://github.com/ash34))

- **Los nombres de paquete ya no se sacrifican por las largas cadenas de versión de Debian.** Cada paquete pendiente conserva su nombre completo en su propia línea, seguido de las versiones instalada y disponible en columnas separadas y del mismo tamaño.
- Los nombres largos y los identificadores de versión se ajustan dentro del panel en lugar de cortarse o desbordarse, y el marcador de seguridad sigue junto a su paquete.

### 🔐 Cambio de contraseña con autenticación de dos factores

- **Cambiar la contraseña del Monitor funciona con y sin 2FA activada.** Con la autenticación de dos factores activada, el formulario pide el código actual del autenticador o un código de respaldo y lo envía con el cambio. Los campos que faltan o no son válidos se rechazan como errores de validación.
- Una pestaña del navegador ya abierta puede completar igualmente un cambio de contraseña después de actualizar el Monitor.

### 🐍 Runtime de Python portable para HTTPS y WebSockets ([#331](https://github.com/MacRimi/ProxMenux/issues/331), reportado por [@f3rs3n](https://github.com/f3rs3n))

- La AppImage del Monitor lleva runtimes aislados de gevent tanto para CPython 3.11 (Proxmox VE 8) como para CPython 3.13 (Proxmox VE 9), y `AppRun` selecciona el árbol correspondiente a partir del intérprete del host antes de arrancar Flask — con lo que se recupera el servidor HTTPS/WSS de gevent previsto en todas las generaciones de Proxmox VE compatibles.
- Las dependencias nativas se fijan y se empaquetan de forma determinista, y cada compilación importa la pila integrada con intérpretes 3.11 y 3.13 reales antes de publicarse.

### 📊 Métricas históricas compartidas en hosts más lentos (reportado por Rafael Fernández Díez)

- Las gráficas de CPU, memoria y red comparten una sola consulta en curso por intervalo de tiempo, con la vista predeterminada de 24 horas precargada y un presupuesto limitado por consulta.
- Un fallo temporal conserva la última instantánea válida con su hora de obtención y un aviso traducido de datos desactualizados, y las gráficas se recuperan solas sin sustituir un intervalo más reciente por una respuesta más antigua.

### 🔄 Versiones de aplicaciones coherentes entre App y Actualizaciones (reportado por Nicolas Ortuzar)

- Las aplicaciones LXC registradas usan una única instantánea compartida y versionada en archivo para la pestaña App, Actualizaciones y la caché del modal, así que la pestaña App ya no puede mostrar una versión disponible o una fecha de comprobación más antigua que la notificación que acabas de recibir.
- Las tarjetas de App abiertas reciben los cambios de estado de versión a través del flujo de datos existente, sin nuevos sondeos, y una actualización en segundo plano no toca los campos del editor sin guardar.

---

## 📦 Instalador, actualizaciones y post-instalación

- **El instalador muestra sus pasos, no la salida de apt**, y un host sin suscripción se instala sin errores de apt en pantalla. Las declaraciones de repositorio duplicadas se comentan.
- **Las comprobaciones de dependencias conservan los repositorios de Proxmox configurados** ([PR #407](https://github.com/MacRimi/ProxMenux/pull/407), aportado por [@f3rs3n](https://github.com/f3rs3n)): el cambio a no-subscription se ofrece, no se aplica, y queda registrado en Audit & Report.
- **pigz sigue funcionando tras una actualización de gzip** ([PR #414](https://github.com/MacRimi/ProxMenux/pull/414), [PR #415](https://github.com/MacRimi/ProxMenux/pull/415), aportado por [@pbr85](https://github.com/pbr85)): gzip se desvía en lugar de sustituirse, y se aplica su nivel de compresión. Los helpers del registro informan de una copia que no se puede escribir ([PR #417](https://github.com/MacRimi/ProxMenux/pull/417), [PR #418](https://github.com/MacRimi/ProxMenux/pull/418)).
- **La personalización de Bashrc nunca pierde lo que ya hay** ([PR #515](https://github.com/MacRimi/ProxMenux/pull/515), aportado por [@f3rs3n](https://github.com/f3rs3n)): una nueva ejecución deja como están los bloques incompletos o anidados, y el archivo nuevo sustituye al antiguo en un solo paso, así que una escritura fallida lo deja intacto.
- **Cada optimización se describe por lo que hace** ([PR #517](https://github.com/MacRimi/ProxMenux/pull/517), aportado por [@f3rs3n](https://github.com/f3rs3n)): Log2RAM, kexec, AMD, el guest agent y los límites de backup ya no prometen lo que sus funciones no ofrecen.
- **Una VM solo se crea a partir de una ISO completa** ([PR #458](https://github.com/MacRimi/ProxMenux/pull/458), aportado por [@f3rs3n](https://github.com/f3rs3n)): la imagen y los drivers VirtIO solo se publican una vez descargados por completo, una descarga fallida se detiene antes de crear la VM, y las imágenes de Debian 13, Rockstor y OpenMediaVault apuntan a sus fuentes actuales.
- **Los loaders de Synology vuelven a descargarse y desempaquetarse** ([PR #459](https://github.com/MacRimi/ProxMenux/pull/459), aportado por [@f3rs3n](https://github.com/f3rs3n)): el selector de M-shell toma la imagen de Alpine que proporciona ahora el autor, y una descarga o extracción fallida se detiene antes de crear la VM, conservando la imagen anterior.
- **FygoOS se incorpora a los sistemas NAS de Crear VM.** ProxMenux descarga el último instalador publicado en fygonas.com y prepara la VM con el mismo asistente que TrueNAS u OpenMediaVault: UEFI sin claves de Secure Boot, el plan de almacenamiento y la GPU opcional.
- **Los instaladores de VM Cloud-Init de Helper-Scripts vuelven a funcionar** ([PR #457](https://github.com/MacRimi/ProxMenux/pull/457), aportado por [@f3rs3n](https://github.com/f3rs3n)): Arch Linux, Debian y Ubuntu usan los scripts mantenidos, que preguntan ellos mismos por la versión, y una descarga fallida se detiene con un error antes de ejecutar nada.
- **Una actualización del sistema detenida por un repositorio de otra versión de Proxmox lo indica**: el mensaje dice qué repositorio de Proxmox VE o Ceph es de otra suite de Debian, en qué archivo, y que se desactiva en Node > Updates > Repositories.
- **La actualización de PVE 8 → 9 se detiene cuando el plan eliminaría `proxmox-ve`** ([PR #349](https://github.com/MacRimi/ProxMenux/pull/349), aportado por [@f3rs3n](https://github.com/f3rs3n)), y una actualización fallida de los índices se notifica como tal.
- **La post-instalación lee la memoria del host en cualquier idioma** ([#353](https://github.com/MacRimi/ProxMenux/issues/353), reportado por [@linux-fertxo](https://github.com/linux-fertxo)), y Log2RAM 1.6 calcula su tamaño a partir de ella.
- **Log2RAM 1.7 conserva los registros más recientes del journal** (reportado por [@f3rs3n](https://github.com/f3rs3n)). Su sincronización ya no deja un archivo antiguo de journal activo en disco, así que tras un reinicio journald empieza una secuencia nueva y elimina primero sus archivos más antiguos. A los hosts con Log2RAM se les ofrece la actualización; surte efecto a partir del siguiente reinicio.
- **Una actualización de varias optimizaciones muestra solo sus pasos**, sea cual sea el flujo de post-instalación del que procede cada una.
- **La post-instalación automática ajusta los bridges del firewall después de las reglas udev de systemd**, como hace la personalizable (aportado por [@Vaso73](https://github.com/Vaso73)). A los hosts con la optimización de red se les ofrece la actualización.
- **Un perfil de swap ZRAM en la post-instalación personalizable** ([PR #450](https://github.com/MacRimi/ProxMenux/pull/450), aportado por [@phyrexia](https://github.com/phyrexia)): un swap comprimido en RAM, de una décima parte de su tamaño, que se usa antes que el swap en disco. No toca ninguna otra configuración de ZRAM, se puede revertir desde Desinstalar optimizaciones, y la tarjeta Memoria del Monitor muestra su uso y su ratio de compresión.
- **Figurine 2.1.1 instala la compilación correspondiente al host** ([PR #465](https://github.com/MacRimi/ProxMenux/pull/465), aportado por [@jcastro](https://github.com/jcastro)): amd64, arm64 o ARMv7. A los hosts con Figurine se les ofrece la actualización.
- **Fastfetch conserva sus módulos del sistema en las versiones actuales** ([PR #355](https://github.com/MacRimi/ProxMenux/pull/355), aportado por [@f3rs3n](https://github.com/f3rs3n)).
- **La actualización de Proxmox VE 8 a 9 mantiene los guests en marcha mientras prepara el host** y se detiene si la actualización de Proxmox VE 8 falla o se cancela, antes de mover ningún repositorio a Trixie. Sin suscripción, el repositorio enterprise que pve-manager 9 añade durante la actualización se deja desactivado. La opción desatendida inicia la actualización, y el modo interactivo instala grub-efi-amd64 sin quedarse esperando una pregunta oculta.
- **Desinstalar ProxMenux no deja nada en su directorio de instalación**, y Mostrar información de versión cuenta como instalado el jq instalado desde GitHub. En español, el canal de publicación se llama «canal de versiones».
- **El menú de ayuda añade `qm unlock` y `pct unlock`**, y elegir la opción de usuarios de CT ya no vuelve a ejecutar el comando anterior.
- **Se traducen los textos de menú con un espacio al principio o al final**, como las preguntas y la opción de volver del menú de ayuda, en todos los scripts.
- **Los comandos de almacenamiento del menú de ayuda buscan las exportaciones de un servidor NFS** con un comando `pvesm scan nfs` válido, y `pveupgrade` se describe como la actualización interactiva de paquetes que inicia.
- **Desinstalar las optimizaciones de la post-instalación elimina los límites de archivos abiertos que estableció**, en systemd y en el perfil de root, y la comprobación de Log2RAM se ejecuta cada 10 minutos con prioridad baja en los dos modos de post-instalación.
- **Añadir una GPU a una VM muestra los dispositivos que comparten su grupo IOMMU** cuando incluye dispositivos de otro slot, que la VM recibe junto con la GPU, antes del resumen.
- **El instalador de NVIDIA conserva el estado del parche NVENC del driver instalado**, así que el menú de versiones reconoce un driver parcheado.
- **Las correcciones para AMD indican cuándo una CPU no las necesita** ([#519](https://github.com/MacRimi/ProxMenux/issues/519), reportado por [@rollingafull](https://github.com/rollingafull)): un procesador AMD que no es EPYC ni Ryzen se reconoce como AMD y se deja sin cambios, con un mensaje que lo indica.

### 🧰 Migración segura de las personalizaciones históricas de Bashrc ([#328](https://github.com/MacRimi/ProxMenux/issues/328), reportado por [@f3rs3n](https://github.com/f3rs3n))

- La personalización de Bashrc migra el bloque exacto sin marcadores que escribían ProxMenux v1.1.3 y anteriores — y la variante histórica que escribía sus marcadores de forma literal — a un único bloque canónico, en lugar de añadir una segunda copia del prompt, de los ajustes del historial y de los alias.
- La detección exige la firma completa de ProxMenux y deja intactos los rangos de marcadores incompletos, así que nunca se eliminan personalizaciones ajenas. La ruta de prompt corta o completa elegida se mantiene tras la migración, y la sustitución atómica conserva los permisos y el propietario originales.

### 🛡 Log2RAM se actualiza sin interrumpir el journal activo ([#327](https://github.com/MacRimi/ProxMenux/issues/327), reportado por [@f3rs3n](https://github.com/f3rs3n))

- Las instalaciones existentes usan una migración de ProxMenux en su sitio en lugar de volver a ejecutar el instalador upstream, cuya ruta de reinstalación elimina los dos directorios de respaldo y deja temporalmente journald sin su montaje activo de `/var/log`.
- La actualización conserva la configuración, el intervalo de sincronización, el montaje tmpfs activo y los servicios en marcha, y sustituye solo los archivos que gestiona ProxMenux. Las instalaciones nuevas aplazan la activación al reinicio que ya pide el flujo de post-instalación.

### 🌀 Las preguntas de la post-instalación aparecen en su propia línea

- Cada paso cierra su indicador de progreso antes de dibujar la siguiente pregunta o menú, así que una pregunta como la elección de instalar Log2RAM se muestra en una línea limpia en lugar de sobre un indicador que sigue girando.

---

## 🌍 Idiomas y redacción

- **Los mensajes dicen exactamente lo que ha pasado** (aportado por [@f3rs3n](https://github.com/f3rs3n)). Una revisión de los menús y de los mensajes de backup, almacenamiento, Samba, Rclone, programador y OCI para que cada uno sea una frase completa que se pueda traducir entera y que afirme solo lo que se ha verificado: [PR #363](https://github.com/MacRimi/ProxMenux/pull/363), [PR #364](https://github.com/MacRimi/ProxMenux/pull/364), [PR #367](https://github.com/MacRimi/ProxMenux/pull/367), [PR #368](https://github.com/MacRimi/ProxMenux/pull/368), [PR #369](https://github.com/MacRimi/ProxMenux/pull/369), [PR #370](https://github.com/MacRimi/ProxMenux/pull/370), [PR #371](https://github.com/MacRimi/ProxMenux/pull/371), [PR #375](https://github.com/MacRimi/ProxMenux/pull/375), [PR #384](https://github.com/MacRimi/ProxMenux/pull/384), [PR #389](https://github.com/MacRimi/ProxMenux/pull/389), [PR #390](https://github.com/MacRimi/ProxMenux/pull/390), [PR #397](https://github.com/MacRimi/ProxMenux/pull/397), [PR #400](https://github.com/MacRimi/ProxMenux/pull/400), [PR #401](https://github.com/MacRimi/ProxMenux/pull/401).
- **Descripciones de los comandos de terminal en todos los idiomas** ([PR #351](https://github.com/MacRimi/ProxMenux/pull/351), [PR #354](https://github.com/MacRimi/ProxMenux/pull/354), aportado por [@f3rs3n](https://github.com/f3rs3n); [PR #362](https://github.com/MacRimi/ProxMenux/pull/362), aportado por [@Vaso73](https://github.com/Vaso73)).
- **El italiano** ([PR #422](https://github.com/MacRimi/ProxMenux/pull/422), [PR #424](https://github.com/MacRimi/ProxMenux/pull/424), [PR #426](https://github.com/MacRimi/ProxMenux/pull/426), [PR #429](https://github.com/MacRimi/ProxMenux/pull/429), [PR #432](https://github.com/MacRimi/ProxMenux/pull/432), [PR #437](https://github.com/MacRimi/ProxMenux/pull/437), [PR #516](https://github.com/MacRimi/ProxMenux/pull/516), [PR #522](https://github.com/MacRimi/ProxMenux/pull/522), aportado por [@f3rs3n](https://github.com/f3rs3n)) **y el eslovaco** ([PR #391](https://github.com/MacRimi/ProxMenux/pull/391), [PR #396](https://github.com/MacRimi/ProxMenux/pull/396), [PR #430](https://github.com/MacRimi/ProxMenux/pull/430), [PR #431](https://github.com/MacRimi/ProxMenux/pull/431), [PR #436](https://github.com/MacRimi/ProxMenux/pull/436), aportado por [@Vaso73](https://github.com/Vaso73)) cubren todo lo nuevo de esta versión, escritos por personas que los hablan.
- **Eslovaco de todo lo nuevo, en el Monitor y en la terminal** ([PR #508](https://github.com/MacRimi/ProxMenux/pull/508), [PR #509](https://github.com/MacRimi/ProxMenux/pull/509), [PR #510](https://github.com/MacRimi/ProxMenux/pull/510), [PR #511](https://github.com/MacRimi/ProxMenux/pull/511), [PR #512](https://github.com/MacRimi/ProxMenux/pull/512), [PR #513](https://github.com/MacRimi/ProxMenux/pull/513), aportado por [@Vaso73](https://github.com/Vaso73)): conexiones y estado de PBS, nodos enlazados, backup del host, ZRAM y post-instalación de PBS, OCI manager, el editor de aplicaciones y el visor del código fuente de las optimizaciones. Sus errores se muestran en el idioma de quien los lee, una actualización o modificación OCI cancelada dice que se ha cancelado, y los mismos textos están completos en los otros seis idiomas.
- **El alemán del Monitor revisado por un hablante nativo** ([PR #455](https://github.com/MacRimi/ProxMenux/pull/455), aportado por [@detlefs](https://github.com/detlefs)): términos mal traducidos corregidos y redacción coherente en toda la interfaz.
- **Una traducción que existe nunca se sustituye.** Las compilaciones de traducciones solo escriben donde no hay nada, mantienen las listas como listas y protegen los nombres que no son palabras: `nouveau`, `initramfs`, `vfio-pci`, los nombres de las versiones de Debian y el resto.
- **El sueco se puede elegir al instalar ProxMenux, y todas las traducciones mantienen intactos los comandos y los nombres** ([PR #475](https://github.com/MacRimi/ProxMenux/pull/475), aportado por [@jcastro](https://github.com/jcastro)): una comprobación offline rechaza una traducción que cambie un comando, una ruta, una variable o un marcador de posición, en los menús y en la documentación, y los textos que lo hacían se corrigieron en todos los idiomas.
- **Etiquetas del Monitor corregidas en alemán, sueco, portugués y francés**: el campo Puerto, los botones de 2FA, el nombre de los códigos de respaldo y las palabras del portugués europeo para nombre de usuario, contraseña y forzar la parada.
- **El español del Monitor y de los menús sigue un mismo estilo**: se trata al lector de *tú*, los botones y las opciones de menú usan el infinitivo y el vocabulario es el de España (*pulsar*, *introducir*, *añadir*, la tecla *Intro*). Backup, snapshot, host, pool y slot se mantienen en inglés, y se corrigieron varios textos mal traducidos. La guía para traductores lo describe.
- **El español de los menús y del catálogo OCI se reescribió a mano**, y las 28 categorías del catálogo están escritas a mano en todos los idiomas.
- **Los conjuntos de pruebas offline cubren todos los idiomas incluidos** ([PR #380](https://github.com/MacRimi/ProxMenux/pull/380), [PR #381](https://github.com/MacRimi/ProxMenux/pull/381), [PR #383](https://github.com/MacRimi/ProxMenux/pull/383), aportado por [@f3rs3n](https://github.com/f3rs3n)).
- **El Monitor está completo en eslovaco**, Audit & Report incluido ([PR #329](https://github.com/MacRimi/ProxMenux/pull/329), [PR #330](https://github.com/MacRimi/ProxMenux/pull/330), [PR #344](https://github.com/MacRimi/ProxMenux/pull/344), [PR #345](https://github.com/MacRimi/ProxMenux/pull/345), aportado por [@Vaso73](https://github.com/Vaso73)). Las categorías de aplicaciones se traducen para mostrarlas mientras los valores propios del catálogo no se tocan para el filtrado, así que la búsqueda coincide con cualquiera de los dos que escribas.
- **Se traducen los textos restantes del panel y de los menús** ([PR #470](https://github.com/MacRimi/ProxMenux/pull/470), aportado por [@jcastro](https://github.com/jcastro)), y añadir un mensaje nuevo ya no rompe las pruebas de traducción ([PR #469](https://github.com/MacRimi/ProxMenux/pull/469)).
- **`host` y `cluster` se leen como tales en todos los idiomas**, tanto en las etiquetas como en la prosa, y cada idioma usa el término que su propio catálogo ya había establecido.
- **El panel de interfaces de red vuelve a contar paquetes**: los errores y los paquetes descartados se nombran para recepción y transmisión en lugar de traducirse como frases normales.
- **Los números se formatean en el idioma de quien los lee**, y el estado «en ejecución» se lee como un estado y no como la acción física de correr, en alemán, español, francés, italiano, portugués y sueco.
- Los nombres de los días de la semana en las actualizaciones programadas se resuelven correctamente, y las acciones de encendido de VM y LXC siguen la redacción en español del propio Proxmox: *Apagar* para la acción ordenada, *Parar* para la forzada.

---

## 📚 Documentación

- **La documentación de la web se revisó en las siete traducciones** ([PR #476](https://github.com/MacRimi/ProxMenux/pull/476), [PR #477](https://github.com/MacRimi/ProxMenux/pull/477), [PR #478](https://github.com/MacRimi/ProxMenux/pull/478), [PR #479](https://github.com/MacRimi/ProxMenux/pull/479), [PR #480](https://github.com/MacRimi/ProxMenux/pull/480), [PR #481](https://github.com/MacRimi/ProxMenux/pull/481), [PR #482](https://github.com/MacRimi/ProxMenux/pull/482), [PR #483](https://github.com/MacRimi/ProxMenux/pull/483), [PR #484](https://github.com/MacRimi/ProxMenux/pull/484), [PR #485](https://github.com/MacRimi/ProxMenux/pull/485), [PR #486](https://github.com/MacRimi/ProxMenux/pull/486), [PR #487](https://github.com/MacRimi/ProxMenux/pull/487), [PR #488](https://github.com/MacRimi/ProxMenux/pull/488), [PR #489](https://github.com/MacRimi/ProxMenux/pull/489), [PR #490](https://github.com/MacRimi/ProxMenux/pull/490), [PR #491](https://github.com/MacRimi/ProxMenux/pull/491), aportado por [@jcastro](https://github.com/jcastro)): páginas de instalación y de referencia, post-instalación, creación de VM, discos, compartición de almacenamiento, red, backup y restauración, seguridad, ajustes, utilidades, el Monitor, OCI manager, referencias de comandos, guías prácticas y las guías de GPU y Coral.
- **OCI manager tiene su propia documentación**: qué instala y cómo, el catálogo, las aplicaciones multicontenedor, las actualizaciones y la recuperación, el formato oci-compose y su uso desde el Monitor, con diagramas y capturas de pantalla.
- **La página de colaboradores da las gracias a las personas que hay detrás de cada versión**: quienes desarrollan, revisan, traducen y prueban ProxMenux hoy, y quienes le ayudaron a dar sus primeros pasos.

---

## 🙏 Agradecimientos

- **[@Vaso73](https://github.com/Vaso73)** — las pruebas comparativas de las aplicaciones OCI frente a sus originales de Docker y las correcciones que salieron de ellas, la reconstrucción de las aplicaciones multicontenedor a partir de su estado guardado, las notificaciones en el idioma de quien las lee, Buscar aplicaciones para servicios instalados a mano y para contenedores Docker, la búsqueda y el filtro de actualizaciones de VM y LXC, los detectores verificados en ejecución, los resultados de actualización de los contenedores detenidos y los controles de encendido que siguen su tarea de Proxmox, las fechas de revisión y la comparación de Audit & Report, y el eslovaco completo del Monitor y de la terminal.
- **[@f3rs3n](https://github.com/f3rs3n)** — la revisión de cientos de mensajes en los menús, los backups, el almacenamiento y OCI manager, las notificaciones de backup, salud, temperatura y clúster, las salvaguardas del formateo de discos y de la restauración del host, las comprobaciones de repositorios y de actualización de PVE, los loaders de Synology, las migraciones de Bashrc y Log2RAM, el informe sobre el ámbito de los tokens de API, el runtime de Python portable, los conjuntos de pruebas y el italiano completo de esta versión.
- **[@jcastro](https://github.com/jcastro)** — ProxMenux en Proxmox Backup Server, las cuentas de registros privados de OCI manager Apps, Gestionar, ciento diecisiete aplicaciones curadas del catálogo ([PR #520](https://github.com/MacRimi/ProxMenux/pull/520), [PR #521](https://github.com/MacRimi/ProxMenux/pull/521), [PR #524](https://github.com/MacRimi/ProxMenux/pull/524), [PR #525](https://github.com/MacRimi/ProxMenux/pull/525)), Modificar y Actualizar más rápidos, Modificar aplicado al contenedor en marcha, la búsqueda de actualizaciones desde el menú OCI, los backups en modo snapshot en ZFS, la conservación de las etiquetas de Proxmox entre operaciones, Figurine para todas las arquitecturas, la guía de Slack y Matrix para Apprise, la retención de los almacenamientos de backups, la eliminación de backups de guests, las comprobaciones de LVM que respetan las exclusiones de discos, las comprobaciones de traducción, las traducciones restantes y la revisión de la documentación en todos los idiomas.
- **[@byGarcia](https://github.com/byGarcia)** — el registro de aplicaciones Docker y el seguimiento de versiones de imagen, con detectores verificados y pruebas de laboratorio, y las imágenes Docker ancladas por digest.
- **[@MattiaC46](https://github.com/MattiaC46)** — los trabajos de backup de VM y CT.
- **[@SystemIdleProcess](https://github.com/SystemIdleProcess)** — el diseño de la selección explícita del actualizador y el detector de Changedetection.io.
- **[@detlefs](https://github.com/detlefs)** — la revisión del alemán del Monitor.
- **[@pbr85](https://github.com/pbr85)** — el desvío de gzip para pigz y los helpers del registro.
- **[@phyrexia](https://github.com/phyrexia)** — el perfil de swap ZRAM y sus métricas en el Monitor.
- **[@fklnc94](https://github.com/fklnc94)** y **[@wolly6973](https://github.com/wolly6973)** — las notificaciones de nodos del clúster y el descarte de montajes remotos obsoletos.
- **[@pdafoto](https://github.com/pdafoto)**, **[@gabglus](https://github.com/gabglus)**, **[@dave100fuegos](https://github.com/dave100fuegos)** y **[@WRCAs](https://github.com/WRCAs)** — las aplicaciones sugeridas para el catálogo OCI y sus pruebas, y los detectores de LazyLibrarian y PeaNUT.
- **[@shtefko](https://github.com/shtefko)**, **[@Joshua1264](https://github.com/Joshua1264)**, **[@sbaghdadi](https://github.com/sbaghdadi)**, **[@ash34](https://github.com/ash34)**, **[@bartclone](https://github.com/bartclone)**, **[@spectante](https://github.com/spectante)**, **[@linux-fertxo](https://github.com/linux-fertxo)**, **[@sponger544](https://github.com/sponger544)**, **[@LucasR3C3](https://github.com/LucasR3C3)**, **[@tropicaljoe](https://github.com/tropicaljoe)**, **[@rollingafull](https://github.com/rollingafull)**, **@sahartford**, **@christiannieveslauz**, **Maragath**, **Charly Silva**, **Nicolas Ortuzar** y **Rafael Fernández Díez** — los informes detrás del tratamiento de `/etc/pve`, los errores de log persistentes, los backups del host con SELinux, el recuento y el log de actualizaciones, los repositorios Borg remotos, el reposo de los discos, la post-instalación en cualquier idioma, el nombre del nodo en hosts lentos, el passthrough de GPU en APU AMD, la restauración del certificado, las correcciones para AMD, las notificaciones de backup por HTTPS, las exclusiones de almacenamiento, los descartes permanentes, los directorios compartidos del host, los backups del host en un clúster, los backups de trabajos anteriores, el historial de notificaciones, la coherencia de las versiones de aplicaciones y las métricas históricas en hosts más lentos.

Los comentarios son bienvenidos en [Discussions](https://github.com/MacRimi/ProxMenux/discussions) o como issue.

---

Para el historial completo de cambios, consulta [Releases](https://github.com/MacRimi/ProxMenux/releases).

---


## 2026-09-02

### Nueva versión ProxMenux v1.2.6

Una versión centrada en restaurar el soporte del Asistente IA para endpoints compatibles con OpenAI alojados en IPs privadas, loopback y redes Docker, alinear el asistente de Secure Gateway con la arquitectura real del host, y consolidar varias mejoras que ya venían acumulándose en develop: entrega atómica de notificaciones, puerto SSH personalizado para destinos remotos Borg, token opcional de la API de GitHub para el seguimiento de versiones de aplicaciones y notificaciones de fallo de replicación con contexto completo.

---

## 🛠 Endpoint OpenAI personalizado del Asistente IA — URLs de LAN / Docker / localhost

- Los endpoints compatibles con OpenAI accesibles en IPs privadas, loopback o redes Docker (LiteLLM, LM Studio, LocalAI, vLLM, OmniRoute, proxies autoalojados…) se aceptan al cargar el catálogo de modelos y al validar la configuración de IA.
- El desplegable muestra el motivo devuelto por el servidor (o el error de red subyacente) justo debajo del botón *Cargar*, así una configuración incorrecta deja de aparecer como una lista vacía y silenciosa.
- Traducido a todos los idiomas del Monitor.

Reportado en la [issue #325](https://github.com/MacRimi/ProxMenux/issues/325) por [@jorgeffonte](https://github.com/jorgeffonte).

---

## 🛠 Asistente Secure Gateway — la plantilla LXC coincide con la arquitectura del host

- La descarga de la plantilla Alpine filtra los resultados de `pveam available` por la arquitectura del host (mediante `dpkg --print-architecture`, con fallback a `uname -m`), así un host Proxmox x86_64 recibe la plantilla `amd64` y un host arm64 recibe la plantilla `arm64`.
- La selección de plantilla local aplica el mismo filtro de arquitectura al reutilizar una plantilla Alpine ya descargada.
- `pct create` se invoca con `--arch <host>` explícito para que los metadatos del contenedor reflejen la arquitectura real del host.

Reportado en la [issue #324](https://github.com/MacRimi/ProxMenux/issues/324) por [@N0X4DD0](https://github.com/N0X4DD0).

---

## 🔔 Entrega atómica de notificaciones

- Los eventos de notificación reservan su huella de deduplicación de forma atómica antes del procesado por IA y del envío por canal, de modo que colectores concurrentes, callbacks de finalización o procesos Monitor paralelos accidentales no pueden enviar el mismo evento dos veces.
- La reserva se comparte a través de SQLite, expira de forma segura si una ejecución se interrumpe y se libera cuando ningún canal tiene éxito, preservando los reintentos ante fallos transitorios de transporte.

---

## 🗄 Destino remoto Borg — puerto SSH personalizado

- El diálogo *Añadir destino Borg* del Monitor y el TUI del shell (`menu` → *Host Backup* → *New Borg target*) aceptan un puerto SSH personalizado. El valor por defecto sigue siendo `22`; cualquier valor entre 1 y 65535 se incrusta en la URL `ssh://user@host:port/path` persistida.
- `BORG_RSH` respeta el puerto personalizado en el momento del backup, así los jobs programados y las ejecuciones manuales alcanzan el puerto correcto.
- El flujo de instalación automática de clave (`generate-auto`) también apunta al puerto personalizado.
- Totalmente retrocompatible con las entradas existentes en `borg-targets.txt` creadas sin puerto explícito.
- Las sondas de capacidad sobre SSH también respetan el puerto personalizado, así la insignia *Available* permanece precisa en puertos no estándar.

Reportado en la [discusión #236](https://github.com/MacRimi/ProxMenux/discussions/236) por [@songochain](https://github.com/songochain).

---

## 🎯 Seguimiento de versiones de aplicaciones — token opcional de la API de GitHub

- **Settings → GitHub API** acepta un token de acceso personal opcional para las comprobaciones de releases y tags cuando se agota la cuota anónima de GitHub.
- El token se guarda cifrado, nunca se devuelve al navegador y puede sustituirse o eliminarse de forma independiente del servicio de Notificaciones.
- El flujo anónimo de GitHub sigue siendo el predeterminado; no se requiere un token mientras la cuota compartida sin autenticar esté disponible.
- El error de límite de tasa apunta al ajuste real y está traducido en todos los idiomas del Monitor.

Reportado en la [discusión #306](https://github.com/MacRimi/ProxMenux/discussions/306) por [@SystemIdleProcess](https://github.com/SystemIdleProcess).

---

## 🔁 Notificaciones de fallo de replicación — contexto completo del job

- Los webhooks nativos de replicación de Proxmox resuelven el ID del trabajo de replicación, el ID de la VM/LXC afectada y el nombre del guest antes de renderizar la notificación.
- El bloque de error exacto proporcionado por Proxmox se conserva como motivo, incluyendo fallos multilínea, con el mensaje completo como fallback seguro cuando el bloque no está presente.
- Las notificaciones de replicación se identifican por su ID de job completo, así los fallos de trabajos de replicación distintos permanecen independientes durante la deduplicación.

Reportado por Ale R.

---

Para el historial completo de cambios, consulta [Releases](https://github.com/MacRimi/ProxMenux/releases).

---


## 2026-09-01

### Nueva versión ProxMenux v1.2.5

Esta versión convierte la gestión de aplicaciones de los contenedores LXC en una función completa del Monitor. El nuevo panel **Apps** reúne los accesos web del nodo, mientras que **Easy Updates** permite comprobar y aplicar por separado actualizaciones del sistema operativo, aplicaciones, Docker Engine e imágenes Docker. ProxMenux incorpora además un catálogo de detección con más de 380 aplicaciones, ocho idiomas en el Monitor, orden de navegación personalizable y mejoras importantes en copias del host, automatización, salud del sistema, hardware y post-instalación.

---

## 🚀 Apps — un lanzador para los servicios del nodo

- Nueva pestaña superior **Apps** con todos los enlaces web registrados en los LXC y los enlaces personalizados añadidos por el usuario.
- Búsqueda, categorías, ordenación y acceso directo al LXC o VM relacionado.
- Los enlaces personalizados permiten integrar servicios alojados en máquinas virtuales, endpoints externos, reverse proxies o cualquier URL habitual.
- Las aplicaciones Docker se muestran como servicios del motor que las aloja, evitando presentarlas como aplicaciones nativas independientes del LXC.
- Los iconos, categorías y estados se adaptan al tema y al idioma seleccionado.

---

## 🔄 Easy Updates para LXC

- La pestaña **Updates** separa claramente las actualizaciones del sistema operativo, de cada aplicación registrada, de Docker Engine y de cada proyecto o imagen Docker.
- Los métodos compatibles con **Proxmox VE Helper-Scripts**, incluidos contenedores antiguos y actuales, se detectan automáticamente cuando existe un actualizador válido.
- Las aplicaciones instaladas manualmente pueden usar detectores de versión y comandos de actualización personalizados.
- Nueva **Actualización en bloque**: el usuario decide qué aplicaciones, Docker Engine y proyectos Docker acompañan a la actualización obligatoria del sistema operativo.
- Los servicios pertenecientes a un mismo proyecto Compose se actualizan en una sola operación para evitar recreaciones repetidas.
- Las comprobaciones de imágenes Docker se basan en el digest del registro, siguen el ciclo de 24 horas y también pueden forzarse con **Comprobar ahora**.
- Los resultados se mantienen en caché y se actualizan tras guardar una aplicación, completar una actualización o producirse un evento de arranque, parada, reinicio o restauración del guest.

---

## 🎯 Catálogo de detección de aplicaciones

- Nuevo catálogo generado a partir de los scripts LXC reales de `community-scripts/ProxmoxVE`, fijando un commit concreto para que cada generación sea reproducible.
- Más de **380 aplicaciones** cubiertas mediante detectores de paquete dpkg/apk, binario, archivo con expresión regular, distribución Python y métodos Docker.
- Detectores alternativos y rutas verificadas permiten reconocer tanto instalaciones modernas como estructuras históricas.
- Nombre, web oficial, puerto predeterminado, categoría y logotipo pueden rellenarse automáticamente y siguen siendo editables.
- El botón **Buscar aplicaciones** permite lanzar una detección completa solo para el LXC seleccionado cuando se haya instalado algo nuevo.

---

## 🌍 Monitor multilingüe y navegación personalizable

- El Monitor está disponible en **inglés, español, alemán, francés, italiano, portugués, eslovaco y sueco**.
- Nueva opción **Orden de navegación** para reorganizar las pestañas principales y elegir de forma indirecta qué vista abre primero.
- La selección se conserva por dispositivo y también se respeta en el menú móvil.
- La documentación incorpora un flujo incremental y reanudable para mantener los idiomas sin sobrescribir traducciones revisadas por personas.

---

## ⚡ Monitor, automatización y experiencia de uso

- Los modales de VM/LXC y sus pestañas reutilizan datos precargados por guest, reduciendo esperas y evitando recargas completas al cambiar de vista.
- Nueva **Actions API** para reinicio/apagado del host, actualización segura de Proxmox, actualización de ProxMenux y operaciones de VM/LXC desde Home Assistant, Ansible u otras automatizaciones.
- **Pushover** se incorpora como canal nativo de notificaciones, con credenciales cifradas, prioridad para alertas críticas y los mismos filtros que el resto de canales.
- Fail2Ban permite gestionar desde Seguridad las redes e IP de confianza.
- Network Flow reconoce interfaces bond y respeta la preferencia Bits/Bytes.

---

## 🩺 Salud, almacenamiento y hardware

- Las alertas de memoria combinan uso alto de swap con RAM realmente disponible, reduciendo falsos positivos en hosts Proxmox con ZFS.
- El Monitor correlaciona los sensores NVMe y `drivetemp` con el dispositivo, modelo y número de serie físicos.
- Las VM con QEMU Guest Agent muestran el uso agregado real de sus sistemas de archivos y reciben alertas de espacio bajo.
- El instalador NVIDIA selecciona la rama mediante kernel, GPU y PCI ID, y el passthrough multi-GPU trabaja por BDF exacto para permitir que una GPU permanezca en el host mientras otra pertenece a una VM.
- La disponibilidad de storages Proxmox se decide por su estado real, aunque un backend como iSCSI no informe capacidad.

---

## 🗄 Copias y restauración del host

- Las copias conservan la configuración completa de los jobs de ProxMenux y reconstruyen de forma validada sus timers o hooks tras restaurar.
- Las rutas personalizadas se copian exactamente como las seleccionó el usuario, sin aplicar exclusiones genéricas pensadas para el perfil integrado.
- El staging aborta ante fallos reales de copia para no presentar como válido un archivo incompleto.
- La base `config.db` de pmxcfs se captura mediante una copia SQLite consistente y los pools ZFS de datos pueden importarse automáticamente durante la restauración.

---

## 🛡 Post-instalación y compatibilidad

- Funciones de post-instalación con rollback más preciso y preparación para Debian 13.
- Optimización ZFS ARC alineada con la política de Proxmox, reconciliación segura de límites duplicados y diagnósticos OOM basados en el bloque completo del kernel.
- Personalización Bashrc con elección entre directorio actual y ruta completa.
- Nombres persistentes de NIC, ajuste de bridges del firewall, Log2RAM en hosts con PBS y recompilación DKMS tras instalar un kernel nuevo reforzados para actualizaciones y re-ejecuciones seguras.

---

## 🩹 Correcciones destacadas

- Las copias de VM/LXC de larga duración ya no quedan limitadas por una espera HTTP de 60 segundos.
- Los webhooks PVE remotos conservan correctamente el secreto y los informes largos de `vzdump` llegan completos al analizador.
- El Monitor respeta discos en standby y las pruebas SMART programadas aceptan correctamente rutas `/dev/...`.
- Los jobs PBS programados conservan el fingerprint del servidor y el runner interpreta de forma segura los archivos `.env` heredados.
- Las actualizaciones seguras comprueban conectividad HTTPS en lugar de depender de ICMP.
- El certificado Proxmox/ACME utilizado por HTTPS se renueva en nuevas conexiones TLS; si el par todavía se está escribiendo o no coincide, el Monitor conserva el último contexto validado.
- La configuración de autenticación puede abrirse de nuevo después de haberla rechazado inicialmente.
- Se corrigieron instalaciones, desinstalaciones y actualizaciones de varias optimizaciones heredadas sin alterar configuraciones administradas por el usuario.

---

## 🙏 Agradecimientos

Un agradecimiento especial a **@vaso73**, cuya colaboración sostenida ha dado forma a este release: la base de i18n que hizo posible el Monitor multilingüe, la traducción completa al eslovaco y una serie de PRs de refuerzo en autenticación, Fail2Ban, flujos LXC y webhooks `vzdump` durante todo el ciclo beta 1.2.4.

Gracias también a **@agarmoli, @SystemIdleProcess, @TCBWZA, @DeXon18, @mrkaffeine92, @Turtletrumpet, @Skynet011, @mon5termatt, @gail7-github, @f3rs3n, @bofrot0603, @MrCaringi, @nikp79, @ThisWasNotTaken, @yeager, @mfmen, @Marceenek, @beyercenter, @peterurbanec, @tropicaljoe, @Dark-Witcher, @benginx, @Atredis76 y LeidenSpain** por las ideas, pruebas, traducciones, diagnósticos, parches e informes durante las betas 1.2.4.1 y 1.2.4.2.

> 📖 **Para ver todos los cambios y su narrativa completa, consulta los releases:** [Releases de ProxMenux en GitHub](https://github.com/MacRimi/ProxMenux/releases)

---



## 2026-07-22

### Nueva versión ProxMenux v1.2.4

Esta versión suma dos mejoras visibles en el propio dashboard — un botón para lanzar la actualización de Proxmox desde el Monitor de Salud, y un prompt para invitar a los usuarios móviles a instalar el Monitor como PWA — extiende el flujo de restauración de Backups con snapshots consistentes de pmxcfs (`config.db`) e importación automática de pools ZFS de datos, refina el comportamiento de Log2RAM en hosts que corren Proxmox Backup Server como servicio, refuerza el ajuste de sysctl de los bridges del firewall en todo el ciclo de vida de VMs, ajusta la optimización de ZFS ARC a su propio ámbito, hace idempotentes los nombres persistentes de NIC en re-ejecuciones, recompila automáticamente los drivers DKMS cuando entra un kernel nuevo, mantiene intacta la sesión de la terminal del Monitor cuando hay update de ProxMenux disponible, y afina cinco plantillas de notificaciones y tres chequeos del panel de salud.

---

## 🩺 Botón Update Now en el Monitor de Salud

- Nuevo botón **Update Now** dentro del modal del Monitor de Salud, en la sección **System Updates**.
- Ejecuta el flujo estándar de actualización de Proxmox (`apt update` + `dist-upgrade` + limpieza posterior) en una terminal dentro del dashboard — sin necesidad de abrir una shell.
- Solo aparece cuando hay actualizaciones pendientes; si el sistema está al día, el botón queda oculto.
- Al cerrar, el Monitor de Salud fuerza un refresh con invalidación de caché (`/api/health/full?refresh=1`) para que el contador de actualizaciones pendientes y la fila del kernel reflejen el estado post-actualización al instante, en lugar del valor pre-actualización que la caché de fondo había guardado justo antes de la ejecución.
- El script subyacente distingue el contexto: si se ejecuta sobre un host ya en producción, respeta los repositorios personalizados del usuario (no desactiva enterprise/ceph, no borra sources legacy, no purga NTP alternativos ni fuerza instalar zfsutils/chrony); si detecta un servidor virgen crea los repos base necesarios. Detecta también si hay un kernel nuevo instalado distinto del que está corriendo y pide el reboot al terminar.
- Durante la actualización se suprimen las notificaciones de `service_fail` de servicios PVE (pve-cluster, pveproxy, corosync…) porque su reinicio es parte normal del upgrade; volvían a notificarse hasta 60 s después de que apt termine.

---

## 📱 Prompt de instalación en la app para móvil

- Los visitantes por primera vez en **Android** (Chrome / Brave) e **iOS Safari** ven ahora una bottom-sheet con instrucciones claras para añadir el Monitor a su pantalla de inicio como PWA.
- La instalación se hace a través de la propia entrada del menú del navegador ("Añadir a pantalla de inicio"), que produce una PWA real instalada que se lanza en modo standalone. La bottom-sheet no intercepta el evento `beforeinstallprompt` del navegador — interceptarlo sin llegar a llamar a `prompt()` degrada la ruta manual del menú a un acceso directo simple, que es lo que apareció en las pruebas de campo.
- Dos niveles de descarte: **Not now** (temporal, reaparece a los 30 días) y **Don't show again** (permanente, almacenado en `localStorage`).
- No se muestra en escritorio, ni cuando el Monitor ya se está ejecutando como aplicación instalada.

---

## 🔔 Contenido de notificaciones — cinco refinamientos de renderizado

- **Destino de backup en título y cuerpo.** Los correos y mensajes de Telegram de backup de VM/CT llevan el storage / destino PBS, de modo que en instalaciones con varios destinos se identifica de un vistazo qué backup produjo el evento.
- **Los cuerpos de migración llevan el nodo destino real** — extraído del log de la tarea PVE para eventos `qmigrate` / `vzmigrate`.
- **Los cuerpos de snapshot llevan el nombre real del snapshot** — extraído del log de la tarea PVE para eventos `qmsnapshot` / `vzsnapshot`.
- **Las notificaciones genéricas `system_problem` incluyen la razón real** — el cuerpo del payload de PVE se surface como cuerpo de la notificación.
- **Los correos de actualización de driver NVIDIA / Coral renderizan correctamente la fila *New Version*** — el placeholder del template está ahora alineado con el campo que lee el renderer.

---

## 🩹 Panel de salud — tres chequeos reforzados

- **Dismiss silencia ahora las alertas de storage.** El flujo de acknowledge cubre `storage_unavailable`, `mount_stale`, `mount_readonly`, `lxc_disk_low`, `lxc_mount_low`, `pve_storage_full` y `zfs_pool_full` bajo la categoría `storage`, y el caché de storage se invalida al pulsar Dismiss para que el panel se refresque inmediatamente.
- **El chequeo de VMs & Containers tolera errores persistidos con la columna `details` a NULL** (#255). `_check_vms_cts_with_persistence` coalesciona un `details` ausente a un dict vacío antes de leer claves anidadas, de modo que una fila sparse suelta ya no deja el chequeo completo fuera de servicio.
- **La notificación `system_startup` se dispara una sola vez por boot.** `_check_startup_aggregation` marca la agregación como completada justo después de encolar el evento, así que el resumen de arranque llega una única vez independientemente de cuántos ticks de polling entren en la sesión.

---

## 🛠 Móvil y webhook

- **El polling del dashboard en móvil se mantiene vivo sobre HTTPS + reverse proxy.** `pwa-register.tsx` auto-desregistra cualquier Service Worker al cargar, así que la limitación en segundo plano de los navegadores móviles deja de interferir con los fetch de polling, y la instalabilidad PWA se gestiona ahora desde el nuevo prompt in-app descrito arriba.
- **La autenticación del webhook confía en todas las IPs locales del host.** El webhook interno (`/api/notifications/webhook`) acepta peticiones desde cualquier IP de una interfaz que el host posee (Tailscale, WireGuard, LAN, IPv6, más la forma IPv4 mapeada en IPv6 `::ffff:x.x.x.x` que Flask reporta en bindings dual-stack), de modo que los botones Test de PVE funcionan a través de cualquiera de ellas.

---

## 🛡 Flujo de actualización — Monitor-terminal-aware para el update y para el cambio de canal

- **La terminal WebSocket del Monitor expone ahora `PROXMENUX_TERMINAL=monitor`** en el entorno de cada shell que abre, y cada proceso hijo lo hereda. Esto le da a `menu` (y a cualquier otro flow que le importe) una vía fiable y determinista para saber que la sesión actual vive dentro del proceso del Monitor — una sesión que quedaría cortada a mitad de instalación si el servicio del Monitor se reiniciara.
- **Prompt de update de `menu`** — cuando hay una nueva versión de ProxMenux disponible y la sesión corre dentro de la terminal del Monitor, el clásico prompt yes/no se sustituye por un msgbox informativo. El msgbox nombra la nueva versión y muestra el comando canónico de una línea (`bash -c "$(wget -qLO - …)"`) para ejecutar el update desde SSH o la consola del host Proxmox. Como el flow ya ha decidido que el path in-terminal es inseguro, hay un solo botón OK — no hay yes/no que pudiera disparar el update destructivo por accidente.
- **Ajustes → Canal de release** — el mismo guard se aplica en `apply_release_channel()` de `config_menu.sh`. Seleccionar Stable ↔ Beta desde la terminal del Monitor muestra un msgbox informativo con el comando `wget` exacto para el canal destino (usando la misma URL que el flow habría descargado por su cuenta) y vuelve al menú en lugar de ejecutar el installer en el sitio.
- **Tras pulsar OK, ambos flows continúan con normalidad.** El usuario sigue usando ProxMenux desde la misma terminal sin restricciones; solo el paso destructivo queda enrutado a otro sitio. No hay bloqueo ni acción forzada.
- **Las sesiones SSH, la consola del host Proxmox y cualquier entorno donde `PROXMENUX_TERMINAL` no sea `monitor` mantienen el comportamiento anterior** y pueden actualizar o cambiar de canal como siempre. El cambio solo afecta al caso en el que hacerlo en el sitio rompería la sesión activa.
- **Nota de bootstrap**: como `PROXMENUX_TERMINAL=monitor` lo añade el AppImage que ship-ea esta release, el guard solo empieza a proteger sesiones una vez que el host está en 1.2.4 o posterior. La primera actualización a 1.2.4, si se dispara desde la terminal del Monitor, aún puede caer en el comportamiento antiguo — a partir de 1.2.4 el guard queda en su sitio.

---

## 🔧 Flujo de actualización — Drivers DKMS recompilados cuando entra un kernel nuevo

- **Cuando `apt full-upgrade` deja preparado un kernel más nuevo que el que está en marcha, `update-pve-safe.sh` recompila ahora los drivers DKMS instalados por ProxMenux contra ese nuevo kernel.** El botón Update Now del Monitor de Salud y la utilidad CLI `utilities/proxmox_update.sh` delegan ambos en `update-pve-safe.sh`, así que las dos vías ganan el comportamiento. El paso lee `components_status.json`, cruza los componentes DKMS que ProxMenux gestiona (`nvidia_driver`, `coral_driver`), instala las cabeceras de kernel correspondientes (`proxmox-headers-<newkver>` o `pve-headers-<newkver>`) si no están ya presentes, y ejecuta `dkms autoinstall -k <newkver>`. Después verifica vía `dkms status` que cada módulo esperado (`gasket` para Coral, `nvidia` para el driver NVIDIA) haya alcanzado el estado `installed` para el nuevo kernel — si alguno no lo hizo, cae al camino `--auto-reinstall` de cada instalador.
- **Un whiptail msgbox anuncia la recompilación antes de ejecutarla.** Un solo botón OK — no hay yes/no. Nombra el kernel entrante y lista los componentes DKMS que se van a recompilar, de modo que el usuario ve exactamente qué está a punto de suceder. Dado que dejar los drivers DKMS sin recompilar dejaría el sistema con un kernel funcional pero TPU / GPU no operativos al arrancar, se trata de transparencia, no de decisión — al pulsar OK se reconoce el trabajo posterior y el flujo procede. Las invocaciones no interactivas (cron, batch sin terminal, sin whiptail) omiten el msgbox y registran la misma información.
- **Solo se consideran componentes registrados como `installed` en `components_status.json`.** Un host sin drivers DKMS gestionados por ProxMenux no ve msgbox ni paso de recompilación. Los hosts que nunca ejecutaron el instalador de Coral o NVIDIA no se ven afectados.
- **Si la recompilación falla, no se aborta la actualización.** Si un módulo DKMS no puede recompilarse contra el nuevo kernel (ruptura de API upstream, dependencia faltante), el flujo de actualización termina normalmente, se nombran los componentes concretos que fallaron en el resumen, y el usuario puede re-ejecutar su instalador a mano tras el reboot. El paso es best-effort por diseño — un desajuste kernel/driver es un problema upstream, no algo que el flujo de actualización deba tratar como fallo.
- El helper compartido `pmx_rebuild_dkms_after_kernel` vive en `scripts/global/utils-install-functions.sh`, de modo que futuros actualizadores o utilidades CLI pueden reutilizarlo con una única llamada.

---

## 🔌 Post-install — Nombres persistentes de NIC ahora idempotentes

- **Los ficheros `.link` gestionados por ProxMenux llevan ahora un prefijo distintivo y un marcador interno.** Se escriben como `10-proxmenux-<iface>.link` y la primera línea de cada fichero es `# Managed by ProxMenux — do not edit`. Ambos se comprueban en los pasos de reconciliación y desinstalación antes de tocar un fichero, de modo que cualquier cosa que el usuario haya escrito a mano o que venga de otro paquete queda a salvo.
- **Cada re-ejecución de `setup_persistent_network` reconcilia las entradas de ProxMenux.** En cada invocación se recorren los ficheros `10-proxmenux-*.link` existentes, se extrae el valor `MACAddress=`, se compara con las MAC actualmente presentes en `/sys/class/net/`, y se eliminan únicamente las entradas propiedad de ProxMenux cuya MAC ya no está. Reemplazos de tarjetas, cambios de NIC y migraciones de hardware dejan de acumular mapeos huérfanos en cada re-ejecución.
- **Los ficheros con formato 1.0 (`10-<iface>.link`, escritos por la versión anterior) se migran automáticamente en la primera ejecución de la nueva función.** Si el fichero coincide con la plantilla exacta que usaba el código 1.0 (dos secciones, `MACAddress=` + `Name=`, nada más), se elimina y se reemplaza por el `10-proxmenux-<iface>.link` en un solo paso. Cualquier fichero que no coincida con esa plantilla exacta se deja intacto.
- **El desinstalador (`uninstall_persistent_network`) elimina ahora solamente ficheros que cumplan a la vez el prefijo `10-proxmenux-` y el marcador en la primera línea.** El anterior barrido `rm -f /etc/systemd/network/*.link` desaparece — los `.link` escritos por el usuario permanecen en su sitio con independencia de su nombre.
- **Implementación única compartida.** Las tres copias de `setup_persistent_network` (`auto_post_install.sh`, `customizable_post_install.sh`, `network_menu.sh`) y el desinstalador delegan ahora en `pmx_setup_persistent_network` / `pmx_uninstall_persistent_network` en `scripts/global/utils-install-functions.sh`. Los futuros arreglos no pueden dejar una copia atrás.
- Se sube `FUNC_VERSION` de 1.0 → 1.1 en las tres llamadas, de modo que el detector de actualizaciones de ProxMenux vuelve a ejecutar la función en hosts que ya tenían la 1.0. Esa primera re-ejecución hace la migración legacy y la reconciliación en un solo paso.

---

## 🧮 Post-install — Optimización de ZFS ARC ajustada a su ámbito

- **`optimize_zfs_arc` establece ahora únicamente `zfs_arc_max`.** La función escribe una sola línea en `/etc/modprobe.d/99-zfsarc.conf`: `options zfs zfs_arc_max=<cap>`. `zfs_arc_min` queda en el valor por defecto de OpenZFS (auto-calculado como el mayor entre 32 MiB y ~1/32 de la RAM), y los tunables de L2ARC (`l2arc_noprefetch`, `l2arc_write_max`) y de TXG (`zfs_txg_timeout`) — que quedan fuera del ámbito de una optimización del ARC — se dejan en los valores por defecto de OpenZFS salvo que el usuario los configure explícitamente.
- **Se regenera ahora el initramfs tras escribir el fichero.** En sistemas con ZFS-on-root el módulo ZFS se carga desde el initramfs antes de que el sistema en marcha lea `/etc/modprobe.d/`, así que un simple reboot no bastaba para que el nuevo cap surtiera efecto. `update-initramfs -u -k all` se ejecuta justo después de escribir el fichero, más `proxmox-boot-tool refresh` en hosts con systemd-boot, de modo que el valor se aplica en el siguiente arranque en lugar de quedar sombreado por la copia obsoleta del initramfs.
- **La función se protege con la presencia de un pool ZFS vivo** (chequeo `zpool list`), de manera que se convierte en no-op en hosts que no usan ZFS.
- **Los valores del cap usan tamaños binarios limpios**: 512 MiB hasta 16 GB de RAM, 1 GiB hasta 32 GB, RAM/8 por encima — con un suelo de 512 MiB para que una lectura defectuosa de memoria no deje un ARC inutilizablemente pequeño.
- Se sube `FUNC_VERSION` de 1.0 → 1.1, de modo que el detector de actualizaciones de ProxMenux vuelve a ejecutar la función en hosts que ya tenían la 1.0. Como la escritura es una reescritura completa de `99-zfsarc.conf`, ejecutar la función actualizada una vez reemplaza el fichero entero limpiamente. El desinstalador ejecuta ahora también `update-initramfs` + `proxmox-boot-tool refresh` tras restaurar o eliminar la configuración, de modo que la reversión se propaga al initramfs de la misma manera.

---

## 🔥 Post-install — Ajuste de sysctl en los bridges del firewall reforzado

- **El ajuste de `rp_filter=0` y `log_martians=0` sobre las interfaces del firewall bridge (`fwbr*`, `fwln*`, `fwpr*`, `tap*`) se aplica ahora también a las interfaces que Proxmox crea al arrancar, parar, reiniciar o migrar una VM.** Se añade `/etc/udev/rules.d/99-proxmenux-fwbr-tune.rules`, que dispara un helper por cada evento `net`/`add` matcheando esos prefijos, de modo que cada interfaz nueva obtiene el valor correcto inmediatamente sin necesidad de reboot ni de reejecutar el post-install.
- **La lógica de ajuste se ha reorganizado en un helper independiente** en `/usr/local/sbin/proxmenux-fwbr-tune`, compartido por el barrido inicial (servicio `proxmenux-fwbr-tune.service`, tipo oneshot) y por la regla udev. Al instalar se hace además un barrido explícito para que la sesión actual vea el cambio sin esperar al siguiente ciclo de VM.
- **El flujo configurable (`customizable_post_install.sh`) incorpora ahora el mismo helper + servicio + regla udev + barrido inicial que el flujo automático**, para que ambos variantes de post-install dejen el sistema en el mismo estado.
- Ambas funciones `apply_network_optimizations` suben `FUNC_VERSION` de 1.0 → 1.1, de modo que el detector de actualizaciones de ProxMenux vuelve a ejecutar la función en hosts que ya tenían la 1.0. El desinstalador (`uninstall_network_optimization`) se amplía para borrar el nuevo helper y la regla udev, y recargar udev.

---

## 🧰 Post-install — Log2RAM + PBS

- **Rotación automática de los logs de la API de PBS cuando `proxmox-backup-server` corre como servicio en el host.** Ambos instaladores de Log2RAM (`install_log2ram_auto` y el configurable `configure_log2ram`) detectan PBS mediante `dpkg-query` y dejan `/etc/logrotate.d/proxmox-backup-api` con una regla de rotación por tamaño (20MB × 3 copias) más `/etc/cron.hourly/proxmox-backup-logrotate`. En un host PVE que además ejecuta PBS como servicio, `pvestatd` sondea el datastore local cada pocos segundos y cada sondeo escribe en `/var/log/proxmox-backup/api/access.log` y `auth.log` — el paquete upstream de PBS no incluye regla de logrotate para esos ficheros, y esta regla los mantiene acotados de modo que un `/var/log` respaldado por tmpfs permanece cómodamente dentro del presupuesto. En hosts sin PBS como servicio no se crea nada.
- **Script upstream `log2ram` parcheado a `rsync -aXv --no-acls` justo después de `install.sh`.** Ambos instaladores reescriben la llamada en el sitio con un `sed` guardado por `grep -q` (deja backup en `.proxmenux.bak`, no-op si una futura release upstream ya no incluye `-A`). Los atributos extendidos (`-X`) se preservan. Resultado: `log2ram write` finaliza limpio en sistemas de ficheros de `/var/log.hdd` que no aceptan ACLs POSIX (ZFS con `acltype=off`, ext4 montado sin la opción `acl`) — sin mensajes de `set_acl: Operation not supported` / salida 23.
- **El bloque de emergencia de `log2ram-check.sh` rota los logs de PBS antes de truncar.** Cuando `/var/log` cruza el umbral del 92%, el script de auto-sync ejecuta ahora `logrotate -f /etc/logrotate.d/proxmox-backup-api` (solo si el fichero de regla existe) *antes* de truncar `pveproxy/access.log`, `pveproxy/error.log` y `pveam.log`. El historial reciente de accesos/autenticación de PBS se conserva en los `.gz` rotados en lugar de perderse. Se subió `FUNC_VERSION` de 1.2 → 1.3 en `install_log2ram_auto` y `configure_log2ram`, y el comentario de cabecera del `log2ram-check.sh` embebido de v1.2 → v1.3.

## 🗄 Restauración de backup — snapshot de pmxcfs + pools ZFS de datos

- **`/var/lib/pve-cluster/config.db` se captura ahora con `sqlite3 .backup`.** pmxcfs (`/etc/pve`) es servido por `pve-cluster` desde ese almacén SQLite, así que un rsync directo del fichero raw con el servicio en marcha puede pillarlo a mitad de checkpoint WAL y aterrizar en el archivo como una copia inconsistente. `hb_prepare_staging` ejecuta ahora `sqlite3 /var/lib/pve-cluster/config.db ".backup '$staging/…/config.db'"` antes del rsync general — la vía canónica (documentada por Proxmox) para snapshotear el almacén de forma consistente mientras `pve-cluster` sigue sirviendo tráfico, con downtime cero para el cluster. El rsync general de `/var/lib/pve-cluster` excluye ahora `config.db`, `config.db-wal` y `config.db-shm` para que nada sobrescriba el dump consistente. Los hosts sin `sqlite3` recurren a una copia raw llamada `config.db.raw-fallback`, que el helper de recuperación promociona a `config.db` antes de arrancar `pve-cluster`. Los metadatos registran qué vía se usó vía `pmxcfs_config_db=sqlite_backup|raw_fallback` en `metadata/run_info.env` para trazabilidad. La ruta de restauración sigue usando el patrón canónico `systemctl stop pve-cluster → cp → systemctl start pve-cluster` (`apply_pending_restore.sh` y el helper de recuperación standalone que se escribe junto a cada directorio de cluster extraído), así que la DB que el usuario trae de vuelta es ahora consistente garantizada en lugar de una copia raw de estado en vuelo.

- **Los pools ZFS de datos listados en el backup ahora se importan automáticamente durante la restauración.** El nuevo paso `_rs_import_data_pools` corre tras el apply de configs, recorre `storage_inventory.zfs_pools[]`, excluye el pool raíz (ya montado por el sistema) y lanza `zpool import <nombre>` para cada pool no-raíz cuyos discos estén todos presentes en este host. Cuando ZFS rechaza el import por *foreign* — el caso típico tras una instalación fresh que regraba la etiqueta on-disk con un `hostid` nuevo — el paso reintenta con `-f` y reporta el pool como forzado para dejar trazabilidad. Los pools a los que les falta algún disco se omiten con un aviso claro en lugar de importarse en modo degradado. Todo esto cierra el caso habitual en el que `zfs-import-scan.service` fallaba al boot tras una instalación fresh y dejaba el pool de datos separado indisponible hasta ejecutar `zpool import -f` a mano.
- **El resultado del auto-import persiste en la tarjeta post-restauración.** El paso escribe una sección `data_pools_import` en `/var/lib/proxmenux/restore-state.json` (el mismo JSON que la tarjeta de la pestaña Backups consulta) y un log crudo en `/var/log/proxmenux/restore-datapools-<timestamp>.log`. La tarjeta muestra dentro de Detalles un bloque dedicado con cinco filas coloreadas (Importados / Forzados / Omitidos parcial / Omitidos ausentes / Fallidos), así que el resumen queda consultable después de cerrar el terminal de restauración, y la entrada se preserva en el historial del run para consulta posterior.
- **Pools ZFS creados con `by-partuuid` o `/dev/sdX` en bruto reconocidos por el chequeo de presencia de discos.** El paso de auto-import y `validate_storage.sh` tratan como absolutas las entradas de `devices_by_id` que empiezan por `/` y solo prependen `/dev/disk/by-id/` a los basenames desnudos, de modo que los pools construidos contra partition UUIDs o dispositivos de bloque en bruto se detectan como presentes cuando sus discos están en el host.
- **`/etc/systemd/network` añadido a las rutas de backup por defecto.** Ese directorio contiene los ficheros `.link` de systemd que fijan los nombres de las NICs a su MAC a través de actualizaciones de kernel y reinstalaciones — el `setup_persistent_network` del post_install los escribe para cada interfaz física, y los usuarios pueden dejar los suyos también para renombrar una NIC a algo significativo. Preservarlos a través de una restauración sobre instalación fresh mantiene intacta en el destino la política de nombres de NIC del host origen, de modo que las entradas de `/etc/network/interfaces` que referencian nombres custom siguen resolviendo tras la restauración.

---

## 🙏 Agradecimientos

- **@pepenai** — dashboard en móvil sobre HTTPS + reverse proxy.
- **Pepo** — autenticación de webhook desde FQDN Tailscale.
- **@ash34** (#255) — chequeo VM/CT con la columna `details` a NULL.
- **@f3rs3n** (#256, #257, #258) — ajuste de sysctl en bridges del firewall, ámbito de la optimización de ZFS ARC y reconciliación de nombres persistentes de NIC.
- **Juan C.** — auto-import de pools ZFS de datos tras instalación fresh.
- **David Barbero (@sikete)** — recompilación de drivers DKMS al actualizar el kernel.


## 2026-07-14

### Nueva versión ProxMenux v1.2.3


![ProxMenux Backups](https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/ProxMenux_backup.png)

Consolidación estable del **ciclo beta v1.2.2.x** (v1.2.2.1 → v1.2.2.2 → v1.2.2.3). La novedad principal es una nueva sección **Backups** con un flujo para crear / programar / restaurar contra Local, PBS y Borg, una tarjeta de progreso en tiempo real de post-restore, un diálogo de cifrado PBS, y una restauración *direction-aware* que gestiona los saltos entre kernels. Alrededor de eso: una nueva vista de topología Network Flow, tarjetas rediseñadas en Overview / VM & LXC / Storage / Network, notificaciones con informcacion más ricas  sin necesidad de IA, un panel Health Monitor Thresholds actualizado, y una re-verificación completa del catálogo de modelos IA en los cinco providers soportados.

---

## 🗄️ Backups integrados en el Monitor

- **Crear / programar / restaurar** copias del host contra destinos **Local**, **Proxmox Backup Server** y **Borg** desde el dashboard.
- **Dos modos de programación**: timer systemd propio, o *attached* a un job vzdump PVE existente (recomendado) con retención heredada de la tarea de copia en cada ejecución.
- **Cifrado PBS con blob de recuperación**: los backups cifrados almacenan una copia de la keyfile envuelta con passphrase como grupo `-keyrecovery` junto a cada backup, para que una instalación instalacion nueva de proxmox siempre pueda recuperar la clave con la passphrase del usuario.
- **Restauración direction-aware**: reaplica ajustes IOMMU / VFIO / GRUB en saltos entre kernels, protege paquetes críticos del cascade-remove, re-mapea NICs automáticamente tras un cambio de placa base.
- **Tarjeta de progreso post-restore en vivo**: tras el reboot, la pestaña Backups muestra una tarjeta en tiempo real con hitos paso a paso, estado por componente (NVIDIA, Intel GPU tools, Coral, AMD tools) y un log tail con filtro "Issues only". Las restauraciones pasadas quedan archivadas y navegables.
- **Gestión de la keyfile PBS inline en el Monitor**: cada fila de destino PBS expone Descargar / Subir / Eliminar para la keyfile, más un toggle Sí/No + passphrase + botón Apply contextual para el escrow. Cuando la keyfile instalada no coincide con el manifest del backup, View contents / Download / Restore ahora muestran un panel ámbar estructurado con el fingerprint requerido, para saber qué keyfile importar.

---

## 🌐 Diagrama Network Flow

- Nueva vista de topología en vivo en la pestaña **Network**: NICs → host → bridges → LXCs / VMs.
- Pulsos rx / tx animados en cada enlace interno — respuesta inmediata a *"¿qué guest está tirando o empujando ahora mismo?"* sin cruzar varios paneles.
- Layout en árbol diseñado para leerse limpio en dispositivos móviles.

---

## 🎨 Tarjetas rediseñadas en Overview / VM & LXC / Storage / Network

- Layouts rediseñados para lectura más rápida y con información más densa y práctica.
- Números clave a la vista de un vistazo, agrupados por relevancia.
- Grid responsive que se comporta limpio desde móvil hasta ultrawide.
- Las tarjetas de **Physical Disks** y **Physical Interfaces** en Storage y Network son el cambio visual más grande — presentación por-item más clara.

---

## 🔔 Notificaciones más ricas out of the box

Para quienes **no** usan un agente de enriquecimiento con IA, el cuerpo de las plantilas ahora añade contenido más útil:

- Los títulos nombran el objeto afectado (`Storage 'PBS' unavailable` en vez de `1 Proxmox storage(s) unavailable`, `Network connectivity lost — vmbr0`, `3 health checks degraded — Storage (myPBS), Network (vmbr0), CPU`).
- Las listas largas muestran los top offenders con una coleta `…and N more` para no perder nada en silencio.
- Las notificaciones de recovery preservan la misma identidad usada en la alerta.
- Los usuarios con enrichment IA siguen recibiendo su reescritura personalizada encima de esta base mejorada.

---

## 🩺 Panel Health Monitor Thresholds rediseñado

- El panel **Settings → Health Monitor Thresholds** que controla los niveles Warning y Critical por categoría (CPU, memoria, temperatura, storage, disks, …) se ha rediseñado con agrupación visual más clara e hints inline.
- Ajustar un threshold ahora es un par de clicks en vez de scrollear por un muro de números.

---

## 🛠 Fixes destacados

- **SMART en enclosures USB-NVMe / USB-SATA que reportan `removable=0`** — los enclosures que reportan `removable=0` (ASMedia, JMicron, Realtek, ASM105x) ahora hacen walk de sysfs para detectar attachment USB, así se prueba el pass-through `-d snt*` y aparecen el modelo real del drive, serial, temperatura, power-on hours y health. El sampler del histórico de temperatura hereda el mismo fix.
- **Prompt de cifrado PBS reworked** a una única pregunta explícita *Encrypt this backup?* Sí/No — nada se sube a PBS a menos que la respuesta sea Sí. Solo cuando no hay keyfile instalada aparece un segundo diálogo que pregunta si generar una nueva o importar una existente. Cancelar nunca deja una keyfile fantasma detrás.
- **Los backups attached programados ahora heredan retención en cada ejecución** — los jobs attached a un padre vzdump PVE releen la config `prune-backups` del padre en cada run y reescriben `KEEP_*` según corresponda. Antes quedaba congelado al valor del momento de creación del job.
- **El installer ya no auto-relanza `menu` tras un update** — el `exec MENU_SCRIPT` al final del update path disparaba errores visibles *"line: syntax"* cuando bash intentaba leer el `/usr/local/bin/menu` recién reescrito por debajo. El flujo ahora sale limpio; el usuario teclea `menu` cuando esté listo. `change_release_channel` en Settings no se ve afectado.
- **PBS restore listing roto en Proxmox 9 / jq 1.7** — `hb_pbs_list_snapshots` cambió de la forma prefix `and not (...)` (jq 1.7 la rechaza) a la postfix `and ((...) | not)` (ambos jq 1.6 y 1.7 la aceptan). También se quitó un `2>/dev/null` que enmascaraba el error de parseo.
- **`run_scheduled_backup.sh` ya no crashea cuando `LANGUAGE` está unset** — las invocaciones cron / systemd ahora cargan el idioma + inicializan el cache de traducción antes de hacer source a las funciones que lo requieren.
- **Los prompts de restore de archive local ya no se congelan en silencio** — `hb_prompt_restore_source_dir` y `hb_prompt_local_archive` usan el TTY handoff fd-9 ya aplicado en otros sitios.
- **El modal de terminal auto-focusea xterm** para que `dialog --yesno` dentro de scripts CLI reciba las flechas en lugar del botón Close.
- **NVIDIA VFIO passthrough escribe `vfio_passthrough` de vuelta en `components_status.json`** — `switch_gpu_mode.sh`, `switch_gpu_mode_direct.sh` y `add_gpu_vm.sh` actualizan el status del componente al cambiar el estado del driver. El auto-reinstall post-restore ya no pisa NVIDIA en hosts dejados intencionadamente en modo VFIO.
- **Las notificaciones de update de Secure Gateway ya no arrastran un `— v` colgando** — cuando solo hay paquetes sidecar que actualizar (Tailscale mismo sin cambio), el título dice `secure-gateway update available — v<current> (packages only)` y el body muestra una única línea "Tailscale: v… (unchanged — only sidecar packages need updating)" en vez de la confusa flecha `v → v`.
- **Auto-migración de modelos IA deprecados** — usuarios con `claude-3-5-haiku-latest`, `claude-3-5-sonnet-latest` o `claude-3-opus-latest` (todos 404 upstream ahora) se migran en silencio a la recomendación actual (`claude-haiku-4-5`, etc.) dentro de las 24 h del upgrade, con una notificación `ai_model_migrated` explicando qué pasó.
- **NVIDIA installer ya no bloqueado a la branch recomendada** (#248) — `filter_option_c_branch` requería un match EXACTO de major branch contra la recomendada por kernel, así que los usuarios de kernel 7.0.14 solo veían drivers 580.x aunque builds concretos de 580.x fallaran al compilar contra el toolchain nuevo de PVE 9.1. El filtro ahora acepta branch ≥ recomendada, así que branches estables más nuevas (590 / 595 / 600) son seleccionables in-menu cuando compilan. `MIN_DRIVER_VERSION` sigue vigilando el suelo.
- **Minor variado** — la URL del webhook PVE sigue el estado SSL activo; las disk observations se registran antes del gate SMART; la pantalla de Login ya no se traga un 401 para siempre tras un stale-token breve; los toggles visibles en tema claro.

---

## 🤖 Refresh de providers IA

`AppImage/config/verified_ai_models.json` refrescado con verificación funcional contra los cinco providers soportados (`_updated: 2026-07-14`):

| Provider    | Eliminados (deprecados / 404)                                                                 | Añadidos / mantenidos                                                                                              | Recomendado                       |
|-------------|-----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|-----------------------------------|
| groq        | `llama-3.1-70b-versatile`, `llama3-70b/8b-8192`, `mixtral-8x7b`, `gemma2-9b-it`                | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `llama-4-scout`, `openai/gpt-oss-20b`, `openai/gpt-oss-120b`    | `llama-3.3-70b-versatile`         |
| gemini      | `gemini-2.0-flash*`, `gemini-1.5-flash`, `gemini-1.0-pro`                                     | `gemini-flash-lite-latest`, `gemini-2.5-flash-lite/flash`, `gemini-3-flash-preview`, `gemini-3.1/3.5-flash-lite/flash` | `gemini-2.5-flash-lite`           |
| openai      | `gpt-5.4-nano`, `gpt-5.4-mini` (HTTP 400)                                                     | `gpt-4.1-nano/mini`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4o`, `gpt-5-chat-latest`, `gpt-5-nano`                          | `gpt-4.1-nano`                    |
| anthropic   | `claude-3-5-haiku-latest`, `claude-3-5-sonnet-latest`, `claude-3-opus-latest` (404 upstream)  | `claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-fable-5` | `claude-haiku-4-5`                |
| openrouter  | `claude-3.5-*`, `gemini-flash-1.5`, `mistral-7b`, `mixtral-8x7b`                              | `llama-4-scout`, `claude-haiku-4.5`, `claude-sonnet-4.6`, `gemini-2.5-flash/lite`, `mistral-small-3.2-24b`         | `meta-llama/llama-3.3-70b-instruct` |

Auto-migración incluida: `PollingCollector._check_ai_model_availability()` se ejecuta cada 24 h y mueve a los usuarios cuyo modelo configurado haya sido retirado a la recomendación reemplazo, con una notificación `ai_model_migrated` explicando qué pasó.

---

## 🙏 Acknowledgments

Agradecimiento especial a los miembros de la comunidad que dieron forma a esta release con diseños concretos, reports de campo y pruebas:

- **[@JF_Car](https://github.com/JF_Car)** — propuso el layout en árbol del nuevo diagrama Network Flow para que se lea correctamente en dispositivos móviles.
- **[@ghosthvj](https://github.com/ghosthvj)** — contribuyó el diseño de las nuevas tarjetas de **Physical Disks** y **Physical Interfaces**.
- **[@riglesias](https://github.com/riglesias)**, **[@princo56](https://github.com/princo56)** y **[@jonatanc](https://github.com/jonatanc)** — probaron el ciclo beta end-to-end y aportaron las sugerencias que cerraron la mayoría de los gaps visibles para el usuario.

Y a cada usuario que abrió una issue, comentó en [GitHub Discussions](https://github.com/MacRimi/ProxMenux/discussions), reportó un bug por el canal comunitario, o simplemente pasó a decir qué funcionaba y qué no en su hardware — la mayor parte de los fixes internos de esta release empezaron como uno de esos reports. Que sigan viniendo.

---

## 2026-06-02

### Nueva versión ProxMenux v1.2.2 — *Consolidación estable del ciclo v1.2.1.x*

Release estable que lleva al canal principal las cuatro prereleases del ciclo **v1.2.1.x** en un solo movimiento. El trabajo a lo largo de esas cuatro betas se centró en tres temas: hacer del Health Monitor algo realmente configurable en lugar de solo observable (thresholds por categoría, duraciones de dismiss por evento, un audit log de supresiones activas), expandir el stack de notificaciones para cubrir alrededor de 80 servicios a través de Apprise mientras se persisten eventos durante las Quiet Hours, y convertir el propio proceso del Monitor en un ciudadano del sistema más silencioso y predecible en hosts idle. Por encima de eso, esta release entrega detección automática de updates en contenedores LXC, una reescritura end-to-end del instalador de Coral TPU con los últimos drivers upstream, y una larga lista de fixes visibles para el usuario — handshake del terminal HTTPS, detección de kernel updates en PVE 9.x, flujo del instalador NVIDIA en Alpine LXC, gestión del audio acompañante en passthrough de GPU mixta, y varias optimizaciones runtime en los bucles de scan del Monitor. Cinco contribuciones de código directas de la comunidad shipean junto con esta release ([@jcastro](https://github.com/jcastro) ×5, [@pespinel](https://github.com/pespinel) ×1) y el trabajo de GPU passthrough lo impulsaron los reports detallados de campo de [@ghosthvj](https://github.com/ghosthvj) — ver los Acknowledgments al final.

---

## 🩺 Health Monitor — Configurable, granular, auditable

Tres piezas acopladas que juntas permiten al usuario ajustar el Health Monitor a la envoltura real de su host en lugar de trabajar alrededor de sus defaults, y gestionar dismisses con el mismo control fino que ya tienen sobre el resto del dashboard.

### Thresholds Warning / Critical por categoría

Cada check que corre el Health Monitor está parametrizado por un par de números — un *Warning* y un *Critical* — y ambos están ahora expuestos bajo **Settings → Health Monitor Thresholds**. Los defaults que shipean con ProxMenux son razonables para el host Proxmox medio, pero cada entorno tiene su propia envoltura:

- Un homelab pequeño con un único SSD quiere paginar antes en capacidad (75 / 90 %) para dejar margen a snapshots.
- Un nodo de datacenter con almacenamiento Ceph redundante puede ser mucho más relajado con los warnings de memoria (un working set del 90 % es normal con ZFS ARC).
- Un mini-PC refrigerado pasivamente necesita thresholds de temperatura más bajos que un servidor con refrigeración forzada — misma clase de disco, distinta envoltura física.

Los cambios surten efecto en el siguiente scan — el Health Monitor relee los valores desde `/usr/local/share/proxmenux/health_thresholds.json` en cada ciclo, sin restart del servicio. Los mismos números también alimentan los rangos de color de cada widget del dashboard (barras de almacenamiento, anillos de CPU/memoria, chips de temperatura, el punto del modal de disco), de forma que la clasificación visual en cualquier punto del Monitor mapea a un rango definido respecto al par configurado.

### Duración de dismiss por evento con badge Permanent

El botón *Dismiss* en cada alerta del Health Monitor abre ahora un pequeño dropdown con tres opciones:

- **24 hours** — default anterior, se comporta exactamente como antes
- **7 days** — útil para una condición temporal de la que no quieres oír durante una migración de una semana
- **Permanently** — silencia este `error_key` concreto indefinidamente

Los dismisses permanentes se persisten con `suppression_hours = -1` en la base de datos de persistencia, nunca re-emiten, nunca re-notifican y se marcan con un badge ámbar **Permanent** distinto en el Health Monitor para que el usuario siempre sepa qué alertas están silenciadas intencionadamente. La infraestructura backend para el centinela permanente ya existía — solo le faltaba a la UI una forma de fijarlo. El contrato de API es pequeño y backwards-compatible: `POST /api/health/acknowledge` acepta un campo body opcional `suppression_hours` (entero positivo para horas, `-1` para permanente); omitirlo preserva el comportamiento previo y usa la supresión configurada de la categoría. Un segundo endpoint nuevo `POST /api/health/un-acknowledge {error_key}` limpia un acknowledgment previamente registrado para que la alerta vuelva a ser elegible para dispararse — usado por el panel Active Suppressions abajo.

### Panel Active Suppressions en Settings

Una nueva sección dentro de **Settings → Health Monitor**, justo debajo de las duraciones de supresión por categoría, lista cada alerta actualmente silenciada — tanto los dismisses con tiempo limitado (con un badge *22h remaining* / *6d remaining*) como los permanentes (con el badge ámbar *Permanent* del dashboard). Cada fila lleva el `error_key`, la categoría, la severidad, el timestamp en que se registró el dismiss, y un botón **Re-enable** que limpia el acknowledgment server-side. Los re-enables están **encolados** — pulsar el botón marca la fila en verde con texto tachado y cambia el botón a *Undo*, y el `POST /api/health/un-acknowledge` real solo se dispara cuando el usuario pulsa **Save**, de modo que un lote de re-enables se entrega atómicamente junto a cualquier cambio pendiente de dropdown por categoría. La acción está protegida por el toggle de *Edit* del Health Monitor en la parte superior de la card. Los dismisses permanentes **solo pueden revertirse desde aquí** — el dashboard no expone intencionadamente un affordance per-alerta de un-dismiss para evitar re-enables accidentales, por lo que el panel de Settings es la superficie deliberada de auditoría + revert para ellos. La lista también se refresca automáticamente cuando se hace un dismiss de una alerta desde el modal del Health Monitor mientras la página de Settings ya está abierta, vía un evento `health-suppression-changed` del navegador más listeners en `window focus` y `document visibilitychange`.

### Tiers de severidad de Disk I/O

Una ventana deslizante de 24 h clasifica ahora los errores ATA / SCSI de dmesg en tres buckets: silencioso (0–10 eventos transitorios), WARNING (11–100) y CRITICAL (100+, o cualquier error duro como UNC / Buffer I/O / Sense Key Hardware Error). Los días tranquilos se quedan tranquilos, pero un único evento de Buffer I/O sigue paginando inmediatamente.

---

## 📨 Canal de notificación Apprise — Paridad completa de features

La integración Apprise que aterrizó como un adapter básico en 1.2.1.4-beta se ha graduado a paridad completa con los canales nativos. Una sola URL de Apprise llega ahora a alrededor de 80 servicios de notificación (Pushover, ntfy, Slack, Matrix, mailto, signal, Pushbullet, Mattermost, Microsoft Teams vía webhooks, …) sin que ProxMenux necesite un adapter dedicado para cada uno. La pestaña Apprise en Notifications expone los mismos controles que Telegram, Gotify, Discord y Email:

- El bloque **Notification Categories** completo — las mismas 10 categorías con sus sub-toggles por evento, idéntico a los otros canales
- **Quiet Hours** — ventana start/end por canal, con el mismo comportamiento de buffering (los eventos disparados durante la ventana se persisten en SQLite y se liberan como un resumen agrupado cuando la ventana cierra, en lugar de dropearse silenciosamente)
- **Daily Digest** — entrega opt-in de un resumen una vez al día a una hora elegida

El filtrado per-channel del backend ya aplicaba genéricamente a cada canal incluyendo Apprise vía el bloque `channel_overrides` — la UI simplemente no estaba surfaceando los controles.

Tres fixes de fiabilidad shipean junto, todos surfaceados después del rollout beta inicial:

1. **Mobile overflow** en viewports estrechos. La fila de Apprise URL solía romper el diseño — el placeholder empaquetaba cuatro URLs de ejemplo completas en una línea y los `<code>` inline de los ejemplos no tenían regla `break-all`. El placeholder es ahora un único ejemplo conciso (`tgram://bottoken/ChatID`), el wrapper del input URL fuerza `min-w-0 / flex-1 / shrink-0` en sus children, y el párrafo de ejemplos usa `break-all min-w-0` para que envuelva limpiamente a cualquier ancho.

2. **Regresión del whitelist backend** que rechazaba Apprise con HTTP 400. El conjunto de canales hardcodeado del validador de notifications-test (`{telegram, gotify, discord, email, all}`) tenía a `apprise` ausente, por lo que cada test o send de Apprise devolvía `400 Invalid channel` antes de que la librería fuera siquiera invocada. El whitelist se deriva ahora en vivo desde `notification_channels.CHANNEL_TYPES`, de forma que añadir una nueva implementación de canal en el futuro no puede regresionar silenciosamente este validador otra vez.

3. **Error reporting opaco** cuando el destino devolvía una respuesta no-2xx. Cuando un destino (`jsons://`, `ntfy://`, `slack://`, …) rechazaba el payload, el usuario solo veía un mensaje genérico *"Apprise rejected the notification (transport failure)"*. El canal captura ahora el logger interno de Apprise durante `notify()` y surfacea el HTTP status code real más el response body del destino (capado a 300 caracteres) — de forma que un beta tester debuggeando un webhook custom puede ver inmediatamente si el servidor upstream está rechazando su schema de payload.

---

## 📦 Detección de updates en LXC

Una nueva sección dedicada en **Settings** (entre *Health Monitor Thresholds* y *Notifications*) con un único toggle que protege el scan per-CT de `apt list --upgradable` / `apk list -u` end-to-end. Default ON. Cuando está OFF el scan para completamente (sin llamadas `pct exec`), cada entrada `type=lxc` se purga inmediatamente del registry de managed-installs, y el toggle de notificación correspondiente en *Notifications → Services* desaparece de la UI mientras preserva su preferencia almacenada.

El checker lee también el `mtime` de la caché de metadata del package-manager de cada CT y dispara `apt-get update` / `apk update` desde fuera vía `pct exec` si tiene más de 24 h, con timeout de 60 s y fallo silencioso. Los CTs appliance long-running cuyas cachés estaban meses obsoletas surfacean por fin su backlog real upstream — un CT Debian 12 con caché de 524 días pasó de "0 updates" a "117 (12 security)" en hardware de lab.

---

## 🐧 Coral TPU en LXC — Últimos drivers upstream

El instalador de Coral para LXC (`scripts/gpu_tpu/install_coral_lxc.sh`) se ha reescrito end-to-end para instalar el **último driver `gasket-dkms` upstream** y el **último runtime `libedgetpu1`** (220 líneas añadidas, 150 eliminadas). Los módulos Coral M.2 / mPCIe que antes fallaban al compilar en kernels PVE 9 ahora instalan y bindean limpiamente. Las notificaciones de update registry-driven que aterrizaron en 1.2.1.2 mantienen ambos paquetes frescos en adelante: la pestaña Hardware + Notifications señalizan cuando feranick/gasket-driver publica una release nueva, y el runtime `libedgetpu1` tracked vía `apt` recibe el flujo estándar de System Updates.

El **path de uninstall del instalador Coral** acompañante también aterriza en este ciclo — espejando el flujo NVIDIA para que una instalación Coral pueda revertirse limpiamente si el usuario re-despliega el host sin aceleración TPU.

---

## ⚡ Optimizaciones de rendimiento del Monitor

Una corrida de strace + sampling de 10 minutos sobre un host live surfaceó tres sitios donde el scanner de background del Monitor estaba spawning subprocesos más agresivamente de lo necesario. Los tres están arreglados en 1.2.2:

### Tormenta de subprocesos fail2ban
En hosts donde `fail2ban-client` no estaba instalado, el wrapper de caché alrededor de `_f2b_get_banned_ips()` solo actualizaba su timestamp en éxito. Cada request HTTP al dashboard caía a través del check de caché y disparaba un `execve("fail2ban-client", ...)` fresco que inmediatamente fallaba con `ENOENT` — 250+ llamadas `execve` fallidas en una ventana de 10 minutos. `shutil.which('fail2ban-client')` se resuelve ahora **una vez** al cargar el módulo y el timestamp de caché se actualiza incondicionalmente. Los hosts sin Fail2Ban tienen ahora cero syscalls de `fail2ban-client` por request.

### Colisión del scheduler de smartctl
El polling de temperatura SMART de discos, la lectura de temperatura CPU y la probe de latency solían dispararse en el mismo offset dentro de cada minuto, produciendo un spike medible de CPU / IO cuando todos sus subprocesos spawneaban juntos. Las polls están ahora staggered (latency primero, luego temperatura CPU, luego SMART de disco) preservando la cadencia per-disco de 60 s — el spike ha desaparecido, el CPU total bajo carga no cambia.

### Subproceso de inventario LXC
El mount monitor solía llamar `lxc-info -n <vmid> -p` por cada CT corriendo solo para obtener su PID init. Ahora lee `/proc/<lxc-start-pid>/task/<lxc-start-pid>/children` directamente y solo cae a `lxc-info` cuando la lectura de `/proc` falla. Un subproceso por CT por ciclo de scan eliminado — medible en hosts con 20+ contenedores.

---

## 🔌 Handshake del terminal HTTPS

Cada modal de terminal en el Monitor (terminal del dashboard, terminal LXC, terminal de scripts) solía fallar con *WebSocket connection error* en hosts donde HTTPS estaba habilitado. La root cause era específica al path `gevent + SSL`: el `WebSocketHandler` de gevent-websocket estaba apilado sobre la implementación de protocolo de flask-sock, por lo que el servidor emitía **dos** cabeceras `HTTP/1.1 101 Switching Protocols` consecutivas y el navegador cerraba la conexión como un frame corrupto. Quitar el argumento explícito `handler_class=WebSocketHandler` restaura una única respuesta 101 y el handshake completa con normalidad. El fix es invisible para usuarios corriendo en HTTP plano — no estaban afectados — pero desbloquea cada install fronteada por HTTPS (reverse proxies, deployments con certificate-managed, cualquier cosa detrás de nginx/Traefik).

Adicionalmente, el panel de terminal solía perder su conexión WebSocket cuando el usuario activaba la feature de auto-traducción del navegador (los prompts "translate this page" de Chrome / Edge / Safari). El traductor mueve nodos del DOM que React aún mantiene como refs, y el componente WebSocket React se rompe porque su ref de contenedor apunta a un nodo movido. Añadido `translate="no"` en los divs contenedores del terminal para que el traductor salte el tty embebido por completo — las traducciones en el resto de la página siguen funcionando.

---

## 🐧 Health Monitor — Detección de kernel updates en PVE 9.x (#208)

En hosts Proxmox VE 9.x, la fila *System Updates → Kernel / PVE* reportaba "Kernel/PVE up to date" incluso cuando un update para el kernel corriendo estaba esperando upstream. Tres causas combinadas, tres fixes combinados:

1. **La lista de prefijos de kernel-packages** incluye ahora `proxmox-kernel-*` y `proxmox-firmware-*` — PVE 9.x shipea kernels bajo `proxmox-kernel-`, no el prefijo `pve-kernel-` de 7.x / 8.x. El regex anterior nunca matcheaba los paquetes nuevos y por tanto nunca flagueaba ningún update de kernel en 9.x.

2. **El dry-run cambió de `apt-get upgrade --dry-run` a `apt-get dist-upgrade --dry-run`**. PVE 9 shipea kernel updates empaquetados como instalaciones nuevas (no como upgrades directas de un paquete existente), y el `upgrade --dry-run` plano no considera nuevas instalaciones en absoluto. `dist-upgrade --dry-run` sí.

3. **La detección del kernel corriendo** lee ahora `uname -r` y flaguea un update como *running-kernel update* cuando el paquete matchea la release corriendo exactamente o su meta-package de branch (p. ej. `proxmox-kernel-6.14` para un host en `6.14.11-4-pve`). El texto de la fila distingue *"Running kernel update available (reboot required)"* de *"N kernel update(s) available (none for running kernel)"* para que el usuario sepa si necesita reboot o solo instalar.

---

## 🟢 Instalador NVIDIA

Varias mejoras impulsadas por los reports detallados de campo de [@ghosthvj](https://github.com/ghosthvj) sobre configuraciones de GPU mixta (ver Acknowledgments):

- **Ventana de compatibilidad de kernel** — el menú de versiones respeta ahora el rango de drivers compatibles del kernel corriendo, ofreciendo solo branches que no fallarán al compilar contra el kernel del host.
- **Soporte Alpine LXC** — el install de userspace container-side se reescribió para que succeda en hosts Alpine; la detección de espacio libre funciona fiablemente en todos los layouts de almacenamiento (LVM-thin, ZFS, directory, etc).
- **NVENC patch awareness** — cuando el host tiene el patch NVENC aplicado, el menú de versiones se estrecha a drivers soportados por el patch para que reinstalar nunca lo pierda silenciosamente.
- **Feedback de uninstall** — el path de uninstall reporta ahora un mensaje claro de completación en lugar de volver al menú en silencio.

---

## 🌐 Sitio de documentación — Migración i18n completa

El sitio de documentación acompañante (proxmenux.com) shipea ahora bajo URLs prefijadas por locale (`/en/...` y `/es/...`) con la plumbing de next-intl. Cada doc page es bilingüe — 107 páginas traducidas al español (sin placeholders copy-of-English). El root `/` redirige a `/en/` vía meta-refresh + JS para que la URL apex siga resolviendo a algo útil. Los RSS feeds funcionan per-locale en `/en/rss.xml` y `/es/rss.xml`, con el canonical `/rss.xml` conservado para backwards compatibility con suscriptores de feed existentes. La búsqueda client-side está wireada vía **Pagefind** — el índice se construye fresh en cada deploy de CI desde el HTML output final y se descarga fragmentariamente por el cliente, así que la búsqueda funciona sin un servidor backend.

Nuevas páginas de documentación cubren la sección **Active Suppressions** en la pestaña Settings y el **dropdown Dismiss por evento** en el modal del Health Monitor, ambas con capturas reflejando la nueva UI.

---

## 🔧 Otras mejoras

- **Sección AI Enhancement en Notifications** — reescrita de una fila uppercase atenuada que los testers consistentemente scrolleaban sin ver, a un label foreground normal-case con un icono `Sparkles` líder y un badge persistente (verde *Active* cuando IA está habilitada, neutro *Optional* cuando no lo está) para que la feature sea descubrible independientemente del estado.
- **Monitorización de temperatura de discos** — readings mejorados, caching más inteligente entre probes SMART, y un modal de historia rediseñado que abre a 24 h por defecto con estadísticas min / avg / max.
- **Detección de updates de funciones post-install** — el Monitor trackea optimizaciones ProxMenux instaladas (Log2Ram, Memory Settings, System Limits, Logrotate, …) y notifica cuando hay una versión más nueva disponible, con apply one-click desde Settings.
- **Flujo de update de Secure Gateway (Tailscale)** — update one-click de Tailscale desde Settings con indicadores Last-checked / Installed / Latest y notificación cuando se publica una nueva versión.
- **Menú Helper-Scripts** — context más rico e información útil para cada entrada, haciendo más fácil saber qué hace cada script antes de ejecutarlo.
- **Wording de agregación burst** — los resúmenes burst reportan ahora solo los eventos *adicionales* que llegaron después de la alerta individual inicial, de forma que el usuario ya no ve el primer evento contado dos veces.
- **Clasificador de errores conocidos** — regex con word-boundary en patrones ATA / UNC para que mensajes de kernel como `nvidia_uvm:FatalError` ya no se clasifiquen mal como problemas de cable ATA.
- **Errores de control de VM / CT** — start / stop / restart fallido surfacea ahora el stderr real de `pvesh` (p. ej. *"no space left on device"*) en el toast de la UI y dispara una notificación `vm_fail` / `ct_fail`, en lugar del bare 500 INTERNAL SERVER ERROR que el usuario solía ver.
- **Path de apply de log2ram** — el flujo auto / update reinicia ahora log2ram después de escribir el nuevo size, de forma que un `512M` configurado realmente surte efecto en el tmpfs corriendo sin restart manual.
- **PVE webhook URL** — el webhook de notificación sigue ahora automáticamente el estado SSL activo, cambiando entre `http://` y `https://` cuando toggleas HTTPS en el panel.
- **Cascada de 401 frontend** — la login screen ya no se traga un 401 para siempre tras un estado breve de token rancio; la flag de dedup se limpia al mount y al login exitoso.

---

## 🙏 Acknowledgments

Esta release incluye contribuciones de código directas de la comunidad y una cantidad sustancial de feedback que dio forma al diseño. Particular agradecimiento a:

### Contributors de código

**[@jcastro](https://github.com/jcastro)** entregó cinco mejoras directas que shipean con v1.2.2:

- **Selección de ISOs de VM desde todos los almacenamientos ISO** — nuevo helper compartido `scripts/global/iso_storage_helpers.sh` más integración en `vm_creator.sh`, `select_linux_iso.sh` y `select_windows_iso.sh`. El picker de ISO lee ahora desde cada almacenamiento Proxmox tagueado como ISO content en lugar de estar pinned a `local`. Commit [`092b548d`](https://github.com/MacRimi/ProxMenux/commit/092b548d).
- **Selector de canal de release en Settings** — un menú proper bajo `scripts/menus/config_menu.sh` para flipear entre los canales de install estable y beta in-place, con la gestión correcta de `version.txt` / `beta_version.txt` en cada lado. Commit [`f8a8c43d`](https://github.com/MacRimi/ProxMenux/commit/f8a8c43d).
- **ZFS autotrim en el auto post-install** — `auto_post_install.sh` habilita ahora `autotrim=on` en pools ZFS root por defecto (con el disable correspondiente en el path de uninstall), de forma que installs SSD-backed reclaman espacio liberado sin intervención manual. Commit [`8877f987`](https://github.com/MacRimi/ProxMenux/commit/8877f987).
- **Detección de webhook loopback + handoff de update** — `flask_notification_routes.py` clasifica correctamente webhooks de `127.0.0.1` / `localhost` como loopback, y el handoff de update del script `menu` ya no flackea en edge cases. Commit [`70ab072c`](https://github.com/MacRimi/ProxMenux/commit/70ab072c).
- **Figurine bumped a 2.0.0** — refresh del banner tool en `customizable_post_install.sh`, con la página de docs actualizada para matchear. Commit [`aba94028`](https://github.com/MacRimi/ProxMenux/commit/aba94028).

**[@pespinel](https://github.com/pespinel)** arregló una regresión del beta-installer que rompía los paths de servicio tras el move al nuevo layout runtime — `install_proxmenux_beta.sh` resuelve ahora los paths correctos de la unit systemd en first install y en update. Commit [`0daab74a`](https://github.com/MacRimi/ProxMenux/commit/0daab74a).

### Field reports que dieron forma al trabajo de GPU + Coral

Los reports detallados y sugerencias de **[@ghosthvj](https://github.com/ghosthvj)** sobre el flujo de hardware passthrough impulsaron las mejoras de scripts de GPU en esta release. Los fixes del instalador NVIDIA, el hardening del lifecycle de GPU + audio acompañante en `switch_gpu_mode.sh`, y el checklist de audio-companion iGPU en `add_gpu_vm.sh::detect_optional_gpu_audio` empezaron todos desde sus reports de edge cases que los paths de código previos manejaban pobremente.

### Todos los demás

Un gracias enorme a cada usuario que abrió un issue en GitHub, comentó en [GitHub Discussions](https://github.com/MacRimi/ProxMenux/discussions), reportó un bug en el canal de la comunidad, o pasó a compartir qué funcionaba y qué no en su hardware. **Muchas de las mejoras internas en esta release — el stagger del scheduler de smartctl, el fix de caché de fail2ban, el reemplazo `lxc-info /proc`, el handshake del terminal HTTPS, la detección de kernel-update en PVE 9.x, todo el wiring de Apprise — empezaron como un report de alguien encontrándose con el problema.** Seguid llegando.

---


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
