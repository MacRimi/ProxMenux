# 📘 Guía Completa: Compartir Recursos entre Proxmox Host y Contenedores LXC

## 📋 Índice

1. [Conceptos Fundamentales](#1-conceptos-fundamentales)
   - [Usuarios y Grupos en Linux](#usuarios-y-grupos-en-linux)
   - [Permisos Básicos](#permisos-básicos)
   - [El Bit Setgid](#el-bit-setgid)
   - [Access Control Lists (ACL)](#access-control-lists-acl)
   - [Contenedores Privilegiados vs No Privilegiados](#contenedores-privilegiados-vs-no-privilegiados)

2. [Cómo Funcionan los Permisos en Recursos Compartidos](#2-cómo-funcionan-los-permisos-en-recursos-compartidos)
   - [Servidores NFS](#servidores-nfs)
   - [Servidores Samba/CIFS](#servidores-sambacifs)
   - [Directorios Locales](#directorios-locales)

3. [Preparación del Host Proxmox](#3-preparación-del-host-proxmox)
   - [Crear Directorio Local](#crear-directorio-local)
   - [Montar Recurso NFS](#montar-recurso-nfs)
   - [Montar Recurso Samba](#montar-recurso-samba)

4. [Configuración de Contenedores](#4-configuración-de-contenedores)
   - [Contenedores Privilegiados](#contenedores-privilegiados)
   - [Contenedores No Privilegiados](#contenedores-no-privilegiados)

5. [Montaje en Contenedores](#5-montaje-en-contenedores)

6. [Verificación y Pruebas](#6-verificación-y-pruebas)

7. [Solución de Problemas](#7-solución-de-problemas)

---

## 1. Conceptos Fundamentales

### Usuarios y Grupos en Linux

#### ¿Qué es un Usuario?

Un **usuario** en Linux es una identidad que puede:
- Poseer archivos y directorios
- Ejecutar procesos
- Tener permisos específicos

Cada usuario tiene:
- **Nombre**: Como `root`, `www-data`, `juan`, `jonatan`, `proxmenux`, `rafa` etc...
- **UID (User ID)**: Número único, como `0` (root), `33` (www-data), `1000` (primer usuario),`1001` (segundo usuario), etc...

```bash
# Ver información de un usuario
id www-data
# Salida: uid=33(www-data) gid=33(www-data) groups=33(www-data)


# Listar todos los usuarios del sistema
cat /etc/passwd | head -5
# Salida:
# root:x:0:0:root:/root:/bin/bash
# daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
# bin:x:2:2:bin:/bin:/usr/sbin/nologin
```

#### ¿Qué es un Grupo?

Un **grupo** es una colección de usuarios que comparten permisos. Permite:
- Dar acceso a múltiples usuarios sin configurar cada uno individualmente
- Organizar permisos de manera lógica
- Simplificar la administración

Cada grupo tiene:
- **Nombre**: Como `root`, `www-data`, `sharedfiles`
- **GID (Group ID)**: Número único, como `0` (root), `33` (www-data), `1000` (usuarios)

```bash
# Ver todos los grupos
cat /etc/group | head -5
# Salida:
# root:x:0:
# daemon:x:1:
# bin:x:2:


# Ver grupos de un usuario
groups www-data
# Salida: www-data : www-data


# Crear un nuevo grupo
groupadd -g 1001 migrupo


# Añadir usuario a un grupo
usermod -aG migrupo www-data
```

#### ¿Por qué son importantes los grupos?

**Ejemplo práctico**: Tienes 3 contenedores que ejecutan aplicaciones web:
- **Sin grupos**: Tendrías que dar permisos individuales a cada usuario de cada contenedor
- **Con grupos**: Creas un grupo `webapps`, añades todos los usuarios web, y das permisos al grupo

### Permisos Básicos

#### Tipos de Permisos

Cada archivo y directorio tiene tres tipos de permisos para tres categorías de usuarios:

| Permiso | Símbolo | Valor | En Archivos | En Directorios |
|---------|---------|-------|-------------|----------------|
| **Lectura** | `r` | 4 | Leer contenido | Listar archivos |
| **Escritura** | `w` | 2 | Modificar archivo | Crear/eliminar archivos |
| **Ejecución** | `x` | 1 | Ejecutar archivo | Entrar al directorio |

#### Categorías de Usuarios

| Categoría | Descripción | Posición |
|-----------|-------------|----------|
| **Propietario** (user) | El dueño del archivo | Primera posición |
| **Grupo** (group) | Miembros del grupo propietario | Segunda posición |
| **Otros** (others) | Todos los demás usuarios | Tercera posición |

#### Lectura de Permisos

```bash
ls -l /mnt/ejemplo
# Salida: drwxrwxr-x 2 root sharedfiles 4096 sep  8 10:30 ejemplo
#         │││││││││
#         │└┴┴┴┴┴┴┴─ Permisos
#         └─────────── Tipo (d=directorio, -=archivo)


# Desglose de permisos: rwxrwxr-x
# Propietario (root): rwx = 7 (lectura + escritura + ejecución)
# Grupo (sharedfiles): rwx = 7 (lectura + escritura + ejecución)  
# Otros: r-x = 5 (lectura + ejecución, sin escritura)
```

#### Permisos Numéricos

Los permisos se pueden expresar como números de 3 dígitos:

```bash
# Ejemplos comunes
chmod 755 archivo    # rwxr-xr-x (propietario: todo, otros: lectura+ejecución)
chmod 644 archivo    # rw-r--r-- (propietario: lectura+escritura, otros: solo lectura)
chmod 775 directorio # rwxrwxr-x (propietario y grupo: todo, otros: lectura+ejecución)
```

### El Bit Setgid

El **setgid** es uno de los conceptos más importantes para directorios compartidos, pero también uno de los menos comprendidos.

#### ¿Qué hace el setgid?

Cuando se aplica a un directorio, el **setgid** hace que:
- **Todos los archivos y subdirectorios creados dentro hereden automáticamente el grupo del directorio padre**
- **No importa qué usuario o proceso cree el archivo, siempre tendrá el mismo grupo**

#### Ejemplo Práctico: Sin setgid

```bash
# Crear directorio sin setgid
mkdir /tmp/sin_setgid
chmod 775 /tmp/sin_setgid
chgrp sharedfiles /tmp/sin_setgid


ls -ld /tmp/sin_setgid
# Salida: drwxrwxr-x 2 root sharedfiles 4096 sep  8 10:30 /tmp/sin_setgid
#               ↑ No hay 's' en la posición del grupo


# Crear archivo como usuario www-data
sudo -u www-data touch /tmp/sin_setgid/archivo1
ls -l /tmp/sin_setgid/archivo1
# Salida: -rw-r--r-- 1 www-data www-data 0 sep  8 10:35 archivo1
# ❌ El archivo pertenece al grupo 'www-data', NO 'sharedfiles'


# Crear archivo como usuario root
touch /tmp/sin_setgid/archivo2
ls -l /tmp/sin_setgid/archivo2
# Salida: -rw-r--r-- 1 root root 0 sep  8 10:36 archivo2
# ❌ El archivo pertenece al grupo 'root', NO 'sharedfiles'
```

**Problema**: Cada usuario crea archivos con su grupo primario, causando inconsistencias.

#### Ejemplo Práctico: Con setgid

```bash
# Crear directorio CON setgid
mkdir /tmp/con_setgid  
chmod 2775 /tmp/con_setgid  # El '2' inicial activa setgid
chgrp sharedfiles /tmp/con_setgid


ls -ld /tmp/con_setgid
# Salida: drwxrwsr-x 2 root sharedfiles 4096 sep  8 10:37 /tmp/con_setgid
#               ↑ La 's' indica que setgid está activo


# Crear archivo como usuario www-data
sudo -u www-data touch /tmp/con_setgid/archivo1
ls -l /tmp/con_setgid/archivo1
# Salida: -rw-r--r-- 1 www-data sharedfiles 0 sep  8 10:38 archivo1
# ✅ El archivo hereda el grupo 'sharedfiles' del directorio padre


# Crear archivo como usuario root
touch /tmp/con_setgid/archivo2
ls -l /tmp/con_setgid/archivo2
# Salida: -rw-r--r-- 1 root sharedfiles 0 sep  8 10:39 archivo2
# ✅ El archivo también hereda el grupo 'sharedfiles'


# Crear subdirectorio
mkdir /tmp/con_setgid/subdir
ls -ld /tmp/con_setgid/subdir
# Salida: drwxr-sr-x 2 root sharedfiles 4096 sep  8 10:40 subdir
# ✅ El subdirectorio hereda el grupo Y también tiene setgid activo
```

#### ¿Por qué es crucial setgid para recursos compartidos?

1. **Consistencia**: Todos los archivos tienen el mismo grupo, independientemente de quién los cree
2. **Simplicidad**: No necesitas cambiar manualmente el grupo de cada archivo nuevo
3. **Herencia**: Los subdirectorios también heredan el setgid, manteniendo la consistencia en toda la estructura
4. **Compatibilidad**: Funciona con NFS, Samba, y contenedores sin configuración adicional

### Access Control Lists (ACL)

#### Limitaciones de los Permisos Tradicionales

Los permisos tradicionales de Linux solo permiten:
- **1 propietario**
- **1 grupo**
- **Permisos para "otros"**

**Problema**: ¿Qué pasa si necesitas que 3 grupos diferentes tengan acceso de escritura?

#### ¿Qué son las ACL?

Las **Access Control Lists (ACL)** extienden los permisos tradicionales permitiendo:
- **Múltiples usuarios** con permisos específicos
- **Múltiples grupos** con permisos específicos
- **Permisos por defecto** que se heredan automáticamente

```bash
# Instalar herramientas ACL
apt-get install acl

# Ver ACL de un archivo/directorio
getfacl /mnt/shared
# Salida:
# file: mnt/shared
# owner: root
# group: sharedfiles
# user::rwx
# group::rwx
# group:webapps:rwx
# group:developers:r-x
# other::r-x
# default:user::rwx
# default:group::rwx
# default:group:webapps:rwx
# default:other::r-x
```

#### Configurar ACL

```bash
# Dar permisos a un grupo específico
setfacl -m g:webapps:rwx /mnt/shared

# Dar permisos a un usuario específico  
setfacl -m u:juan:rw /mnt/shared

# Configurar permisos por defecto (se heredan)
setfacl -d -m g:webapps:rwx /mnt/shared

# Aplicar ACL recursivamente a todo el contenido existente
setfacl -R -m g:webapps:rwx /mnt/shared

# Combinar: aplicar a existente Y configurar por defecto
setfacl -R -m g:webapps:rwx /mnt/shared
setfacl -d -m g:webapps:rwx /mnt/shared
```

#### ¿Por qué son importantes las ACL para NFS y Samba?

**NFS y mapeo de IDs**:
- NFS transmite solo números (UID/GID), no nombres
- Si el cliente tiene usuarios con IDs diferentes, los permisos se rompen
- Las ACL aseguran que el grupo correcto siempre tenga acceso

**Ejemplo práctico**:
```bash
# Servidor NFS: usuario 'web' tiene UID 1001
# Cliente NFS: usuario 'web' tiene UID 1002

# Sin ACL: El cliente ve archivos del UID 1001 (usuario inexistente)
# Con ACL: El grupo 'webapps' siempre tiene acceso, independiente de UIDs
```

### Contenedores Privilegiados vs No Privilegiados

#### ¿Qué son los Contenedores No Privilegiados?

Los contenedores **no privilegiados** son más seguros porque:
- El usuario `root` del contenedor NO es `root` del host
- Los IDs de usuario/grupo están "desplazados"
- Limitan el daño si el contenedor es comprometido

#### Mapeo de IDs

En un contenedor no privilegiado típico:

| Contenedor | Host | Explicación |
|------------|------|-------------|
| UID 0 (root) | UID 100000 | Root del contenedor = usuario 100000 del host |
| UID 1 | UID 100001 | Usuario 1 del contenedor = usuario 100001 del host |
| UID 1000 (usuario) | UID 101000 | Usuario 1000 del contenedor = usuario 101000 del host |
| GID 0 (root) | GID 100000 | Grupo root del contenedor = grupo 100000 del host |
| GID 1000 (grupo) | GID 101000 | Grupo 1000 del contenedor = grupo 101000 del host |

#### El Problema en la Práctica

```bash
# En el HOST: Crear archivo con grupo 'sharedfiles' (GID 1000)
echo "datos" > /mnt/shared/archivo.txt
chgrp sharedfiles /mnt/shared/archivo.txt
ls -l /mnt/shared/archivo.txt
# Salida: -rw-r--r-- 1 root sharedfiles 6 sep  8 archivo.txt


# En el CONTENEDOR NO PRIVILEGIADO: Ver el mismo archivo
pct exec 101 -- ls -l /mnt/shared/archivo.txt
# Salida: -rw-r--r-- 1 nobody nogroup 6 sep  8 archivo.txt
# ❌ El contenedor ve 'nobody:nogroup' porque no conoce el GID 1000 del host
```

#### ¿Por qué pasa esto?

1. **Host**: El archivo pertenece al GID 1000 (`sharedfiles`)
2. **Contenedor**: Busca qué grupo tiene GID 1000 en SU `/etc/group`
3. **Resultado**: Si no existe ese GID en el contenedor, muestra `nogroup`
4. **Consecuencia**: El usuario del contenedor no puede escribir

---

## 2. Cómo Funcionan los Permisos en Recursos Compartidos

### Servidores NFS

#### ¿Cómo maneja NFS los permisos?

Los servidores NFS (ya sean Linux, TrueNAS, Synology, etc.) funcionan de manera similar:

1. **Solo transmiten números**: NFS envía UID/GID numéricos, no nombres de usuario
2. **No hay autenticación de usuario**: NFS confía en que el cliente ya autenticó al usuario
3. **Los permisos se evalúan en el servidor**: El servidor NFS verifica permisos usando sus propios archivos `/etc/passwd` y `/etc/group`

#### Ejemplo con TrueNAS

```bash
# En TrueNAS: Crear dataset con permisos
# Dataset: /mnt/pool/shared
# Propietario: root (UID 0)
# Grupo: shared (GID 1001)  
# Permisos: 775


# En Proxmox: Montar el NFS
mount -t nfs 192.168.1.100:/mnt/pool/shared /mnt/truenas_shared


# Ver cómo se ven los permisos en Proxmox
ls -ld /mnt/truenas_shared
# Salida: drwxrwxr-x 2 root 1001 4096 sep  8 10:45 /mnt/truenas_shared
#                        ↑ Aparece el GID numérico porque Proxmox no tiene grupo con GID 1001
```

#### Solución: Crear grupo con el mismo GID

```bash
# En Proxmox: Crear grupo con el mismo GID que TrueNAS
groupadd -g 1001 truenas_shared


# Ahora se ve correctamente
ls -ld /mnt/truenas_shared
# Salida: drwxrwxr-x 2 root truenas_shared 4096 sep  8 10:45 /mnt/truenas_shared
```

#### Configuraciones comunes en servidores NFS

**TrueNAS/FreeNAS**:
- Maptype: Unix
- Usuario: root o usuario específico
- Grupo: wheel, shared, o grupo personalizado

**Synology**:
- Squash: No mapping
- Usuario: root o admin
- Grupo: users o grupo personalizado

**Linux (Ubuntu/Debian)**:
```bash
# /etc/exports
/export/shared 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
```

### Servidores Samba/CIFS

#### ¿Cómo maneja Samba los permisos?

Samba es más complejo porque debe mapear entre:
1. **Usuarios Windows** (autenticación SMB)
2. **Usuarios Linux** (permisos del sistema de archivos)

#### Ejemplo con Synology

```bash
# En Synology: Crear carpeta compartida
# Nombre: SharedData
# Permisos SMB: Grupo 'users' con lectura/escritura
# Permisos Linux: 775, propietario 'admin', grupo 'users'


# En Proxmox: Montar Samba
mount -t cifs //192.168.1.200/SharedData /mnt/synology_shared \
  -o username=admin,password=mipassword,uid=root,gid=1000,file_mode=0664,dir_mode=0775


# Ver permisos
ls -ld /mnt/synology_shared
# Salida: drwxrwxr-x 2 root 1000 4096 sep  8 10:50 /mnt/synology_shared
#                        ↑ Usa el GID especificado en las opciones de montaje
```

#### Opciones importantes de montaje CIFS

- `uid=`: UID que se asigna a todos los archivos
- `gid=`: GID que se asigna a todos los archivos  
- `file_mode=`: Permisos para archivos (ej: 0664)
- `dir_mode=`: Permisos para directorios (ej: 0775)
- `forceuid/forcegid`: Fuerza el uso de uid/gid especificados

### Directorios Locales

Los directorios locales son los más simples:
- Los permisos se respetan directamente
- No hay mapeo de red
- Funciona con usuarios y grupos locales del sistema

---

## 3. Preparación del Host Proxmox

### Crear Directorio Local

Para crear un directorio local que se compartirá con contenedores:

```bash
# 1. Crear directorio
mkdir -p /mnt/local_shared


# 2. Crear grupo común (usaremos GID 101000 para compatibilidad universal)
groupadd -g 101000 sharedfiles


# 3. Configurar propietario y permisos con setgid
chown root:sharedfiles /mnt/local_shared
chmod 2775 /mnt/local_shared


# 4. Aplicar ACL para garantizar permisos
setfacl -R -m g:sharedfiles:rwx /mnt/local_shared
setfacl -d -m g:sharedfiles:rwx /mnt/local_shared


# 5. Verificar configuración
ls -ld /mnt/local_shared
# Salida esperada: drwxrwsr-x+ 2 root sharedfiles 4096 sep  8 11:00 /mnt/local_shared
#                       ↑ 's' indica setgid activo
#                          ↑ '+' indica ACL aplicadas


getfacl /mnt/local_shared
# Salida esperada:
# file: mnt/local_shared
# owner: root
# group: sharedfiles
# user::rwx
# group::rwx
# other::r-x
# default:user::rwx
# default:group::rwx
# default:other::r-x
```

### Montar Recurso NFS

#### Montaje Temporal

```bash
# 1. Crear punto de montaje
mkdir -p /mnt/nfs_shared


# 2. Montar NFS
mount -t nfs 192.168.1.100:/export/shared /mnt/nfs_shared


# 3. Verificar montaje
df -h | grep nfs
mount | grep nfs


# 4. Ver permisos originales
ls -ld /mnt/nfs_shared
# Ejemplo: drwxrwxr-x 2 root 1001 4096 sep  8 11:05 /mnt/nfs_shared
```

#### Crear Grupo Compatible

```bash
# Si el directorio NFS tiene un GID específico (ej: 1001), crear grupo local
groupadd -g 1001 nfs_shared


# Verificar que ahora se ve el nombre del grupo
ls -ld /mnt/nfs_shared
# Salida: drwxrwxr-x 2 root nfs_shared 4096 sep  8 11:05 /mnt/nfs_shared
```

#### Aplicar Configuración Universal

```bash
# Para compatibilidad con contenedores, aplicar nuestro esquema estándar
# IMPORTANTE: Solo si tienes permisos de escritura en el NFS


# Crear nuestro grupo estándar
groupadd -g 101000 sharedfiles


# Cambiar grupo del directorio NFS (si es posible)
chgrp sharedfiles /mnt/nfs_shared


# Aplicar setgid y ACL
chmod 2775 /mnt/nfs_shared
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_shared
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_shared
```

#### Montaje Persistente

```bash
# Editar /etc/fstab
nano /etc/fstab


# Añadir línea:
192.168.1.100:/export/shared /mnt/nfs_shared nfs rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev 0 0


# Explicación de opciones:
# rw: lectura/escritura
# hard: reintentar indefinidamente si el servidor no responde
# nofail: no fallar el arranque si no se puede montar
# rsize/wsize: tamaño de buffer para lectura/escritura (mejor rendimiento)
# timeo: timeout en décimas de segundo (60 segundos)
# retrans: número de reintentos antes de reportar error
# _netdev: esperar a que la red esté disponible
# 0 0: no hacer dump ni fsck (siempre para recursos de red)

# Probar montaje
mount -a


# Verificar
df -h | grep nfs
```

### Montar Recurso Samba

#### Crear Archivo de Credenciales

```bash
# Crear archivo de credenciales seguro
nano /etc/cifs-credentials


# Contenido:
username=tu_usuario
password=tu_password
domain=tu_dominio


# Proteger archivo
chmod 600 /etc/cifs-credentials
chown root:root /etc/cifs-credentials
```

#### Montaje Temporal

```bash
# 1. Crear punto de montaje
mkdir -p /mnt/samba_shared


# 2. Montar Samba con opciones específicas
mount -t cifs //192.168.1.200/SharedData /mnt/samba_shared \
  -o credentials=/etc/cifs-credentials,uid=root,gid=101000,file_mode=0664,dir_mode=2775,iocharset=utf8,vers=3.0


# Explicación de opciones:
# credentials: archivo con usuario/password
# uid=root: todos los archivos aparecen como propietario root
# gid=101000: todos los archivos aparecen con grupo sharedfiles
# file_mode=0664: permisos para archivos (rw-rw-r--)
# dir_mode=2775: permisos para directorios (rwxrwsr-x) con setgid
# iocharset=utf8: codificación de caracteres
# vers=3.0: versión del protocolo SMB


# 3. Verificar montaje
df -h | grep cifs
ls -ld /mnt/samba_shared
```

#### Configurar Grupo y Permisos

```bash
# Crear grupo si no existe
groupadd -g 101000 sharedfiles


# Verificar que los permisos son correctos
ls -ld /mnt/samba_shared
# Salida esperada: drwxrwsr-x 2 root sharedfiles 4096 sep  8 11:10 /mnt/samba_shared


# Aplicar ACL adicionales si es necesario
setfacl -R -m g:sharedfiles:rwx /mnt/samba_shared
setfacl -d -m g:sharedfiles:rwx /mnt/samba_shared
```

#### Montaje Persistente

```bash
# Editar /etc/fstab
nano /etc/fstab


# Añadir línea:
//192.168.1.200/SharedData /mnt/samba_shared cifs credentials=/etc/cifs-credentials,uid=root,gid=101000,file_mode=0664,dir_mode=2775,iocharset=utf8,vers=3.0,_netdev,nofail 0 0


# Probar montaje
mount -a


# Verificar
df -h | grep cifs
```

---

## 4. Configuración de Contenedores

### Contenedores Privilegiados

Los contenedores privilegiados comparten los mismos UIDs/GIDs que el host, por lo que la configuración es más directa.

#### ¿Necesitan configuración especial?

**Respuesta corta**: Generalmente NO, pero hay casos donde SÍ es recomendable.

#### Cuándo NO necesitan configuración

Si el contenedor privilegiado:
- Solo usa el usuario `root`
- No ejecuta servicios con usuarios específicos (como `www-data`)
- Los archivos siempre se crean como `root:root`

```bash
# Ejemplo: Contenedor que solo usa root
pct exec 100 -- bash
whoami  # root
id      # uid=0(root) gid=0(root) groups=0(root)


# Crear archivo en directorio compartido
echo "test" > /mnt/shared/archivo.txt
ls -l /mnt/shared/archivo.txt
# Salida: -rw-r--r-- 1 root root 5 sep  8 11:15 archivo.txt
# ❌ El archivo pertenece al grupo 'root', no 'sharedfiles'
```

#### Cuándo SÍ necesitan configuración

Si el contenedor privilegiado:
- Ejecuta servicios web (`www-data`, `nginx`, `apache`)
- Tiene aplicaciones que crean archivos con usuarios específicos
- Necesita compatibilidad con otros contenedores o servicios

```bash
# Ejemplo: Contenedor con Nextcloud
pct exec 100 -- bash


# Ver usuarios del sistema
cat /etc/passwd | grep -E "(www-data|nginx|apache)"
# Salida: www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin


# Sin configuración: Nextcloud crea archivos como www-data:www-data
sudo -u www-data touch /mnt/shared/nextcloud_file.txt
ls -l /mnt/shared/nextcloud_file.txt
# Salida: -rw-r--r-- 1 www-data www-data 0 sep  8 11:20 nextcloud_file.txt
# ❌ Grupo 'www-data' no es compatible con otros contenedores
```

#### Configuración Recomendada para Contenedores Privilegiados

```bash
# 1. Entrar al contenedor
pct exec 100 -- bash


# 2. Crear grupo con el mismo GID que el host
groupadd -g 101000 sharedfiles


# 3. Añadir usuarios relevantes al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data


# Si tienes otros usuarios específicos de aplicaciones:
usermod -aG sharedfiles nextcloud 2>/dev/null || true
usermod -aG sharedfiles nginx 2>/dev/null || true
# (añade los usuaros que desees)


# 4. Verificar membresía
groups root
# Salida: root : root sharedfiles


groups www-data  
# Salida: www-data : www-data sharedfiles


# 5. Salir del contenedor
exit
```

#### ¿Por qué es importante esta configuración?

1. **Consistencia**: Los archivos creados por diferentes usuarios mantienen el grupo `sharedfiles`
2. **Compatibilidad**: Funciona con contenedores no privilegiados y otros servicios
3. **Flexibilidad**: Permite que múltiples usuarios/servicios accedan a los mismos archivos

### Contenedores No Privilegiados

Los contenedores no privilegiados SIEMPRE necesitan configuración especial debido al mapeo de UIDs/GIDs.

#### Configuración Obligatoria

```bash
# 1. Entrar al contenedor
pct exec 101 -- bash


# 2. Crear grupo con GID mapeado
# GID 1000 en contenedor = GID 101000 en host
groupadd -g 1000 sharedfiles


# 3. Listar usuarios disponibles en el contenedor
awk -F: '$3>=1000 && $1!="nobody" {print $1 " (UID: " $3 ")"}' /etc/passwd
# Salida típica:
# root (UID: 0)
# www-data (UID: 33)  
# ncp (UID: 1000)


# También incluir usuarios del sistema si es necesario
awk -F: '$3<1000 && $3>0 && $1!="nobody" {print $1 " (UID: " $3 ")"}' /etc/passwd


# 4. Añadir usuarios al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data


# Si tienes usuarios específicos de aplicaciones:
usermod -aG sharedfiles ncp 2>/dev/null || true
usermod -aG sharedfiles nextcloud 2>/dev/null || true
# (añade los usuaros que desees)


# 5. Verificar configuración
id www-data
# Salida esperada: uid=33(www-data) gid=33(www-data) groups=33(www-data),1000(sharedfiles)


# 6. Salir del contenedor
exit
```

#### Cómo Añadir Más Usuarios

Si instalas nuevas aplicaciones que crean usuarios adicionales:

```bash
# Entrar al contenedor
pct exec 101 -- bash


# Buscar nuevos usuarios (UID >= 100)
awk -F: '$3>=100 && $3<65534 {print $1 " (UID: " $3 ", GID: " $4 ")"}' /etc/passwd


# Añadir al grupo sharedfiles
usermod -aG sharedfiles nombre_usuario


# Verificar
groups nombre_usuario
```

#### Añadir TODOS los usuarios automáticamente

```bash
# Script para añadir todos los usuarios relevantes
pct exec 101 -- bash -c '
# Obtener todos los usuarios con UID >= 100 y < 65534 (excluyendo nobody)
for user in $(awk -F: "$3>=100 && $3<65534 && $1!=\"nobody\" {print $1}" /etc/passwd); do
    echo "Añadiendo usuario: $user"
    usermod -aG sharedfiles "$user" 2>/dev/null || echo "Error añadiendo $user"
done

# Verificar usuarios añadidos
echo "Usuarios en grupo sharedfiles:"
getent group sharedfiles
'
```

---

## 5. Montaje en Contenedores

### Configuración del Montaje

Para ambos tipos de contenedores, el montaje se configura igual, pero con consideraciones importantes:
Por ejemplo:
```bash
# Para contenedor privilegiado (ID 100)
pct set 100 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1


# Para contenedor no privilegiado (ID 101)  
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1


# Reiniciar contenedores para activar montajes
pct reboot 100
pct reboot 101

```

#### Explicación de Parámetros

- **`/mnt/shared_data`**: Ruta en el HOST (donde está montado el recurso)
- **`mp=/mnt/shared`**: Ruta en el CONTENEDOR (donde aparecerá el directorio)
- **`backup=0`**: Excluir del backup de vzdump (recomendado para recursos de red)
- **`acl=1`**: Habilitar soporte para ACL dentro del contenedor
- **`shared=1`**: **CRUCIAL para clusters** - permite migración sin copiar datos

#### ¿Por qué shared=1 es importante?

Sin `shared=1`:
- Proxmox intenta copiar todo el contenido durante migraciones
- Falla si el directorio contiene muchos datos
- No funciona con recursos de red

Con `shared=1`:
- Proxmox asume que el directorio está disponible en todos los nodos
- Solo migra la configuración, no los datos
- Funciona perfectamente con NFS, Samba, y almacenamiento compartido

### Verificación del Montaje

```bash
# Verificar que el montaje está activo
pct exec 100 -- df -h | grep shared
pct exec 101 -- df -h | grep shared


# Verificar permisos dentro de los contenedores
pct exec 100 -- ls -ld /mnt/shared
pct exec 101 -- ls -ld /mnt/shared


# Verificar ACL dentro de los contenedores
pct exec 100 -- getfacl /mnt/shared
pct exec 101 -- getfacl /mnt/shared
```

---

## 6. Verificación y Pruebas

### Prueba Básica de Escritura

#### Desde el Host

```bash
# Crear archivo de prueba desde el host
echo "Archivo creado desde HOST" > /mnt/shared_data/test_host.txt


# Verificar propietario y permisos
ls -l /mnt/shared_data/test_host.txt
# Salida esperada: -rw-rw-r--+ 1 root sharedfiles 26 sep  8 12:00 test_host.txt
```

#### Desde Contenedor Privilegiado

```bash
# Crear archivo como root
pct exec 100 -- bash -c 'echo "Archivo desde contenedor privilegiado (root)" > /mnt/shared/test_priv_root.txt'


# Crear archivo como www-data
pct exec 100 -- sudo -u www-data bash -c 'echo "Archivo desde contenedor privilegiado (www-data)" > /mnt/shared/test_priv_www.txt'


# Verificar en el host
ls -l /mnt/shared_data/test_priv_*
# Salida esperada:
# -rw-rw-r--+ 1 root sharedfiles 42 sep  8 12:01 test_priv_root.txt
# -rw-rw-r--+ 1 www-data sharedfiles 48 sep  8 12:01 test_priv_www.txt
```

#### Desde Contenedor No Privilegiado

```bash
# Crear archivo como root del contenedor
pct exec 101 -- bash -c 'echo "Archivo desde contenedor no privilegiado (root)" > /mnt/shared/test_unpriv_root.txt'


# Crear archivo como www-data del contenedor
pct exec 101 -- sudo -u www-data bash -c 'echo "Archivo desde contenedor no privilegiado (www-data)" > /mnt/shared/test_unpriv_www.txt'


# Verificar en el host
ls -l /mnt/shared_data/test_unpriv_*
# Salida esperada:
# -rw-rw-r--+ 1 100000 sharedfiles 46 sep  8 12:02 test_unpriv_root.txt
# -rw-rw-r--+ 1 100033 sharedfiles 52 sep  8 12:02 test_unpriv_www.txt
#              ↑ UIDs mapeados (+100000)
```

### Prueba de Acceso Cruzado

```bash
# Desde contenedor privilegiado, leer archivo del no privilegiado
pct exec 100 -- cat /mnt/shared/test_unpriv_root.txt
# Salida: Archivo desde contenedor no privilegiado (root)


# Desde contenedor no privilegiado, leer archivo del privilegiado
pct exec 101 -- cat /mnt/shared/test_priv_root.txt
# Salida: Archivo desde contenedor privilegiado (root)


# Modificar archivo desde diferentes contenedores
pct exec 100 -- bash -c 'echo "Modificado desde privilegiado" >> /mnt/shared/test_unpriv_root.txt'
pct exec 101 -- bash -c 'echo "Modificado desde no privilegiado" >> /mnt/shared/test_priv_root.txt'


# Verificar contenido
cat /mnt/shared_data/test_unpriv_root.txt
cat /mnt/shared_data/test_priv_root.txt
```

### Prueba de Herencia de Permisos

```bash
# Crear subdirectorio desde contenedor
pct exec 100 -- mkdir /mnt/shared/subdir_test


# Verificar que hereda setgid y grupo
ls -ld /mnt/shared_data/subdir_test
# Salida esperada: drwxrwsr-x+ 2 root sharedfiles 4096 sep  8 12:05 subdir_test
#                        ↑ 's' indica setgid heredado


# Crear archivo en subdirectorio
pct exec 101 -- touch /mnt/shared/subdir_test/archivo_en_subdir.txt


# Verificar herencia
ls -l /mnt/shared_data/subdir_test/archivo_en_subdir.txt
# Salida esperada: -rw-rw-r--+ 1 100000 sharedfiles 0 sep  8 12:06 archivo_en_subdir.txt
```


---

## 7. Solución de Problemas

### Error: "Permission denied" al escribir

#### Síntomas
```bash
pct exec 101 -- touch /mnt/shared/test.txt
# touch: cannot touch '/mnt/shared/test.txt': Permission denied
```

#### Diagnóstico
```bash
# 1. Verificar permisos en el host
ls -ld /mnt/shared_data
getfacl /mnt/shared_data


# 2. Verificar grupo en el contenedor
pct exec 101 -- getent group sharedfiles


# 3. Verificar membresía del usuario
pct exec 101 -- groups www-data
```

#### Soluciones
```bash
# Solución 1: Recrear grupo en contenedor
pct exec 101 -- groupadd -g 1000 sharedfiles
pct exec 101 -- usermod -aG sharedfiles www-data


# Solución 2: Reaplicar ACL en host
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data


# Solución 3: Verificar setgid
chmod 2775 /mnt/shared_data
```

### Error: Archivos aparecen como "nobody:nogroup"

#### Síntomas
```bash
pct exec 101 -- ls -l /mnt/shared/
# -rw-r--r-- 1 nobody nogroup 100 sep  8 12:00 archivo.txt
```

#### Causa
El contenedor no tiene un grupo con el GID del archivo.

#### Solución
```bash
# 1. Ver GID numérico en el host
ls -n /mnt/shared_data/archivo.txt
# -rw-r--r-- 1 0 101000 100 sep  8 12:00 archivo.txt
#              ↑ GID 101000


# 2. Crear grupo en contenedor con GID mapeado
# GID 101000 en host = GID 1000 en contenedor no privilegiado
pct exec 101 -- groupadd -g 1000 sharedfiles


# 3. Verificar que ahora se ve correctamente
pct exec 101 -- ls -l /mnt/shared/archivo.txt
# -rw-r--r-- 1 nobody sharedfiles 100 sep  8 12:00 archivo.txt
```

### Error: "Transport endpoint is not connected" (NFS)

#### Síntomas
```bash
ls /mnt/nfs_shared
# ls: cannot access '/mnt/nfs_shared': Transport endpoint is not connected
```

#### Diagnóstico
```bash
# Verificar estado del montaje
mount | grep nfs
df -h | grep nfs


# Verificar conectividad
ping 192.168.1.100
showmount -e 192.168.1.100
```

#### Soluciones
```bash
# Solución 1: Remontar
umount /mnt/nfs_shared
mount -t nfs 192.168.1.100:/export/shared /mnt/nfs_shared


# Solución 2: Usar opciones más robustas
mount -t nfs 192.168.1.100:/export/shared /mnt/nfs_shared \
  -o hard,intr,rsize=32768,wsize=32768,timeo=600,retrans=2


# Solución 3: Verificar servicios NFS
systemctl status nfs-common
systemctl restart nfs-common
```

### Error: Contenedor no puede acceder después de migración

#### Síntomas
Después de migrar un contenedor a otro nodo, no puede acceder al directorio compartido.

#### Causa
El directorio compartido no está montado en el nodo destino, o falta `shared=1`.

#### Solución
```bash
# 1. Verificar configuración del contenedor
cat /etc/pve/lxc/101.conf | grep mp0
# Debe incluir: shared=1


# 2. Si falta shared=1, añadirlo
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1


# 3. Verificar que el directorio existe en el nodo destino
ls -ld /mnt/shared_data


# 4. Si no existe, montar el recurso en el nodo destino
# (repetir pasos de montaje NFS/Samba según corresponda)
```

### Error: "Operation not supported" con ACL

#### Síntomas
```bash
setfacl -m g:sharedfiles:rwx /mnt/shared_data
# setfacl: /mnt/shared_data: Operation not supported
```

#### Causa
El sistema de archivos no soporta ACL.

#### Diagnóstico
```bash
# Verificar tipo de sistema de archivos
df -T /mnt/shared_data


# Verificar opciones de montaje
mount | grep shared_data
```

#### Soluciones
```bash
# Para ext4: Remontar con soporte ACL
mount -o remount,acl /mnt/shared_data


# Para NFS: Añadir opción acl
umount /mnt/shared_data
mount -t nfs 192.168.1.100:/export/shared /mnt/shared_data -o acl


# Para sistemas de archivos que no soportan ACL:
# Usar solo permisos tradicionales con setgid
chmod 2775 /mnt/shared_data
```

### Archivos creados con permisos incorrectos

#### Síntomas
Los archivos se crean con permisos 644 en lugar de 664.

#### Causa
La umask del proceso no permite escritura de grupo.

#### Solución
```bash
# Verificar umask actual
pct exec 101 -- umask
# Si es 022, cambiar a 002


# Cambiar umask temporalmente
pct exec 101 -- umask 002


# Cambiar umask permanentemente
pct exec 101 -- bash -c 'echo "umask 002" >> /etc/profile'


# Alternativa: Usar ACL por defecto (más robusta)
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m o::r-x /mnt/shared_data
```

---

## 📋 Resumen de Comandos Clave

### Configuración del Host

```bash
# Crear directorio local
mkdir -p /mnt/shared_data
groupadd -g 101000 sharedfiles
chown root:sharedfiles /mnt/shared_data
chmod 2775 /mnt/shared_data
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data


# Montar NFS persistente
echo "192.168.1.100:/export/shared /mnt/nfs_shared nfs rw,hard,nofail,_netdev 0 0" >> /etc/fstab


# Montar Samba persistente  
echo "//192.168.1.200/share /mnt/samba_shared cifs credentials=/etc/cifs-creds,uid=root,gid=101000,file_mode=0664,dir_mode=2775,_netdev,nofail 0 0" >> /etc/fstab
```

### Configuración de Contenedores

```bash
# Contenedor privilegiado
pct exec 100 -- groupadd -g 101000 sharedfiles
pct exec 100 -- usermod -aG sharedfiles root
pct exec 100 -- usermod -aG sharedfiles www-data


# Contenedor no privilegiado
pct exec 101 -- groupadd -g 1000 sharedfiles
pct exec 101 -- usermod -aG sharedfiles root
pct exec 101 -- usermod -aG sharedfiles www-data


# Montaje
pct set 100 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1
```

### Verificación

```bash
# Verificar configuración
ls -ld /mnt/shared_data
getfacl /mnt/shared_data
pct exec 101 -- groups www-data


# Prueba de escritura
echo "test" > /mnt/shared_data/test.txt
pct exec 100 -- touch /mnt/shared/test_priv.txt
pct exec 101 -- touch /mnt/shared/test_unpriv.txt
```

---

## 🎯 Conclusión

Esta guía te ha mostrado cómo configurar correctamente recursos compartidos entre Proxmox y contenedores LXC, tanto privilegiados como no privilegiados. Los conceptos clave son:

1. **Grupo común** (`sharedfiles`) con GID consistente
2. **Setgid** (2775) para herencia automática de grupo
3. **ACL** para garantizar permisos robustos
4. **Mapeo correcto** de UIDs/GIDs en contenedores no privilegiados
5. **Configuración adecuada** de montajes con `shared=1`, `backup=0`, `acl=1`

Con esta configuración, tendrás un sistema robusto que funciona con NFS, Samba, directorios locales, y es compatible con clusters y migraciones de Proxmox.


