# 📘 Guía Completa: Compartir Recursos entre Proxmox Host y Contenedores LXC

## 📋 Índice

1. [Introducción](#introducción)
2. [Conceptos Fundamentales](#conceptos-fundamentales)
   - [Usuarios y Grupos en Linux](#usuarios-y-grupos-en-linux)
   - [Permisos en Linux](#permisos-en-linux)
   - [Access Control Lists (ACL)](#access-control-lists-acl)
   - [Contenedores No Privilegiados](#contenedores-no-privilegiados)
3. [Tipos de Recursos Compartidos](#tipos-de-recursos-compartidos)
   - [NFS (Network File System)](#nfs-network-file-system)
   - [Samba/CIFS](#sambacifs)
   - [Directorios Locales](#directorios-locales)
4. [Configuración Paso a Paso](#configuración-paso-a-paso)
   - [Preparación del Host](#preparación-del-host)
   - [Montar Recursos Compartidos](#montar-recursos-compartidos)
   - [Configurar Contenedores](#configurar-contenedores)
   - [Crear Puntos de Montaje](#crear-puntos-de-montaje)
5. [Verificación y Pruebas](#verificación-y-pruebas)
6. [Solución de Problemas](#solución-de-problemas)
7. [Mejores Prácticas](#mejores-prácticas)

---

## Introducción

Esta guía explica cómo compartir recursos (NFS, Samba, directorios locales) entre el host de Proxmox y contenedores LXC, tanto privilegiados como no privilegiados, manteniendo permisos correctos y acceso de lectura/escritura.

### ¿Por qué es complejo?

- Los **contenedores no privilegiados** usan IDs de usuario/grupo desplazados (+100000)
- **NFS y Samba** manejan permisos de manera diferente
- Los **permisos tradicionales** de Linux tienen limitaciones
- La **persistencia** tras reinicios requiere configuración específica

### ¿Qué aprenderás?

- Cómo funcionan los permisos en Linux y por qué fallan con contenedores
- Qué son las ACL y por qué son esenciales para recursos compartidos
- Cómo configurar correctamente NFS, Samba y directorios locales
- Por qué usar el GID 101000 y el grupo `sharedfiles`
- Cómo hacer que todo sea persistente tras reinicios

---

## Conceptos Fundamentales

### Usuarios y Grupos en Linux

#### ¿Qué es un Usuario?

Un **usuario** en Linux es una identidad que puede:
- Poseer archivos y directorios
- Ejecutar procesos
- Tener permisos específicos

Cada usuario tiene:
- **Nombre**: Como `root`, `www-data`, `ncp`
- **UID (User ID)**: Número único, como `0` (root), `33` (www-data), `1000` (primer usuario)

```bash
# Ver información de un usuario
id www-data
# Salida: uid=33(www-data) gid=33(www-data) groups=33(www-data)

# Listar usuarios del sistema (solo los relevantes)
awk -F: '$3>=1000 && $1!="nobody"{print $1 " (UID: " $3 ")"}' /etc/passwd
# Salida ejemplo:
# ncp (UID: 1000)
# usuario1 (UID: 1001)
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
# Ver todos los grupos relevantes
getent group | grep -E "(root|www-data|sharedfiles)" | head -5
# Salida:
# root:x:0:
# www-data:x:33:
# sharedfiles:x:101000:

# Ver grupos de un usuario
groups www-data
# Salida: www-data : www-data

# Crear un nuevo grupo con GID específico
groupadd -g 101000 sharedfiles

# Añadir usuario a un grupo
usermod -aG sharedfiles www-data
```

#### ¿Por qué son importantes los grupos?

**Ejemplo práctico**: Tienes 3 contenedores que ejecutan aplicaciones web:
- **Sin grupos**: Tendrías que dar permisos individuales a cada usuario de cada contenedor
- **Con grupos**: Creas un grupo `sharedfiles`, añades todos los usuarios web, y das permisos al grupo

---

### Permisos en Linux

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
# Ver permisos de un directorio específico
ls -ld /mnt/shared_data
# Salida: drwxrwxr-x 2 root sharedfiles 4096 sep  8 10:30 /mnt/shared_data
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

#### El Bit Setgid (Herencia de Grupo)

El **setgid** es crucial para directorios compartidos y es la clave para que funcionen correctamente:

```bash
# Sin setgid - PROBLEMA
mkdir /tmp/sin_setgid
chmod 775 /tmp/sin_setgid
chgrp sharedfiles /tmp/sin_setgid

# Crear archivo como usuario diferente
sudo -u www-data touch /tmp/sin_setgid/archivo1
ls -ld /tmp/sin_setgid/archivo1
# Salida: -rw-r--r-- 1 www-data www-data 0 sep  8 10:35 /tmp/sin_setgid/archivo1
# ❌ El archivo pertenece al grupo 'www-data', no 'sharedfiles'

# Con setgid - SOLUCIÓN
mkdir /tmp/con_setgid  
chmod 2775 /tmp/con_setgid  # El '2' inicial activa setgid
chgrp sharedfiles /tmp/con_setgid

sudo -u www-data touch /tmp/con_setgid/archivo2
ls -ld /tmp/con_setgid/archivo2
# Salida: -rw-r--r-- 1 www-data sharedfiles 0 sep  8 10:36 /tmp/con_setgid/archivo2
# ✅ El archivo hereda el grupo 'sharedfiles' del directorio padre
```

**¿Por qué es importante setgid?**
- **Sin setgid**: Cada proceso crea archivos con su grupo primario → inconsistencia
- **Con setgid**: Todos los archivos nuevos heredan el grupo del directorio → consistencia
- **Resultado**: Todos los usuarios del grupo pueden leer/escribir todos los archivos

**Identificar setgid visualmente**:
```bash
ls -ld /mnt/shared_data
# Con setgid: drwxrwsr-x (nota la 's' en lugar de 'x' en el grupo)
# Sin setgid:  drwxrwxr-x (nota la 'x' normal en el grupo)
```

---

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
# Instalar herramientas ACL (si no están instaladas)
apt-get update && apt-get install -y acl

# Ver ACL de un directorio
getfacl /mnt/shared_data
# Salida:
# file: mnt/shared_data
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
setfacl -m g:webapps:rwx /mnt/shared_data

# Dar permisos a un usuario específico  
setfacl -m u:ncp:rwx /mnt/shared_data

# Configurar permisos por defecto (se heredan en archivos nuevos)
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data

# Aplicar ACL recursivamente a todo el contenido existente
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data

# Combinar: aplicar a existente Y configurar por defecto
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data
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
# Con ACL: El grupo 'sharedfiles' siempre tiene acceso, independiente de UIDs
```

**Samba y herencia**:
- Samba puede forzar grupos, pero las ACL son más flexibles
- Las ACL por defecto aseguran herencia correcta
- Funcionan incluso si Samba no está configurado perfectamente

---

### Contenedores No Privilegiados

#### ¿Qué son los Contenedores No Privilegiados?

Los contenedores **no privilegiados** son más seguros porque:
- El usuario `root` del contenedor NO es `root` del host
- Los IDs de usuario/grupo están "desplazados"
- Limitan el daño si el contenedor es comprometido

#### Mapeo de IDs en Proxmox

En un contenedor no privilegiado típico de Proxmox:

| Contenedor | Host | Explicación |
|------------|------|-------------|
| UID 0 (root) | UID 100000 | Root del contenedor = usuario 100000 del host |
| UID 1 | UID 100001 | Usuario 1 del contenedor = usuario 100001 del host |
| UID 1000 (usuario) | UID 101000 | Usuario 1000 del contenedor = usuario 101000 del host |
| GID 0 (root) | GID 100000 | Grupo root del contenedor = grupo 100000 del host |
| GID 1000 (grupo) | GID 101000 | Grupo 1000 del contenedor = grupo 101000 del host |

#### ¿Por qué usar GID 101000?

**El GID 101000 es estratégico porque**:
- Es el **primer GID mapeado** para contenedores no privilegiados en Proxmox
- Corresponde al **GID 1000 dentro del contenedor**, que es el GID estándar para grupos de usuarios
- Garantiza **compatibilidad universal** entre contenedores privilegiados y no privilegiados
- Es **predecible** y **consistente** en todas las instalaciones de Proxmox

```bash
# En el HOST: Crear grupo con GID 101000
groupadd -g 101000 sharedfiles

# En CONTENEDOR NO PRIVILEGIADO: Crear grupo con GID 1000
groupadd -g 1000 sharedfiles
# Este GID 1000 del contenedor se mapea automáticamente al GID 101000 del host

# En CONTENEDOR PRIVILEGIADO: Crear grupo con GID 101000
groupadd -g 101000 sharedfiles
# Mismo GID que el host, sin mapeo
```

#### El Problema en la Práctica

```bash
# En el HOST: Crear archivo con grupo 'sharedfiles' (GID 101000)
echo "datos importantes" > /mnt/shared_data/archivo.txt
chgrp sharedfiles /mnt/shared_data/archivo.txt
ls -ld /mnt/shared_data/archivo.txt
# Salida: -rw-r--r-- 1 root sharedfiles 18 sep  8 archivo.txt

# En el CONTENEDOR NO PRIVILEGIADO (sin configurar): Ver el mismo archivo
pct exec 101 -- ls -ld /mnt/shared_data/archivo.txt
# Salida: -rw-r--r-- 1 nobody nogroup 18 sep  8 archivo.txt
# ❌ El contenedor ve 'nobody:nogroup' porque no conoce el GID 101000 del host

# En el CONTENEDOR NO PRIVILEGIADO (configurado): Ver el mismo archivo
pct exec 101 -- ls -ld /mnt/shared_data/archivo.txt
# Salida: -rw-r--r-- 1 root sharedfiles 18 sep  8 archivo.txt
# ✅ El contenedor reconoce el grupo porque tiene 'sharedfiles' con GID 1000 (mapeado a 101000)
```

#### ¿Por qué pasa esto?

1. **Host**: El archivo pertenece al GID 101000 (`sharedfiles`)
2. **Contenedor**: Busca qué grupo tiene GID 1000 en SU `/etc/group` (porque 101000 - 100000 = 1000)
3. **Sin configurar**: Si no existe ese GID en el contenedor, muestra `nogroup`
4. **Configurado**: Si existe el grupo `sharedfiles` con GID 1000, lo reconoce correctamente
5. **Consecuencia**: Solo con la configuración correcta el usuario del contenedor puede escribir

---

## Tipos de Recursos Compartidos

### NFS (Network File System)

#### ¿Qué es NFS?

**NFS** es un protocolo que permite montar directorios remotos como si fueran locales. Es especialmente popular en entornos Linux/Unix.

#### ¿Cómo funcionan los permisos en NFS?

**Característica clave**: NFS transmite solo **números** (UID/GID), no nombres de usuarios/grupos.

```bash
# Servidor NFS (ej: TrueNAS, Synology, servidor Linux)
# Archivo creado por usuario 'admin' (UID 1001) en grupo 'storage' (GID 2000)
-rw-rw-r-- 1 admin storage 1024 sep  8 archivo.txt

# Cliente NFS (Proxmox host)
# NFS transmite: UID=1001, GID=2000
# Proxmox busca en su /etc/passwd y /etc/group:
# - ¿Existe UID 1001? Si no → muestra número o 'nobody'
# - ¿Existe GID 2000? Si no → muestra número o 'nogroup'

# Resultado típico en Proxmox:
-rw-rw-r-- 1 1001 2000 1024 sep  8 archivo.txt
# o
-rw-rw-r-- 1 nobody nogroup 1024 sep  8 archivo.txt
```

#### Problemas comunes con permisos NFS

**Problema 1: UIDs/GIDs diferentes**
```bash
# Servidor NFS: usuario 'web' = UID 500
# Cliente: usuario 'web' = UID 1000
# Resultado: El cliente no puede acceder a archivos del servidor
```

**Problema 2: Usuarios inexistentes**
```bash
# Servidor: archivo creado por UID 1500 (usuario 'app')
# Cliente: no existe UID 1500
# Resultado: archivo aparece como 'nobody' y no es accesible
```

**Solución: Grupo universal + ACL**
```bash
# En lugar de depender de UIDs específicos, usar un grupo común:
# 1. Crear grupo 'sharedfiles' con GID 101000 en host y contenedores
# 2. Aplicar ACL para dar permisos al grupo
# 3. Todos los usuarios relevantes pertenecen al grupo
# Resultado: Funciona independientemente de los UIDs individuales
```

#### Configuración típica de servidores NFS

**TrueNAS/FreeNAS**:
- Crear dataset con permisos Unix
- Configurar servicio NFS
- Definir redes permitidas
- Los permisos se basan en UID/GID numéricos

**Synology**:
- Crear carpeta compartida
- Habilitar servicio NFS
- Configurar permisos de acceso
- Mapear usuarios si es necesario

**Servidor Linux**:
```bash
# /etc/exports
/export/data 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
```

---

### Samba/CIFS

#### ¿Qué es Samba?

**Samba** implementa el protocolo SMB/CIFS, permitiendo que sistemas Linux compartan archivos con Windows y otros sistemas.

#### ¿Cómo funcionan los permisos en Samba?

Samba tiene **dos capas de permisos**:

1. **Permisos de Samba** (definidos en smb.conf)
2. **Permisos del sistema de archivos** (permisos Unix tradicionales + ACL)

```bash
# Ejemplo de configuración Samba
[shared_data]
    path = /srv/samba/shared
    browseable = yes
    read only = no
    valid users = @storage_users
    force group = storage_users
    create mask = 0664
    directory mask = 2775
```

#### Diferencias con NFS

| Aspecto | NFS | Samba |
|---------|-----|-------|
| **Autenticación** | Basada en IP/red | Usuario/contraseña |
| **Permisos** | Solo UID/GID numéricos | Mapeo de usuarios + permisos Unix |
| **Herencia** | Depende del sistema de archivos | Configurable (force group, masks) |
| **Compatibilidad** | Linux/Unix nativo | Multiplataforma (Windows, Linux, macOS) |

#### Configuración típica de servidores Samba

**Servidor Linux con Samba**:
```bash
# /etc/samba/smb.conf
[global]
    workgroup = WORKGROUP
    security = user
    map to guest = bad user

[shared]
    path = /srv/samba/shared
    valid users = @sharedfiles
    force group = sharedfiles
    create mask = 0664
    directory mask = 2775
    read only = no
```

**NAS (Synology, QNAP, etc.)**:
- Crear carpeta compartida
- Configurar usuarios y grupos
- Habilitar SMB/CIFS
- Definir permisos por usuario/grupo

---

### Directorios Locales

#### ¿Qué son los directorios locales?

Son carpetas que existen directamente en el host de Proxmox, sin involucrar protocolos de red.

#### Ventajas

- **Rendimiento máximo** (sin overhead de red)
- **Simplicidad** (sin configuración de red)
- **Control total** sobre permisos
- **Ideal para datos críticos** o de alta frecuencia de acceso

#### Casos de uso típicos

```bash
# Logs centralizados
/var/log/containers/

# Configuraciones compartidas
/etc/shared-configs/

# Datos de aplicaciones
/opt/app-data/

# Backups locales
/backup/containers/
```

---

## Configuración Paso a Paso

### Preparación del Host

#### Paso 1: Instalar herramientas necesarias

```bash
# Actualizar sistema
apt-get update

# Instalar herramientas ACL
apt-get install -y acl

# Instalar cliente NFS (si vas a usar NFS)
apt-get install -y nfs-common

# Instalar cliente Samba (si vas a usar Samba)
apt-get install -y cifs-utils

# Verificar instalación
which setfacl getfacl mount.nfs mount.cifs
```

#### Paso 2: Crear grupo universal

```bash
# Crear grupo con GID específico para compatibilidad universal
groupadd -g 101000 sharedfiles

# Verificar creación
getent group sharedfiles
# Salida: sharedfiles:x:101000:

# Añadir usuario root al grupo (opcional, para pruebas)
usermod -aG sharedfiles root
```

**¿Por qué GID 101000?**
- Es el primer GID mapeado en contenedores no privilegiados de Proxmox
- Corresponde al GID 1000 dentro del contenedor (GID estándar de usuarios)
- Garantiza compatibilidad entre contenedores privilegiados y no privilegiados
- Es predecible y consistente en todas las instalaciones

---

### Montar Recursos Compartidos

#### Opción A: Montar recurso NFS

```bash
# Crear punto de montaje
mkdir -p /mnt/nfs_share

# Montar temporalmente para probar
mount -t nfs 192.168.1.100:/export/data /mnt/nfs_share

# Verificar montaje
df -h | grep nfs_share
# Salida: 192.168.1.100:/export/data  100G   50G   50G  50% /mnt/nfs_share

# Ver permisos originales
ls -ld /mnt/nfs_share
# Salida típica: drwxr-xr-x 2 1001 1001 4096 sep  8 /mnt/nfs_share
```

**Hacer montaje persistente**:
```bash
# Editar /etc/fstab
echo "192.168.1.100:/export/data /mnt/nfs_share nfs rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev 0 0" >> /etc/fstab

# Verificar sintaxis
mount -a

# Comprobar que funciona tras reinicio
systemctl reboot
# Tras reinicio:
df -h | grep nfs_share
```

**Explicación de opciones NFS**:
- `rw`: Lectura y escritura
- `hard`: Reintentar indefinidamente si el servidor no responde
- `nofail`: No fallar el arranque si no se puede montar
- `rsize/wsize=131072`: Tamaño de buffer para mejor rendimiento
- `timeo=600`: Timeout de 60 segundos
- `retrans=2`: Reintentar 2 veces antes de reportar error
- `_netdev`: Esperar a que la red esté lista
- `0 0`: No hacer dump ni fsck (siempre para recursos de red)

#### Opción B: Montar recurso Samba

```bash
# Crear punto de montaje
mkdir -p /mnt/samba_share

# Crear archivo de credenciales
cat > /etc/cifs-credentials << EOF
username=tu_usuario
password=tu_password
domain=tu_dominio
EOF

# Proteger archivo de credenciales
chmod 600 /etc/cifs-credentials

# Montar temporalmente para probar
mount -t cifs //192.168.1.200/shared /mnt/samba_share -o credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0

# Verificar montaje
df -h | grep samba_share
# Salida: //192.168.1.200/shared  500G  200G  300G  40% /mnt/samba_share

# Ver permisos originales
ls -ld /mnt/samba_share
```

**Hacer montaje persistente**:
```bash
# Editar /etc/fstab
echo "//192.168.1.200/shared /mnt/samba_share cifs credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0,_netdev,nofail 0 0" >> /etc/fstab

# Verificar sintaxis
mount -a
```

**Explicación de opciones Samba**:
- `credentials=`: Archivo con usuario/contraseña
- `iocharset=utf8`: Codificación de caracteres
- `vers=3.0`: Versión del protocolo SMB
- `_netdev`: Esperar a que la red esté lista
- `nofail`: No fallar el arranque si no se puede montar

#### Opción C: Crear directorio local

```bash
# Crear directorio local
mkdir -p /mnt/local_share

# Ver permisos iniciales
ls -ld /mnt/local_share
# Salida: drwxr-xr-x 2 root root 4096 sep  8 /mnt/local_share
```

---

### Configurar Permisos Universales

**Independientemente del tipo de recurso (NFS, Samba, local), aplicar la misma configuración**:

```bash
# Ejemplo con /mnt/shared_data (cambiar por tu ruta)
SHARED_DIR="/mnt/shared_data"

# Paso 1: Asignar propietario y grupo
chown root:sharedfiles "$SHARED_DIR"

# Paso 2: Aplicar permisos con setgid
chmod 2775 "$SHARED_DIR"

# Paso 3: Verificar setgid (debe aparecer 's' en lugar de 'x' para el grupo)
ls -ld "$SHARED_DIR"
# Salida esperada: drwxrwsr-x 2 root sharedfiles 4096 sep  8 /mnt/shared_data
#                              ↑ Esta 's' indica setgid activo

# Paso 4: Aplicar ACL para contenido existente
setfacl -R -m g:sharedfiles:rwx "$SHARED_DIR"

# Paso 5: Configurar ACL por defecto para archivos nuevos
setfacl -d -m g:sharedfiles:rwx "$SHARED_DIR"

# Paso 6: Verificar ACL
getfacl "$SHARED_DIR"
# Salida esperada:
# file: mnt/shared_data
# owner: root
# group: sharedfiles
# user::rwx
# group::rwx
# other::r-x
# default:user::rwx
# default:group::rwx
# default:other::r-x
```

**¿Por qué esta configuración funciona universalmente?**
- **chown root:sharedfiles**: Establece un propietario conocido y el grupo universal
- **chmod 2775**: Da permisos completos al propietario y grupo, y activa setgid
- **setgid (el '2' en 2775)**: Asegura que todos los archivos nuevos hereden el grupo `sharedfiles`
- **ACL recursiva (-R)**: Corrige permisos de archivos/directorios existentes
- **ACL por defecto (-d)**: Asegura que archivos nuevos tengan permisos correctos

---

### Configurar Contenedores

#### Contenedores Privilegiados

Los contenedores privilegiados comparten los mismos UIDs/GIDs que el host, por lo que la configuración es más simple:

```bash
# Entrar al contenedor privilegiado (ejemplo: ID 100)
pct exec 100 -- bash

# Crear grupo idéntico al host
groupadd -g 101000 sharedfiles

# Añadir usuarios relevantes al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Si tienes Nextcloud u otras aplicaciones
usermod -aG sharedfiles ncp 2>/dev/null || true

# Verificar membresía
groups root
# Salida: root : root sharedfiles

groups www-data
# Salida: www-data : www-data sharedfiles

# Salir del contenedor
exit
```

**Nota importante**: En contenedores privilegiados, técnicamente no es estrictamente necesario añadir usuarios al grupo si solo el propietario (root) va a escribir archivos. Sin embargo, es una buena práctica porque:
- **Consistencia**: Mantiene la misma configuración en todos los contenedores
- **Flexibilidad**: Permite que servicios web (www-data) o aplicaciones (ncp) escriban directamente
- **Futuro**: Si cambias permisos o añades servicios, ya está configurado
- **Depuración**: Es más fácil diagnosticar problemas cuando la configuración es uniforme

#### Contenedores No Privilegiados

Los contenedores no privilegiados requieren mapeo de IDs, por lo que necesitan configuración específica:

```bash
# Entrar al contenedor no privilegiado (ejemplo: ID 101)
pct exec 101 -- bash

# Crear grupo con GID mapeado
groupadd -g 1000 sharedfiles
# Importante: GID 1000 en contenedor = GID 101000 en host

# Listar usuarios disponibles en el contenedor
awk -F: '$3>=1000 && $1!="nobody"{print $1 " (UID: " $3 ")"}' /etc/passwd
# Salida ejemplo:
# ncp (UID: 1000)
# www-data (UID: 33)

# Añadir usuarios al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Ejemplo específico: añadir usuario de Nextcloud
usermod -aG sharedfiles ncp 2>/dev/null || true

# Verificar configuración completa
id www-data
# Salida esperada: uid=33(www-data) gid=33(www-data) groups=33(www-data),1000(sharedfiles)

id ncp 2>/dev/null || echo "Usuario ncp no existe"
# Si existe: uid=1000(ncp) gid=1000(ncp) groups=1000(ncp),1000(sharedfiles)

# Salir del contenedor
exit
```

**¿Cómo añadir más usuarios?**

Si necesitas añadir usuarios adicionales (por ejemplo, para otras aplicaciones):

```bash
# Dentro del contenedor no privilegiado
pct exec 101 -- bash

# Ver todos los usuarios del sistema
cat /etc/passwd | grep -v nologin | grep -v false | awk -F: '{print $1 " (UID: " $3 ")"}'

# Añadir usuarios específicos
usermod -aG sharedfiles usuario1
usermod -aG sharedfiles usuario2

# Para añadir TODOS los usuarios con UID >= 1000 automáticamente:
for user in $(awk -F: '$3>=1000 && $1!="nobody"{print $1}' /etc/passwd); do
    usermod -aG sharedfiles "$user" 2>/dev/null || true
    echo "Añadido usuario: $user"
done

# Verificar todos los usuarios añadidos
getent group sharedfiles
# Salida: sharedfiles:x:1000:root,www-data,ncp,usuario1,usuario2

exit
```

---

### Crear Puntos de Montaje

#### Configurar montajes en contenedores

```bash
# Para contenedor privilegiado (ID 100)
pct set 100 -mp0 /mnt/shared_data,mp=/mnt/shared,shared=1,backup=0,acl=1

# Para contenedor no privilegiado (ID 101)  
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,shared=1,backup=0,acl=1

# Reiniciar contenedores para activar montajes
pct reboot 100
pct reboot 101

# Esperar a que arranquen
sleep 15

# Verificar que los montajes están activos
pct exec 100 -- df -h | grep shared
pct exec 101 -- df -h | grep shared
```

**Explicación de parámetros**:
- `mp0`: Primer punto de montaje (mp1, mp2, etc. para adicionales)
- `/mnt/shared_data`: Ruta en el host
- `mp=/mnt/shared`: Ruta dentro del contenedor
- `shared=1`: **Esencial para clusters** - permite migración sin copiar datos
- `backup=0`: Excluye del backup de vzdump (evita duplicar datos)
- `acl=1`: Habilita soporte ACL dentro del contenedor

**¿Por qué shared=1 es importante?**
- Sin `shared=1`: Proxmox copia todos los datos al migrar el contenedor
- Con `shared=1`: Proxmox asume que los datos están disponibles en todos los nodos
- **Resultado**: Migraciones rápidas y sin duplicar almacenamiento

---

## Verificación y Pruebas

### Prueba básica de funcionamiento

```bash
# Desde el HOST: Crear archivo de prueba
echo "Archivo creado desde el host" > /mnt/shared_data/test_host.txt
ls -ld /mnt/shared_data/test_host.txt
# Salida esperada: -rw-r--r-- 1 root sharedfiles 29 sep  8 test_host.txt

# Desde CONTENEDOR PRIVILEGIADO: Crear archivo
pct exec 100 -- bash -c 'echo "Archivo desde contenedor privilegiado" > /mnt/shared/test_privileged.txt'
pct exec 100 -- ls -ld /mnt/shared/test_privileged.txt
# Salida esperada: -rw-r--r-- 1 root sharedfiles 35 sep  8 test_privileged.txt

# Desde CONTENEDOR NO PRIVILEGIADO: Crear archivo
pct exec 101 -- bash -c 'echo "Archivo desde contenedor no privilegiado" > /mnt/shared/test_unprivileged.txt'
pct exec 101 -- ls -ld /mnt/shared/test_unprivileged.txt
# Salida esperada: -rw-r--r-- 1 root sharedfiles 38 sep  8 test_unprivileged.txt

# Verificar desde el HOST que todos los archivos son accesibles
ls -ld /mnt/shared_data/test_*.txt
# Todos deben mostrar grupo 'sharedfiles' y ser legibles
```

### Prueba de escritura cruzada

```bash
# Desde HOST: Modificar archivo creado por contenedor
echo "Modificado desde host" >> /mnt/shared_data/test_privileged.txt

# Desde CONTENEDOR PRIVILEGIADO: Modificar archivo creado por host
pct exec 100 -- bash -c 'echo "Modificado desde privilegiado" >> /mnt/shared/test_host.txt'

# Desde CONTENEDOR NO PRIVILEGIADO: Modificar archivo creado por privilegiado
pct exec 101 -- bash -c 'echo "Modificado desde no privilegiado" >> /mnt/shared/test_privileged.txt'

# Verificar que todas las modificaciones funcionaron
cat /mnt/shared_data/test_host.txt
cat /mnt/shared_data/test_privileged.txt
```

### Verificar herencia de permisos

```bash
# Crear subdirectorio desde contenedor no privilegiado
pct exec 101 -- mkdir -p /mnt/shared/subdir_test

# Verificar que hereda el grupo correcto
ls -ld /mnt/shared_data/subdir_test
# Salida esperada: drwxrwsr-x 2 root sharedfiles 4096 sep  8 subdir_test
#                              ↑ La 's' indica que setgid se heredó

# Crear archivo dentro del subdirectorio
pct exec 101 -- bash -c 'echo "test herencia" > /mnt/shared/subdir_test/archivo.txt'

# Verificar herencia de grupo
ls -ld /mnt/shared_data/subdir_test/archivo.txt
# Salida esperada: -rw-r--r-- 1 root sharedfiles 14 sep  8 archivo.txt
```

---

## Solución de Problemas

### Error: "Permission denied" al escribir

**Síntomas**:
```bash
pct exec 101 -- bash -c 'echo "test" > /mnt/shared/test.txt'
# bash: /mnt/shared/test.txt: Permission denied
```

**Diagnóstico**:
```bash
# 1. Verificar permisos del directorio
ls -ld /mnt/shared_data
# ¿Tiene permisos de escritura para el grupo? ¿Está activo setgid?

# 2. Verificar grupo en el contenedor
pct exec 101 -- getent group sharedfiles
# ¿Existe el grupo? ¿Tiene el GID correcto?

# 3. Verificar membresía del usuario
pct exec 101 -- groups root
# ¿El usuario pertenece al grupo sharedfiles?

# 4. Verificar ACL
getfacl /mnt/shared_data
# ¿Están configuradas las ACL para el grupo?
```

**Soluciones**:
```bash
# Solución 1: Reconfigurar permisos básicos
chmod 2775 /mnt/shared_data
chgrp sharedfiles /mnt/shared_data

# Solución 2: Recrear grupo en contenedor
pct exec 101 -- groupadd -g 1000 sharedfiles
pct exec 101 -- usermod -aG sharedfiles root

# Solución 3: Reconfigurar ACL
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data

# Solución 4: Reiniciar contenedor
pct reboot 101
```

### Error: Archivos aparecen como "nobody:nogroup"

**Síntomas**:
```bash
pct exec 101 -- ls -ld /mnt/shared/archivo.txt
# -rw-r--r-- 1 nobody nogroup 100 sep  8 archivo.txt
```

**Causa**: El contenedor no reconoce los UIDs/GIDs del host.

**Solución**:
```bash
# Crear grupo con GID correcto en el contenedor
pct exec 101 -- groupadd -g 1000 sharedfiles

# Si el problema persiste, verificar mapeo
pct exec 101 -- cat /proc/self/uid_map
pct exec 101 -- cat /proc/self/gid_map
```

### Error: Montaje NFS falla

**Síntomas**:
```bash
mount -t nfs 192.168.1.100:/export/data /mnt/nfs_share
# mount.nfs: Connection refused
```

**Diagnóstico**:
```bash
# 1. Verificar conectividad
ping 192.168.1.100

# 2. Verificar servicio NFS en el servidor
showmount -e 192.168.1.100

# 3. Verificar puertos
nmap -p 111,2049 192.168.1.100

# 4. Verificar logs
journalctl -u nfs-client -f
```

**Soluciones**:
```bash
# Instalar cliente NFS si no está
apt-get install -y nfs-common

# Reiniciar servicios NFS
systemctl restart nfs-client.target

# Probar con opciones específicas
mount -t nfs -o vers=3 192.168.1.100:/export/data /mnt/nfs_share
```

### Error: Montaje Samba falla

**Síntomas**:
```bash
mount -t cifs //192.168.1.200/shared /mnt/samba_share
# mount error(13): Permission denied
```

**Diagnóstico**:
```bash
# 1. Verificar credenciales
cat /etc/cifs-credentials

# 2. Probar conexión manual
smbclient -L //192.168.1.200 -U usuario

# 3. Verificar versión SMB
mount -t cifs //192.168.1.200/shared /mnt/samba_share -o vers=1.0,username=usuario
```

**Soluciones**:
```bash
# Instalar cliente Samba si no está
apt-get install -y cifs-utils

# Probar diferentes versiones SMB
mount -t cifs //192.168.1.200/shared /mnt/samba_share -o vers=3.0,credentials=/etc/cifs-credentials

# Verificar y corregir credenciales
chmod 600 /etc/cifs-credentials
```

### Error: Contenedor no arranca tras añadir montaje

**Síntomas**:
```bash
pct start 101
# TASK ERROR: startup for container '101' failed
```

**Diagnóstico**:
```bash
# Ver configuración del contenedor
cat /etc/pve/lxc/101.conf | grep mp

# Ver logs del contenedor
journalctl -u pve-container@101 -f
```

**Soluciones**:
```bash
# Verificar que la ruta del host existe
ls -ld /mnt/shared_data

# Corregir configuración si es necesaria
pct set 101 -delete mp0
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,shared=1,backup=0,acl=1

# Arrancar contenedor
pct start 101
```

---

## Mejores Prácticas

### Organización de directorios

```bash
# Estructura recomendada
/mnt/
├── nfs_shares/
│   ├── documents/
│   ├── media/
│   └── backups/
├── samba_shares/
│   ├── public/
│   └── private/
└── local_shares/
    ├── configs/
    ├── logs/
    └── data/
```

### Nomenclatura consistente

```bash
# Usar nombres descriptivos y consistentes
/mnt/nfs_documents     # En lugar de /mnt/share1
/mnt/samba_public      # En lugar de /mnt/smb
/mnt/local_configs     # En lugar de /mnt/data
```

### Seguridad

```bash
# Limitar permisos de "otros"
chmod 2770 /mnt/sensitive_data  # Sin acceso para "otros"

# Usar ACL específicas para datos sensibles
setfacl -m u:admin:rwx /mnt/sensitive_data
setfacl -m g:admins:rwx /mnt/sensitive_data
setfacl -m other::--- /mnt/sensitive_data  # Sin acceso para otros
```

### Monitoreo

```bash
# Script para verificar montajes
#!/bin/bash
for mount in /mnt/nfs_* /mnt/samba_* /mnt/local_*; do
    if mountpoint -q "$mount"; then
        echo "✅ $mount está montado"
    else
        echo "❌ $mount NO está montado"
    fi
done

# Verificar permisos
for dir in /mnt/*/; do
    if [[ $(stat -c %G "$dir") == "sharedfiles" ]]; then
        echo "✅ $dir tiene grupo correcto"
    else
        echo "❌ $dir tiene grupo incorrecto: $(stat -c %G "$dir")"
    fi
done
```

### Backup y recuperación

```bash
# Backup de configuraciones
cp /etc/fstab /etc/fstab.backup
cp /etc/cifs-credentials /etc/cifs-credentials.backup

# Backup de configuraciones de contenedores
cp /etc/pve/lxc/*.conf /backup/lxc-configs/

# Script de restauración rápida
#!/bin/bash
# restore_mounts.sh
systemctl stop pve-container@*
mount -a
systemctl start pve-container@*
```

---

## Resumen Final

### Puntos clave para recordar

1. **Grupo universal**: Usar `sharedfiles` con GID 101000 en host, GID 1000 en contenedores no privilegiados
2. **Setgid**: Siempre usar `chmod 2775` para herencia automática de grupo
3. **ACL**: Aplicar tanto recursivamente (-R) como por defecto (-d)
4. **Montajes**: Usar `shared=1,backup=0,acl=1` en configuraciones de contenedores
5. **Persistencia**: Configurar `/etc/fstab` con opciones `_netdev,nofail,0 0`

### Comando de verificación rápida

```bash
# Ejecutar para verificar configuración completa
#!/bin/bash
echo "=== Verificación de configuración ==="
echo "1. Grupo sharedfiles en host:"
getent group sharedfiles

echo "2. Permisos del directorio compartido:"
ls -ld /mnt/shared_data

echo "3. ACL configuradas:"
getfacl /mnt/shared_data | grep -E "(group:sharedfiles|default:group:sharedfiles)"

echo "4. Montajes en contenedores:"
pct exec 100 -- df -h | grep shared 2>/dev/null || echo "Contenedor 100 no disponible"
pct exec 101 -- df -h | grep shared 2>/dev/null || echo "Contenedor 101 no disponible"

echo "5. Grupos en contenedores:"
pct exec 100 -- getent group sharedfiles 2>/dev/null || echo "Grupo no configurado en contenedor 100"
pct exec 101 -- getent group sharedfiles 2>/dev/null || echo "Grupo no configurado en contenedor 101"

echo "=== Verificación completada ==="
```

Con esta configuración, tendrás un sistema robusto y flexible para compartir recursos entre Proxmox y contenedores LXC, con permisos correctos y persistencia tras reinicios.
```

