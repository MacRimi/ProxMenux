# 📘 Guía Completa: Compartir Recursos entre Proxmox Host y Contenedores LXC

## 📋 Índice

1. [Conceptos Fundamentales](#1-conceptos-fundamentales)
2. [Preparación del Host Proxmox](#2-preparación-del-host-proxmox)
3. [Tipos de Recursos Compartidos](#3-tipos-de-recursos-compartidos)
4. [Configuración de Contenedores](#4-configuración-de-contenedores)
5. [Montaje en Contenedores](#5-montaje-en-contenedores)
6. [Verificación y Pruebas](#6-verificación-y-pruebas)
7. [Solución de Problemas](#7-solución-de-problemas)
8. [Comandos de Referencia Rápida](#8-comandos-de-referencia-rápida)

---

## 1. Conceptos Fundamentales

### ¿Qué son los Usuarios y Grupos en Linux?

En Linux, cada archivo y proceso pertenece a un **usuario** y un **grupo**:

```bash
# Ver información de un archivo
ls -l /mnt/shared/archivo.txt
# Salida: -rw-rw-r-- 1 root sharedfiles 1024 dic 8 archivo.txt
#         ↑permisos  ↑usuario ↑grupo    ↑tamaño
```

**Explicación de permisos:**
- `rw-` = Usuario propietario: lectura y escritura
- `rw-` = Grupo propietario: lectura y escritura  
- `r--` = Otros usuarios: solo lectura

### ¿Qué son las ACLs (Access Control Lists)?

Las **ACLs** son permisos extendidos que van más allá del sistema tradicional usuario/grupo/otros:

```bash
# Ver ACLs de un directorio
getfacl /mnt/shared
# Salida:
# user::rwx
# group::rwx
# group:sharedfiles:rwx    ← ACL específica para el grupo
# mask::rwx
# other::r-x
# default:user::rwx        ← Permisos por defecto para nuevos archivos
# default:group::rwx
# default:group:sharedfiles:rwx
# default:mask::rwx
# default:other::r-x
```

### ¿Por qué son importantes los Grupos en Proxmox?

Los **contenedores no privilegiados** usan un mapeo de IDs:
- Usuario `root` (UID 0) en el contenedor = UID 100000 en el host
- Usuario `www-data` (UID 33) en el contenedor = UID 100033 en el host

**El problema:** Si un archivo pertenece al UID 1000 en el host, el contenedor lo ve como UID 101000 (inexistente).

**La solución:** Usar un **grupo común** con **ACLs** que garanticen permisos independientemente del UID.

---

## 2. Preparación del Host Proxmox

### Paso 1: Crear Grupo Universal

```bash
# Crear grupo que usarán todos los recursos compartidos
groupadd -g 101000 sharedfiles

# Verificar que se creó correctamente
getent group sharedfiles
# Salida: sharedfiles:x:101000:
```

**¿Por qué GID 101000?**
- Es el primer GID mapeado de contenedores no privilegiados
- Garantiza compatibilidad entre host y contenedores

### Paso 2: Instalar Herramientas Necesarias

```bash
# Instalar herramientas para ACLs
apt update
apt install -y acl

# Para recursos NFS
apt install -y nfs-common

# Para recursos Samba/CIFS
apt install -y cifs-utils
```

---

## 3. Tipos de Recursos Compartidos

### A) Directorio Local del Host

**Cuándo usar:** Para almacenamiento compartido simple entre contenedores del mismo host.

```bash
# 1. Crear directorio
mkdir -p /mnt/local_shared

# 2. Configurar propietario y permisos
chown root:sharedfiles /mnt/local_shared
chmod 2775 /mnt/local_shared

# 3. Aplicar ACLs
setfacl -R -m g:sharedfiles:rwx /mnt/local_shared
setfacl -d -m g:sharedfiles:rwx /mnt/local_shared

# 4. Verificar configuración
ls -ld /mnt/local_shared
# Salida: drwxrwsr-x+ 2 root sharedfiles 4096 dic 8 /mnt/local_shared
#         ↑ La 's' indica setgid activo
#         ↑ El '+' indica ACLs aplicadas
```

**Explicación de permisos 2775:**
- `2` = setgid (nuevos archivos heredan el grupo)
- `7` = rwx para el propietario (root)
- `7` = rwx para el grupo (sharedfiles)
- `5` = r-x para otros

### B) Recurso NFS Remoto

**Cuándo usar:** Para acceder a un servidor NFS existente en la red.

```bash
# 1. Crear punto de montaje
mkdir -p /mnt/nfs_shared

# 2. Montar temporalmente para probar
mount -t nfs 192.168.1.100:/export/data /mnt/nfs_shared

# 3. Verificar que funciona
ls -la /mnt/nfs_shared

# 4. Si funciona, hacer persistente en /etc/fstab
echo "192.168.1.100:/export/data /mnt/nfs_shared nfs rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev 0 0" >> /etc/fstab

# 5. Configurar permisos locales
chown root:sharedfiles /mnt/nfs_shared
chmod 2775 /mnt/nfs_shared
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_shared
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_shared

# 6. Probar montaje persistente
umount /mnt/nfs_shared
mount -a
```

**Explicación de opciones NFS:**
- `rw` = lectura y escritura
- `hard` = reintentar indefinidamente si el servidor no responde
- `nofail` = no bloquear el arranque si no está disponible
- `rsize/wsize=131072` = tamaño de buffer para mejor rendimiento
- `timeo=600` = timeout de 60 segundos
- `retrans=2` = reintentar 2 veces antes de reportar error
- `_netdev` = esperar a que la red esté lista
- `0 0` = no hacer dump ni fsck (siempre para recursos de red)

### C) Recurso Samba/CIFS

**Cuándo usar:** Para acceder a recursos compartidos de Windows o servidores Samba.

```bash
# 1. Crear archivo de credenciales seguro
cat > /etc/cifs-credentials << EOF
username=tu_usuario
password=tu_password
domain=tu_dominio
EOF

# 2. Proteger el archivo
chmod 600 /etc/cifs-credentials

# 3. Crear punto de montaje
mkdir -p /mnt/samba_shared

# 4. Montar temporalmente para probar
mount -t cifs //192.168.1.200/shared /mnt/samba_shared -o credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0

# 5. Verificar que funciona
ls -la /mnt/samba_shared

# 6. Si funciona, hacer persistente en /etc/fstab
echo "//192.168.1.200/shared /mnt/samba_shared cifs credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0,_netdev,nofail 0 0" >> /etc/fstab

# 7. Configurar permisos locales
chown root:sharedfiles /mnt/samba_shared
chmod 2775 /mnt/samba_shared
setfacl -R -m g:sharedfiles:rwx /mnt/samba_shared
setfacl -d -m g:sharedfiles:rwx /mnt/samba_shared

# 8. Probar montaje persistente
umount /mnt/samba_shared
mount -a
```

**Explicación de opciones CIFS:**
- `credentials=` = archivo con usuario/password
- `iocharset=utf8` = codificación de caracteres
- `vers=3.0` = versión del protocolo SMB
- `_netdev` = esperar a que la red esté lista
- `nofail` = no bloquear el arranque si no está disponible

---

## 4. Configuración de Contenedores

### Contenedor Privilegiado (Ejemplo: ID 100)

**¿Necesita configuración especial?**
En teoría no, porque los UIDs/GIDs son idénticos al host. Sin embargo, **es recomendable** crear el grupo para consistencia:

```bash
# 1. Entrar al contenedor
pct exec 100 -- bash

# 2. Crear grupo idéntico al host
groupadd -g 101000 sharedfiles

# 3. Añadir usuarios relevantes al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Si tienes otros usuarios específicos de aplicaciones:
usermod -aG sharedfiles ncp 2>/dev/null || true  # Nextcloud
usermod -aG sharedfiles mysql 2>/dev/null || true  # MySQL

# 4. Verificar membresía
groups root
groups www-data

# 5. Salir del contenedor
exit
```

**¿Por qué hacerlo aunque no sea estrictamente necesario?**
- **Consistencia:** Mismo comportamiento en privilegiados y no privilegiados
- **Migración:** Si conviertes el contenedor a no privilegiado, ya está configurado
- **Claridad:** Es evidente qué usuarios tienen acceso al recurso compartido

### Contenedor No Privilegiado (Ejemplo: ID 101)

**Aquí SÍ es obligatorio** configurar el grupo:

```bash
# 1. Entrar al contenedor
pct exec 101 -- bash

# 2. Crear grupo con GID mapeado
groupadd -g 1000 sharedfiles
# Importante: GID 1000 en contenedor = GID 101000 en host

# 3. Listar todos los usuarios disponibles
awk -F: '$3>=1000 && $1!="nobody" {print $1 " (UID: " $3 ")"}' /etc/passwd
# O más simple, solo los nombres:
awk -F: '$3>=1000 && $1!="nobody" {print $1}' /etc/passwd

# 4. Añadir usuarios al grupo (ajusta según tu contenedor)
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Para aplicaciones específicas:
usermod -aG sharedfiles ncp 2>/dev/null || true      # Nextcloud
usermod -aG sharedfiles mysql 2>/dev/null || true    # MySQL
usermod -aG sharedfiles postgres 2>/dev/null || true # PostgreSQL
usermod -aG sharedfiles redis 2>/dev/null || true    # Redis

# 5. Verificar configuración
id www-data
# Salida esperada: uid=33(www-data) gid=33(www-data) groups=33(www-data),1000(sharedfiles)

# 6. Salir del contenedor
exit
```

**¿Cómo añadir TODOS los usuarios automáticamente?**

```bash
# Dentro del contenedor no privilegiado:
# Obtener lista de usuarios y añadirlos al grupo
for user in $(awk -F: '$3>=1000 && $1!="nobody" {print $1}' /etc/passwd); do
    usermod -aG sharedfiles "$user"
    echo "Usuario $user añadido al grupo sharedfiles"
done

# Verificar resultado
getent group sharedfiles
```

---

## 5. Montaje en Contenedores

### Configurar Puntos de Montaje

```bash
# Para contenedor privilegiado (ID 100)
pct set 100 -mp0 /mnt/local_shared,mp=/mnt/shared,backup=0,acl=1,shared=1

# Para contenedor no privilegiado (ID 101)  
pct set 101 -mp0 /mnt/local_shared,mp=/mnt/shared,backup=0,acl=1,shared=1

# Si tienes múltiples recursos:
pct set 101 -mp1 /mnt/nfs_shared,mp=/mnt/nfs,backup=0,acl=1,shared=1
pct set 101 -mp2 /mnt/samba_shared,mp=/mnt/samba,backup=0,acl=1,shared=1
```

**Explicación de parámetros:**
- `mp0` = identificador del punto de montaje (mp0, mp1, mp2...)
- `/mnt/local_shared` = ruta en el host
- `mp=/mnt/shared` = ruta dentro del contenedor
- `backup=0` = excluir del backup de vzdump (recomendado para recursos de red)
- `acl=1` = habilitar soporte para ACLs dentro del contenedor
- `shared=1` = **IMPORTANTE** para clusters - permite migración sin copiar datos

### Aplicar Cambios

```bash
# Reiniciar contenedores para activar montajes
pct reboot 100
pct reboot 101

# Esperar a que arranquen completamente
sleep 15

# Verificar que están funcionando
pct status 100
pct status 101
```

---

## 6. Verificación y Pruebas

### Prueba Básica de Escritura

```bash
# 1. Crear archivo desde el host
echo "Archivo creado desde el host" > /mnt/local_shared/test_host.txt

# 2. Verificar permisos en el host
ls -l /mnt/local_shared/test_host.txt
getfacl /mnt/local_shared/test_host.txt

# 3. Probar desde contenedor privilegiado
pct exec 100 -- bash -c "echo 'Desde contenedor privilegiado' > /mnt/shared/test_privileged.txt"

# 4. Probar desde contenedor no privilegiado
pct exec 101 -- bash -c "echo 'Desde contenedor no privilegiado' > /mnt/shared/test_unprivileged.txt"

# 5. Verificar todos los archivos desde el host
ls -la /mnt/local_shared/
getfacl /mnt/local_shared/test_*
```

**Resultado esperado:**
```bash
# Todos los archivos deben tener:
-rw-rw-r--+ 1 root sharedfiles [tamaño] [fecha] archivo.txt
#         ↑ El '+' confirma que las ACLs están activas
```

### Prueba de Acceso Cruzado

```bash
# 1. Desde contenedor privilegiado, leer archivo del no privilegiado
pct exec 100 -- cat /mnt/shared/test_unprivileged.txt

# 2. Desde contenedor no privilegiado, leer archivo del privilegiado
pct exec 101 -- cat /mnt/shared/test_privileged.txt

# 3. Modificar archivos cruzados
pct exec 100 -- bash -c "echo 'Modificado por privilegiado' >> /mnt/shared/test_unprivileged.txt"
pct exec 101 -- bash -c "echo 'Modificado por no privilegiado' >> /mnt/shared/test_privileged.txt"

# 4. Verificar contenido final
cat /mnt/local_shared/test_unprivileged.txt
cat /mnt/local_shared/test_privileged.txt
```

### Verificar Herencia de Permisos

```bash
# 1. Crear subdirectorio desde contenedor
pct exec 101 -- mkdir /mnt/shared/subdir_test

# 2. Crear archivo en subdirectorio
pct exec 101 -- bash -c "echo 'Archivo en subdirectorio' > /mnt/shared/subdir_test/archivo.txt"

# 3. Verificar herencia desde el host
ls -ld /mnt/local_shared/subdir_test
ls -l /mnt/local_shared/subdir_test/archivo.txt
getfacl /mnt/local_shared/subdir_test
```

**Resultado esperado:**
- El subdirectorio debe tener grupo `sharedfiles`
- El archivo debe tener grupo `sharedfiles`
- Las ACLs deben estar presentes

---

## 7. Solución de Problemas

### Error: "Permission denied" al escribir

**Síntomas:**
```bash
pct exec 101 -- touch /mnt/shared/test.txt
# touch: cannot touch '/mnt/shared/test.txt': Permission denied
```

**Diagnóstico:**
```bash
# 1. Verificar montaje en el contenedor
pct exec 101 -- mount | grep /mnt/shared

# 2. Verificar permisos en el host
ls -ld /mnt/local_shared
getfacl /mnt/local_shared

# 3. Verificar grupo en el contenedor
pct exec 101 -- getent group sharedfiles
pct exec 101 -- groups root
```

**Soluciones:**
```bash
# Si falta el grupo en el contenedor:
pct exec 101 -- groupadd -g 1000 sharedfiles
pct exec 101 -- usermod -aG sharedfiles root

# Si faltan ACLs en el host:
setfacl -R -m g:sharedfiles:rwx /mnt/local_shared
setfacl -d -m g:sharedfiles:rwx /mnt/local_shared

# Si faltan permisos básicos:
chmod 2775 /mnt/local_shared
chown root:sharedfiles /mnt/local_shared
```

### Error: Archivos con propietario incorrecto

**Síntomas:**
```bash
ls -l /mnt/local_shared/
# -rw-r--r-- 1 100033 100033 archivo.txt  ← UIDs numéricos en lugar de nombres
```

**Causa:** El contenedor no privilegiado creó el archivo, pero el host no reconoce los UIDs mapeados.

**Solución:**
```bash
# 1. Verificar que las ACLs están activas
getfacl /mnt/local_shared/archivo.txt
# Debe mostrar: group:sharedfiles:rwx

# 2. Si las ACLs están bien, el archivo es accesible aunque el UID se vea raro
# 3. Para "limpiar" la visualización, cambiar propietario:
chown root:sharedfiles /mnt/local_shared/archivo.txt
```

### Error: Montaje no persistente tras reinicio

**Síntomas:**
Tras reiniciar Proxmox, los recursos NFS/Samba no están montados.

**Solución:**
```bash
# 1. Verificar /etc/fstab
cat /etc/fstab | grep -E "(nfs|cifs)"

# 2. Probar montaje manual
mount -a

# 3. Si falla, verificar conectividad
ping 192.168.1.100  # IP del servidor NFS/Samba

# 4. Para NFS, verificar que el servicio está activo
systemctl status nfs-common

# 5. Para Samba, verificar credenciales
cat /etc/cifs-credentials
```

### Error: "Transport endpoint is not connected"

**Síntomas:**
```bash
ls /mnt/nfs_shared
# ls: cannot access '/mnt/nfs_shared': Transport endpoint is not connected
```

**Causa:** El servidor NFS no está disponible o la conexión se perdió.

**Solución:**
```bash
# 1. Desmontar forzosamente
umount -f /mnt/nfs_shared

# 2. Verificar conectividad
ping 192.168.1.100
showmount -e 192.168.1.100

# 3. Remontar
mount /mnt/nfs_shared

# 4. Si persiste, revisar opciones de montaje
# Cambiar 'hard' por 'soft' en /etc/fstab para evitar bloqueos
```

---

## 8. Comandos de Referencia Rápida

### Gestión de Grupos
```bash
# Crear grupo
groupadd -g 101000 sharedfiles

# Añadir usuario a grupo
usermod -aG sharedfiles usuario

# Ver miembros de un grupo
getent group sharedfiles

# Ver grupos de un usuario
groups usuario
id usuario
```

### Gestión de Permisos
```bash
# Permisos básicos con setgid
chmod 2775 /ruta/directorio
chown root:sharedfiles /ruta/directorio

# ACLs
setfacl -R -m g:sharedfiles:rwx /ruta/directorio    # Aplicar a existente
setfacl -d -m g:sharedfiles:rwx /ruta/directorio    # Por defecto para nuevos

# Ver ACLs
getfacl /ruta/directorio

# Eliminar ACLs
setfacl -b /ruta/directorio
```

### Gestión de Contenedores LXC
```bash
# Añadir punto de montaje
pct set ID -mp0 /host/path,mp=/container/path,backup=0,acl=1,shared=1

# Ejecutar comando en contenedor
pct exec ID -- comando

# Entrar al contenedor
pct enter ID

# Ver configuración del contenedor
cat /etc/pve/lxc/ID.conf
```

### Montajes de Red
```bash
# NFS temporal
mount -t nfs servidor:/export /punto/montaje

# Samba temporal
mount -t cifs //servidor/recurso /punto/montaje -o credentials=/archivo

# Ver montajes activos
mount | grep -E "(nfs|cifs)"

# Desmontar
umount /punto/montaje

# Montaje persistente
echo "entrada" >> /etc/fstab
mount -a
```

### Diagnóstico
```bash
# Ver permisos detallados
ls -la /ruta
getfacl /ruta

# Ver procesos usando un directorio
lsof /ruta

# Ver montajes del sistema
cat /proc/mounts | grep /ruta

# Verificar conectividad NFS
showmount -e servidor_nfs

# Verificar conectividad Samba
smbclient -L //servidor_samba -U usuario
```

---

## ✅ Resumen Final

Esta guía te ha enseñado a:

1. **Entender** los conceptos de usuarios, grupos y ACLs en Linux
2. **Crear** un grupo universal (`sharedfiles`) para compartir recursos
3. **Montar** diferentes tipos de recursos (local, NFS, Samba) en Proxmox
4. **Configurar** contenedores privilegiados y no privilegiados correctamente
5. **Aplicar** permisos que funcionen en todos los escenarios
6. **Solucionar** problemas comunes de permisos y montajes

**Puntos clave para recordar:**
- Usa **GID 101000** para el grupo `sharedfiles`
- Aplica **permisos 2775** (con setgid) en directorios compartidos
- Configura **ACLs por defecto** para garantizar herencia
- Usa **shared=1** en montajes LXC para compatibilidad con clusters
- Los contenedores **no privilegiados** requieren configuración del grupo
- Los recursos de red necesitan **_netdev** y **nofail** en `/etc/fstab`

Con esta configuración, tendrás un sistema robusto de recursos compartidos que funciona correctamente entre el host Proxmox y todos tus contenedores LXC, independientemente de si son privilegiados o no.
```

