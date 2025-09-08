# 📘 Guía Completa: Compartir Recursos en Proxmox con LXC
*Montaje de recursos NFS, Samba y directorios locales en contenedores privilegiados y no privilegiados*

---

## 📋 Índice

1. [**Conceptos Fundamentales**](#1-conceptos-fundamentales)
   - [¿Qué son los usuarios y grupos en Linux?](#qué-son-los-usuarios-y-grupos-en-linux)
   - [¿Qué son los permisos?](#qué-son-los-permisos)
   - [¿Qué son las ACLs?](#qué-son-las-acls)
   - [Contenedores privilegiados vs no privilegiados](#contenedores-privilegiados-vs-no-privilegiados)

2. [**Cómo Funcionan los Permisos en Recursos Compartidos**](#2-cómo-funcionan-los-permisos-en-recursos-compartidos)
   - [Servidores NFS (Linux, TrueNAS, Synology)](#servidores-nfs)
   - [Servidores Samba/CIFS](#servidores-sambacifs)
   - [Directorios locales](#directorios-locales)

3. [**Preparación del Host Proxmox**](#3-preparación-del-host-proxmox)
   - [Crear grupo universal](#crear-grupo-universal)
   - [Montar recurso NFS](#montar-recurso-nfs)
   - [Montar recurso Samba](#montar-recurso-samba)
   - [Crear directorio local](#crear-directorio-local)

4. [**Configuración de Contenedores**](#4-configuración-de-contenedores)
   - [Contenedores privilegiados](#contenedores-privilegiados)
   - [Contenedores no privilegiados](#contenedores-no-privilegiados)

5. [**Montaje en Contenedores LXC**](#5-montaje-en-contenedores-lxc)

6. [**Verificación y Pruebas**](#6-verificación-y-pruebas)

7. [**Solución de Problemas**](#7-solución-de-problemas)

---

## 1. Conceptos Fundamentales

### ¿Qué son los usuarios y grupos en Linux?

En Linux, cada archivo y proceso pertenece a un **usuario** y un **grupo**:

```bash
# Ver información de un archivo
ls -l /etc/passwd
# Salida: -rw-r--r-- 1 root root 2847 sep  8 12:34 /etc/passwd
#         permisos   usuario grupo tamaño fecha nombre
```

**¿Por qué son importantes los grupos?**
- Permiten dar acceso a múltiples usuarios sin cambiar permisos individuales
- En Proxmox, son la clave para que diferentes contenedores accedan a los mismos archivos
- Simplifican la administración: añades un usuario al grupo y automáticamente tiene acceso

### ¿Qué son los permisos?

Los permisos en Linux se representan con 3 números (ejemplo: `755`):

```bash
# Ejemplo de permisos
chmod 755 /mnt/shared_data
# 7 = 4+2+1 = lectura+escritura+ejecución para el propietario
# 5 = 4+0+1 = lectura+ejecución para el grupo
# 5 = 4+0+1 = lectura+ejecución para otros
```

**Permisos especiales importantes:**
- **setgid (2000)**: Los archivos nuevos heredan el grupo del directorio padre
- **sticky bit (1000)**: Solo el propietario puede borrar sus archivos

```bash
# Combinar permisos especiales
chmod 2775 /mnt/shared_data
# 2 = setgid activado
# 775 = rwxrwxr-x (lectura/escritura/ejecución para propietario y grupo)
```

### ¿Qué son las ACLs?

Las **ACLs (Access Control Lists)** son permisos extendidos que van más allá del sistema tradicional usuario/grupo/otros:

```bash
# Ver ACLs de un directorio
getfacl /mnt/shared_data

# Salida típica:
# file: /mnt/shared_data
# owner: root
# group: sharedfiles
# flags: -s-  (setgid activo)
# user::rwx
# group::rwx
# group:sharedfiles:rwx
# mask::rwx
# other::r-x
# default:user::rwx
# default:group::rwx
# default:group:sharedfiles:rwx
# default:mask::rwx
# default:other::r-x
```

**¿Por qué son cruciales las ACLs?**
- **Garantizan permisos**: Aunque un proceso tenga `umask 077`, las ACLs aseguran que el grupo tenga acceso
- **Herencia automática**: Los archivos nuevos automáticamente tienen los permisos correctos
- **Compatibilidad con NFS**: NFS solo entiende números de UID/GID, las ACLs aseguran consistencia

### Contenedores privilegiados vs no privilegiados

**Contenedor privilegiado:**
- UID 0 en contenedor = UID 0 en host (root = root)
- Acceso directo a recursos del host
- Menos seguro pero más simple

**Contenedor no privilegiado:**
- UID 0 en contenedor = UID 100000 en host
- UID 1000 en contenedor = UID 101000 en host
- Más seguro pero requiere mapeo de permisos

```bash
# Ejemplo: archivo creado en contenedor no privilegiado
# Dentro del contenedor (ID 101):
echo "test" > /mnt/shared/archivo.txt
ls -l /mnt/shared/archivo.txt
# -rw-r--r-- 1 root root 5 sep 8 archivo.txt

# En el host:
ls -l /mnt/shared_data/archivo.txt  
# -rw-r--r-- 1 100000 100000 5 sep 8 archivo.txt
# UID 0 del contenedor se ve como UID 100000 en el host
```

---

## 2. Cómo Funcionan los Permisos en Recursos Compartidos

### Servidores NFS

**En el servidor NFS (Linux, TrueNAS, Synology):**

Los servidores NFS manejan permisos de diferentes formas:

#### Servidor Linux tradicional:
```bash
# En el servidor NFS
/etc/exports:
/export/data 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)

# El directorio en el servidor:
ls -l /export/data
drwxrwxr-x 2 usuario1 compartido 4096 sep 8 /export/data
```

#### TrueNAS/FreeNAS:
- **Interfaz web**: Configuras permisos por usuario/grupo
- **Mapeo de usuarios**: Puedes mapear usuarios del cliente a usuarios del servidor
- **ACLs nativas**: TrueNAS usa ACLs de FreeBSD/ZFS que son más potentes

#### Synology NAS:
- **DSM (interfaz web)**: Configuras carpetas compartidas con permisos por usuario
- **Mapeo automático**: Synology puede mapear automáticamente usuarios por nombre
- **Squash options**: Controla cómo se mapean usuarios root y anónimos

**¿Qué pasa cuando montas NFS en Proxmox?**

```bash
# Montar NFS desde TrueNAS
mount -t nfs 192.168.1.100:/mnt/pool1/shared /mnt/nfs_share

# Ver cómo se ven los permisos en Proxmox:
ls -l /mnt/nfs_share
# drwxrwxr-x 2 1001 1001 4096 sep 8 shared_folder
#              ^^^^ ^^^^ 
#              UID  GID del servidor NFS
```

**Problema típico**: El servidor NFS tiene UID/GID diferentes a Proxmox:
- Servidor: usuario `juan` (UID 1001), grupo `familia` (GID 1001)  
- Proxmox: no existe UID 1001, se ve como número
- **Solución**: Crear grupo común con GID específico y usar ACLs

### Servidores Samba/CIFS

**En el servidor Samba:**

Samba traduce entre permisos de Windows y Linux:

```bash
# Configuración típica en smb.conf del servidor:
[shared]
   path = /srv/samba/shared
   valid users = @familia
   read only = no
   create mask = 0664
   directory mask = 2775
   force group = familia
```

**¿Qué pasa cuando montas Samba en Proxmox?**

```bash
# Montar Samba desde Windows Server o Linux
mount -t cifs //192.168.1.200/shared /mnt/samba_share -o username=juan,password=secreto

# Ver permisos en Proxmox:
ls -l /mnt/samba_share  
# drwxrwxr-x 2 juan familia 4096 sep 8 documentos
```

**Características importantes de Samba:**
- **Mapeo de usuarios**: Samba puede mapear usuarios Windows ↔ Linux
- **Force group**: Todos los archivos nuevos pertenecen a un grupo específico
- **Create/directory mask**: Controla permisos de archivos y carpetas nuevos
- **ACL support**: Samba puede preservar ACLs de Windows en sistemas Linux

### Directorios locales

Los directorios locales son los más simples:
- Permisos directos del sistema de archivos
- Sin traducción de protocolos
- Control total sobre UID/GID

```bash
# Crear directorio local optimizado para compartir
mkdir -p /mnt/local_shared
chown root:sharedfiles /mnt/local_shared
chmod 2775 /mnt/local_shared
setfacl -d -m g:sharedfiles:rwx /mnt/local_shared
```

---

## 3. Preparación del Host Proxmox

### Crear grupo universal

Primero creamos un grupo que será el punto común entre host y contenedores:

```bash
# Crear grupo con GID específico
groupadd -g 101000 sharedfiles

# Verificar que se creó correctamente
getent group sharedfiles
# sharedfiles:x:101000:

# ¿Por qué GID 101000?
# - Es el mapeo base para contenedores no privilegiados
# - UID/GID 1000 en contenedor no privilegiado = 101000 en host
# - Facilita la compatibilidad entre ambos tipos de contenedores
```

### Montar recurso NFS

#### Montaje temporal (para pruebas):
```bash
# Crear punto de montaje
mkdir -p /mnt/nfs_share

# Montar NFS (ejemplo desde TrueNAS)
mount -t nfs 192.168.1.100:/mnt/pool1/shared /mnt/nfs_share

# Verificar montaje
df -h | grep nfs_share
# 192.168.1.100:/mnt/pool1/shared  1.0T  500G  500G  50% /mnt/nfs_share

# Ver permisos originales
ls -l /mnt/nfs_share
# total 4
# drwxr-xr-x 2 1001 1001 4096 sep  8 12:34 documentos
# -rw-r--r-- 1 1002 1002  156 sep  8 12:35 readme.txt
```

#### Configurar permisos para compartir con LXC:
```bash
# Cambiar grupo del punto de montaje
chgrp sharedfiles /mnt/nfs_share
chmod g+w /mnt/nfs_share

# Aplicar ACLs para garantizar acceso del grupo
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_share
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_share

# Verificar ACLs aplicadas
getfacl /mnt/nfs_share
```

#### Hacer montaje persistente:
```bash
# Editar /etc/fstab
nano /etc/fstab

# Añadir línea:
192.168.1.100:/mnt/pool1/shared /mnt/nfs_share nfs rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev 0 0

# Explicación de opciones:
# rw: lectura y escritura
# hard: reintentar indefinidamente si el servidor no responde
# nofail: no fallar el arranque si no se puede montar
# rsize/wsize: tamaño de bloques para optimizar transferencia
# timeo: timeout en décimas de segundo (60 segundos)
# retrans: número de retransmisiones antes de timeout
# _netdev: esperar a que la red esté disponible
# 0 0: no hacer dump ni fsck (siempre para recursos de red)

# Probar montaje
mount -a
```

### Montar recurso Samba

#### Crear archivo de credenciales:
```bash
# Crear archivo seguro para credenciales
nano /etc/cifs-credentials

# Contenido:
username=tu_usuario
password=tu_contraseña
domain=tu_dominio

# Proteger archivo
chmod 600 /etc/cifs-credentials
```

#### Montaje temporal:
```bash
# Crear punto de montaje
mkdir -p /mnt/samba_share

# Montar Samba
mount -t cifs //192.168.1.200/shared /mnt/samba_share -o credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0

# Verificar montaje
df -h | grep samba_share
```

#### Configurar permisos:
```bash
# Aplicar mismo tratamiento que NFS
chgrp sharedfiles /mnt/samba_share
chmod g+w /mnt/samba_share
setfacl -R -m g:sharedfiles:rwx /mnt/samba_share
setfacl -d -m g:sharedfiles:rwx /mnt/samba_share
```

#### Hacer montaje persistente:
```bash
# Añadir a /etc/fstab:
//192.168.1.200/shared /mnt/samba_share cifs credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0,_netdev,nofail 0 0

# Probar
mount -a
```

### Crear directorio local

```bash
# Crear directorio local para compartir
mkdir -p /mnt/local_shared

# Configurar propietario y permisos
chown root:sharedfiles /mnt/local_shared
chmod 2775 /mnt/local_shared

# Aplicar ACLs
setfacl -d -m g:sharedfiles:rwx /mnt/local_shared

# Verificar configuración
ls -ld /mnt/local_shared
# drwxrwsr-x+ 2 root sharedfiles 4096 sep  8 12:45 /mnt/local_shared
#         ^^^
#         's' indica setgid activo
#            '+' indica ACLs presentes
```

---

## 4. Configuración de Contenedores

### Contenedores privilegiados

En contenedores privilegiados, los UIDs son idénticos al host, pero aún necesitamos configurar el grupo:

```bash
# Entrar al contenedor privilegiado (ejemplo ID 100)
pct exec 100 -- bash

# Crear grupo con mismo GID que el host
groupadd -g 101000 sharedfiles

# ¿Por qué necesitamos crear el grupo si es privilegiado?
# Aunque los UIDs coinciden, los NOMBRES de grupo deben existir
# El kernel mapea por números, pero las aplicaciones usan nombres

# Verificar que el grupo se creó
getent group sharedfiles
# sharedfiles:x:101000:

# Añadir usuarios relevantes al grupo
# Ver qué usuarios existen en el contenedor:
awk -F: '$3>=1000 && $1!="nobody" {print $1 " (UID: " $3 ")"}' /etc/passwd

# Ejemplo de salida:
# root (UID: 0)
# www-data (UID: 33)
# ncp (UID: 1000)

# Añadir usuarios que necesiten acceso:
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data
usermod -aG sharedfiles ncp 2>/dev/null || true

# Verificar membresía
groups root
# root : root sharedfiles

groups www-data  
# www-data : www-data sharedfiles

# Salir del contenedor
exit
```

**¿Por qué añadir usuarios al grupo en contenedor privilegiado?**
- Aunque el UID es el mismo, el proceso debe ejecutarse con el GID correcto
- Las aplicaciones (Apache, Nginx, Nextcloud) ejecutan con usuarios específicos
- Al añadirlos al grupo, pueden escribir en directorios compartidos

### Contenedores no privilegiados

Los contenedores no privilegiados requieren mapeo de UIDs:

```bash
# Entrar al contenedor no privilegiado (ejemplo ID 101)
pct exec 101 -- bash

# Crear grupo con GID que mapee a 101000 en el host
groupadd -g 1000 sharedfiles

# ¿Por qué GID 1000 y no 101000?
# Dentro del contenedor: GID 1000
# En el host se ve como: GID 101000 (1000 + 100000)
# Esto coincide con nuestro grupo del host

# Verificar mapeo
id
# uid=0(root) gid=0(root) groups=0(root)

# Añadir usuarios al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data
usermod -aG sharedfiles ncp 2>/dev/null || true

# Verificar que el mapeo funciona
id www-data
# uid=33(www-data) gid=33(www-data) groups=33(www-data),1000(sharedfiles)

# Salir del contenedor
exit

# Verificar desde el host cómo se ve el grupo
pct exec 101 -- getent group sharedfiles
# sharedfiles:x:1000:root,www-data,ncp
```

**¿Cómo añadir más usuarios?**

```bash
# Dentro del contenedor, listar todos los usuarios del sistema:
awk -F: '{print $1 " (UID: " $3 ", GID: " $4 ")"}' /etc/passwd

# Añadir usuarios específicos:
usermod -aG sharedfiles nombre_usuario

# Añadir todos los usuarios con UID >= 1000 automáticamente:
for user in $(awk -F: '$3>=1000 && $1!="nobody" {print $1}' /etc/passwd); do
    usermod -aG sharedfiles "$user" 2>/dev/null || true
    echo "Usuario $user añadido al grupo sharedfiles"
done
```

---

## 5. Montaje en Contenedores LXC

### Configurar montajes

```bash
# Para contenedor privilegiado (ID 100)
pct set 100 -mp0 /mnt/nfs_share,mp=/mnt/shared,shared=1,backup=0,acl=1

# Para contenedor no privilegiado (ID 101)  
pct set 101 -mp0 /mnt/nfs_share,mp=/mnt/shared,shared=1,backup=0,acl=1

# Explicación de parámetros:
# /mnt/nfs_share: ruta en el host
# mp=/mnt/shared: ruta dentro del contenedor
# shared=1: permite migración en clusters sin copiar datos
# backup=0: excluye del backup de vzdump (evita copiar datos externos)
# acl=1: habilita soporte para ACLs dentro del contenedor
```

### Reiniciar contenedores

```bash
# Reiniciar para activar montajes
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

### Prueba en contenedor privilegiado

```bash
# Entrar al contenedor privilegiado
pct exec 100 -- bash

# Verificar montaje
df -h | grep shared
# /dev/fuse  1.0T  500G  500G  50% /mnt/shared

# Verificar permisos
ls -ld /mnt/shared
# drwxrwsr-x+ 2 root sharedfiles 4096 sep  8 /mnt/shared

# Crear archivo de prueba
echo "Prueba desde contenedor privilegiado $(date)" > /mnt/shared/test_privileged.txt

# Verificar propietario
ls -l /mnt/shared/test_privileged.txt
# -rw-rw-r--+ 1 root sharedfiles 45 sep  8 test_privileged.txt

# Cambiar a usuario www-data y probar
su - www-data -s /bin/bash
echo "Prueba www-data privilegiado $(date)" > /mnt/shared/test_www_privileged.txt
ls -l /mnt/shared/test_www_privileged.txt
# -rw-rw-r--+ 1 www-data sharedfiles 42 sep  8 test_www_privileged.txt

exit # salir de www-data
exit # salir del contenedor
```

### Prueba en contenedor no privilegiado

```bash
# Entrar al contenedor no privilegiado
pct exec 101 -- bash

# Verificar montaje
df -h | grep shared

# Crear archivo de prueba
echo "Prueba desde contenedor no privilegiado $(date)" > /mnt/shared/test_unprivileged.txt

# Verificar dentro del contenedor
ls -l /mnt/shared/test_unprivileged.txt
# -rw-rw-r--+ 1 root sharedfiles 48 sep  8 test_unprivileged.txt

# Probar con www-data
su - www-data -s /bin/bash
echo "Prueba www-data no privilegiado $(date)" > /mnt/shared/test_www_unprivileged.txt
exit

exit # salir del contenedor
```

### Verificar desde el host

```bash
# Ver todos los archivos creados
ls -l /mnt/nfs_share/

# Salida esperada:
# -rw-rw-r--+ 1 root      sharedfiles    45 sep  8 test_privileged.txt
# -rw-rw-r--+ 1 www-data  sharedfiles    42 sep  8 test_www_privileged.txt  
# -rw-rw-r--+ 1 100000    101000         48 sep  8 test_unprivileged.txt
# -rw-rw-r--+ 1 100033    101000         45 sep  8 test_www_unprivileged.txt

# Verificar que todos pertenecen al grupo correcto
stat /mnt/nfs_share/test_*.txt | grep -E "(File:|Uid:|Gid:)"
```

### Prueba de escritura cruzada

```bash
# Desde contenedor privilegiado, modificar archivo del no privilegiado
pct exec 100 -- bash -c 'echo "Modificado por privilegiado" >> /mnt/shared/test_unprivileged.txt'

# Desde contenedor no privilegiado, modificar archivo del privilegiado  
pct exec 101 -- bash -c 'echo "Modificado por no privilegiado" >> /mnt/shared/test_privileged.txt'

# Verificar que ambas operaciones funcionaron
cat /mnt/nfs_share/test_unprivileged.txt
cat /mnt/nfs_share/test_privileged.txt
```

---

## 7. Solución de Problemas

### Error: "Permission denied" al escribir

**Síntomas:**
```bash
pct exec 101 -- bash -c 'echo "test" > /mnt/shared/test.txt'
# bash: /mnt/shared/test.txt: Permission denied
```

**Diagnóstico:**
```bash
# Verificar permisos del directorio
ls -ld /mnt/nfs_share
# drwxr-xr-x 2 1001 1001 4096 sep  8 /mnt/nfs_share
#         ^^^
#         Falta escritura para grupo

# Verificar ACLs
getfacl /mnt/nfs_share
# No aparecen ACLs para el grupo sharedfiles
```

**Solución:**
```bash
# Corregir permisos
chmod g+w /mnt/nfs_share
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_share
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_share
```

### Error: Archivos aparecen con propietario numérico

**Síntomas:**
```bash
ls -l /mnt/nfs_share
# -rw-r--r-- 1 1001 1001 156 sep  8 archivo.txt
#              ^^^^ ^^^^
#              UIDs numéricos en lugar de nombres
```

**Explicación:**
- El servidor NFS tiene usuarios con UIDs diferentes
- Proxmox no tiene usuarios con esos UIDs
- Es normal y no afecta el funcionamiento

**Solución (opcional):**
```bash
# Crear usuarios con los mismos UIDs si es necesario
useradd -u 1001 -g sharedfiles usuario_remoto
```

### Error: "Transport endpoint is not connected"

**Síntomas:**
```bash
ls /mnt/nfs_share
# ls: cannot access '/mnt/nfs_share': Transport endpoint is not connected
```

**Diagnóstico:**
```bash
# Verificar montaje
mount | grep nfs_share
# No aparece o aparece como "stale"

# Verificar conectividad al servidor
ping 192.168.1.100
showmount -e 192.168.1.100
```

**Solución:**
```bash
# Desmontar forzosamente
umount -f /mnt/nfs_share

# Volver a montar
mount -a

# Si persiste, verificar configuración del servidor NFS
```

### Error: Contenedor no puede acceder al montaje

**Síntomas:**
```bash
pct exec 101 -- ls /mnt/shared
# ls: cannot access '/mnt/shared': No such file or directory
```

**Diagnóstico:**
```bash
# Verificar configuración del contenedor
pct config 101 | grep mp0
# mp0: /mnt/nfs_share,mp=/mnt/shared,backup=0,acl=1

# Verificar que el directorio existe en el host
ls -ld /mnt/nfs_share
```

**Solución:**
```bash
# Reiniciar contenedor
pct reboot 101

# Si persiste, verificar que el montaje del host funciona
ls /mnt/nfs_share
```

### Error: ACLs no funcionan

**Síntomas:**
```bash
getfacl /mnt/nfs_share
# getfacl: Removing leading '/' from absolute path names
# # file: mnt/nfs_share
# # owner: root
# # group: sharedfiles
# user::rwx
# group::rwx
# other::r-x
# (No aparecen ACLs por defecto)
```

**Diagnóstico:**
```bash
# Verificar si el sistema de archivos soporta ACLs
mount | grep nfs_share
# Si es NFS, verificar versión y opciones de montaje

# Verificar herramientas ACL
which setfacl getfacl
```

**Solución:**
```bash
# Instalar herramientas ACL si faltan
apt update && apt install acl -y

# Remontar con soporte ACL si es necesario
mount -o remount,acl /mnt/nfs_share

# Aplicar ACLs nuevamente
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_share
```

---

## 🎯 Resumen Final

### Flujo completo exitoso:

1. **Host**: Crear grupo `sharedfiles` (GID 101000)
2. **Host**: Montar recurso (NFS/Samba/local) con permisos y ACLs correctos
3. **Contenedores**: Crear grupo `sharedfiles` y añadir usuarios
4. **Host**: Configurar montaje en contenedores con `shared=1,backup=0,acl=1`
5. **Verificar**: Crear archivos desde ambos contenedores y verificar permisos

### Comandos clave para recordar:

```bash
# Crear grupo universal
groupadd -g 101000 sharedfiles

# Configurar directorio con herencia
chmod 2775 /mnt/directorio
chgrp sharedfiles /mnt/directorio

# Aplicar ACLs por defecto
setfacl -d -m g:sharedfiles:rwx /mnt/directorio

# Montar en contenedor
pct set ID -mp0 /host/path,mp=/container/path,shared=1,backup=0,acl=1

# Verificar funcionamiento
pct exec ID -- su - usuario -c 'echo "test" > /container/path/test.txt'
```

### ¿Por qué funciona esta configuración?

- **Grupo común**: Punto de encuentro entre host y contenedores
- **GID 101000**: Compatible con mapeo de contenedores no privilegiados  
- **setgid (2775)**: Herencia automática del grupo en archivos nuevos
- **ACLs por defecto**: Garantizan permisos independientemente de umask
- **shared=1**: Permite migración en clusters
- **backup=0**: Evita copiar datos externos en backups

Esta configuración asegura que tanto contenedores privilegiados como no privilegiados puedan leer y escribir en recursos compartidos, manteniendo permisos consistentes y compatibilidad con clusters de Proxmox.
```

