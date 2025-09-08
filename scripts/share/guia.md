# 📘 Guía Completa: Compartir Recursos entre Proxmox Host y Contenedores LXC

## Índice
1. [Conceptos Fundamentales](#conceptos-fundamentales)
2. [Usuarios y Grupos en Linux](#usuarios-y-grupos-en-linux)
3. [Permisos en Linux](#permisos-en-linux)
4. [¿Qué son las ACL?](#qué-son-las-acl)
5. [El Problema de los Contenedores No Privilegiados](#el-problema-de-los-contenedores-no-privilegiados)
6. [Solución Universal: Grupos Compartidos](#solución-universal-grupos-compartidos)
7. [Configuración Paso a Paso](#configuración-paso-a-paso)
8. [Casos Prácticos](#casos-prácticos)
9. [Resolución de Problemas](#resolución-de-problemas)

---

## 🎯 Introducción

Esta guía explica paso a paso cómo compartir carpetas y recursos entre el host de Proxmox y contenedores LXC (privilegiados y no privilegiados). Aprenderás los conceptos fundamentales de permisos en Linux y cómo configurar correctamente NFS, Samba y directorios locales.

### ¿Por qué es importante?

En Proxmox es común necesitar que varios contenedores accedan a los mismos datos:
- Compartir archivos entre múltiples servicios
- Servir contenido por red (NFS/Samba)
- Centralizar almacenamiento de datos
- Hacer backups centralizados

El mayor desafío son los **permisos**, especialmente en contenedores **no privilegiados** que usan mapeo de IDs.

---

## 📚 Conceptos Fundamentales

### ¿Qué son los Usuarios y Grupos en Linux?

**Usuario**: Identidad que ejecuta procesos y posee archivos
- Cada usuario tiene un **UID** (User ID) numérico único
- Ejemplo: `root` tiene UID 0, `www-data` tiene UID 33

**Grupo**: Colección de usuarios que comparten permisos
- Cada grupo tiene un **GID** (Group ID) numérico único
- Un usuario puede pertenecer a múltiples grupos
- Ejemplo: grupo `sharedfiles` con GID 1000

```bash
# Ver información de un usuario
id www-data
# Salida: uid=33(www-data) gid=33(www-data) groups=33(www-data),1000(sharedfiles)

# Ver todos los grupos del sistema
cat /etc/group | grep shared
# Salida: sharedfiles:x:1000:www-data,root
```

### ¿Qué son los Permisos en Linux?

Cada archivo y directorio tiene tres tipos de permisos para tres categorías:

**Categorías:**
- **Propietario** (u): El usuario dueño del archivo
- **Grupo** (g): El grupo propietario del archivo  
- **Otros** (o): Todos los demás usuarios

**Permisos:**
- **Lectura (r)**: Ver contenido (valor 4)
- **Escritura (w)**: Modificar contenido (valor 2)
- **Ejecución (x)**: Ejecutar archivo o acceder a directorio (valor 1)

```bash
# Ejemplo de permisos
ls -l /mnt/shared_data
# -rwxrw-r-- 1 root sharedfiles 1024 sep 8 archivo.txt
#  |||||||
#  ||||||└─ Otros: lectura
#  |||||└── Grupo: lectura + escritura  
#  ||||└─── Propietario: lectura + escritura + ejecución
#  |||└──── Tipo: - (archivo regular)
#  ||└───── Propietario: root
#  |└────── Grupo: sharedfiles
#  └─────── Tamaño: 1024 bytes
```

### ¿Qué son las ACLs (Access Control Lists)?

Las ACLs permiten permisos más granulares que el sistema tradicional Unix:

```bash
# Ver ACLs de un directorio
getfacl /mnt/shared_data
# Salida:
# file: /mnt/shared_data
# owner: root
# group: sharedfiles
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

**¿Por qué usar ACLs?**
- Garantizan permisos consistentes independientemente de la `umask`
- Permiten permisos por defecto para archivos nuevos
- Esenciales para NFS (que solo entiende UIDs/GIDs numéricos)

### Contenedores Privilegiados vs No Privilegiados

**Privilegiados:**
- Usan los mismos UIDs/GIDs que el host
- `root` en contenedor = `root` en host (UID 0)
- Más simples de configurar pero menos seguros

**No Privilegiados:**
- UIDs/GIDs desplazados +100000
- `root` en contenedor (UID 0) = UID 100000 en host
- `www-data` en contenedor (UID 33) = UID 100033 en host
- Más seguros pero requieren configuración especial

---

## 🛠️ Configuración Paso a Paso

### Paso 1: Preparar el Host

#### 1.1 Crear Directorio Base y Grupo Universal

```bash
# Crear directorio compartido
mkdir -p /mnt/shared_data

# Crear grupo universal con GID específico
groupadd -g 101000 sharedfiles

# Verificar creación
getent group sharedfiles
# Salida: sharedfiles:x:101000:
```

**¿Por qué GID 101000?**
- Es el mapeo que corresponde a GID 1000 dentro de contenedores no privilegiados
- Permite compatibilidad universal entre contenedores privilegiados y no privilegiados

#### 1.2 Configurar Permisos Base

```bash
# Asignar propietario y grupo
chown root:sharedfiles /mnt/shared_data

# Establecer permisos con setgid
chmod 2775 /mnt/shared_data
```

**Explicación del chmod 2775:**
- `2`: **setgid bit** - Los archivos nuevos heredan el grupo del directorio padre
- `7`: Propietario (root) - lectura, escritura, ejecución
- `7`: Grupo (sharedfiles) - lectura, escritura, ejecución  
- `5`: Otros - lectura, ejecución (sin escritura)

#### 1.3 Aplicar ACLs

```bash
# ACLs para contenido existente
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data

# ACLs por defecto para contenido nuevo
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data

# Verificar ACLs aplicadas
getfacl /mnt/shared_data
```

**¿Por qué ACLs?**
- `-R`: Aplica a todo el contenido existente recursivamente
- `-d`: Define permisos por defecto para archivos/directorios nuevos
- Garantiza que el grupo `sharedfiles` siempre tenga acceso completo

### Paso 2: Configurar Contenedor Privilegiado

```bash
# 2.1 Entrar al contenedor
pct exec 100 -- bash

# 2.2 Crear grupo idéntico al host
groupadd -g 101000 sharedfiles

# 2.3 Añadir usuarios relevantes al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Si tienes otros usuarios (nextcloud, etc.)
usermod -aG sharedfiles ncp 2>/dev/null || true

# 2.4 Verificar membresía
groups root
groups www-data

# 2.5 Salir del contenedor
exit
```

**¿Es necesario configurar grupos en contenedores privilegiados?**

**SÍ, es necesario** por las siguientes razones:

1. **Consistencia de permisos**: Aunque el contenedor privilegiado usa los mismos UIDs que el host, los **grupos** pueden no existir dentro del contenedor
2. **Servicios específicos**: Aplicaciones como Apache (`www-data`) o Nextcloud (`ncp`) necesitan pertenecer al grupo para escribir archivos
3. **ACLs**: Las ACLs verifican tanto UIDs como GIDs, por lo que el grupo debe existir en ambos lados
4. **Futuras migraciones**: Si conviertes el contenedor a no privilegiado, ya tendrás la configuración correcta

**Ejemplo práctico:**
```bash
# Sin configurar grupo en contenedor privilegiado
echo "test" > /mnt/shared/archivo.txt
ls -l /mnt/shared/archivo.txt
# -rw-r--r-- 1 root root 5 sep 8 archivo.txt  ← Grupo incorrecto

# Con grupo configurado
echo "test2" > /mnt/shared/archivo2.txt  
ls -l /mnt/shared/archivo2.txt
# -rw-rw-r-- 1 root sharedfiles 6 sep 8 archivo2.txt  ← Grupo correcto
```

### Paso 3: Configurar Contenedor No Privilegiado

```bash
# 3.1 Entrar al contenedor
pct exec 101 -- bash

# 3.2 Crear grupo con GID mapeado
groupadd -g 1000 sharedfiles
# Importante: GID 1000 en contenedor = GID 101000 en host

# 3.3 Añadir usuarios al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data
usermod -aG sharedfiles ncp 2>/dev/null || true

# 3.4 Verificar configuración
id www-data
# Salida esperada: uid=33(www-data) gid=33(www-data) groups=33(www-data),1000(sharedfiles)

# 3.5 Salir del contenedor
exit
```

#### Añadir Usuarios Adicionales

**Método 1: Añadir usuarios específicos**
```bash
# Dentro del contenedor
usermod -aG sharedfiles usuario1
usermod -aG sharedfiles usuario2
```

**Método 2: Añadir todos los usuarios del sistema (automático)**
```bash
# Script para añadir todos los usuarios con UID >= 1000
for user in $(awk -F: '$3>=1000 && $1!="nobody" {print $1}' /etc/passwd); do
    usermod -aG sharedfiles "$user" 2>/dev/null || true
    echo "Usuario $user añadido al grupo sharedfiles"
done
```

**Método 3: Añadir usuarios interactivamente**
```bash
# Mostrar usuarios disponibles
echo "Usuarios disponibles en el sistema:"
awk -F: '$3>=1000 && $1!="nobody" {print "- " $1 " (UID: " $3 ")"}' /etc/passwd

# Preguntar qué usuarios añadir
read -p "¿Qué usuarios quieres añadir al grupo sharedfiles? (separados por espacios): " usuarios
for user in $usuarios; do
    if id "$user" >/dev/null 2>&1; then
        usermod -aG sharedfiles "$user"
        echo "✓ Usuario $user añadido"
    else
        echo "✗ Usuario $user no existe"
    fi
done
```

### Paso 4: Montar el Directorio en los Contenedores

```bash
# 4.1 Para contenedor privilegiado (ID 100)
pct set 100 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1

# 4.2 Para contenedor no privilegiado (ID 101)  
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1

# 4.3 Reiniciar contenedores para activar montajes
pct reboot 100
pct reboot 101

# Esperar a que arranquen
sleep 10
```

**Explicación de parámetros:**
- `mp0`: Mount point 0 (primer punto de montaje)
- `/mnt/shared_data`: Ruta en el host
- `mp=/mnt/shared`: Ruta dentro del contenedor
- `backup=0`: Excluir del backup de vzdump
- `acl=1`: Habilitar soporte para ACLs
- `shared=1`: **Importante para clusters** - permite migración sin copiar datos

**¿Por qué shared=1?**
- En clusters Proxmox, permite migrar contenedores entre nodos
- El almacenamiento debe estar disponible en todos los nodos
- Sin `shared=1`, Proxmox intentará copiar los datos durante la migración

---

## 🌐 Configurar Recursos de Red

### Opción A: Montar Recurso NFS Existente

#### A.1 Instalar Cliente NFS en el Host

```bash
# Debian/Ubuntu
apt update && apt install nfs-common

# Verificar servicios NFS
systemctl status rpc-statd
systemctl status rpc-gssd
```

#### A.2 Crear Punto de Montaje y Montar

```bash
# Crear directorio de montaje
mkdir -p /mnt/nfs_share

# Montar temporalmente para probar
mount -t nfs 192.168.1.50:/export/shared /mnt/nfs_share

# Verificar montaje
df -h | grep nfs
mount | grep nfs
```

#### A.3 Hacer Montaje Persistente

```bash
# Añadir a /etc/fstab
echo "192.168.1.50:/export/shared /mnt/nfs_share nfs rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev 0 0" >> /etc/fstab

# Verificar sintaxis
mount -a

# Comprobar que funciona tras reinicio
umount /mnt/nfs_share
mount /mnt/nfs_share
```

**Explicación de opciones NFS:**
- `rw`: Lectura y escritura
- `hard`: Reintentar indefinidamente si el servidor no responde
- `nofail`: No fallar el arranque si no se puede montar
- `rsize/wsize=131072`: Tamaño de buffer de lectura/escritura (128KB)
- `timeo=600`: Timeout de 60 segundos (600 décimas)
- `retrans=2`: Reintentar 2 veces antes de reportar error
- `_netdev`: Esperar a que la red esté disponible
- `0 0`: No hacer dump ni fsck (siempre para recursos de red)

#### A.4 Configurar Permisos en el Recurso NFS

```bash
# Aplicar configuración de permisos al recurso montado
chown root:sharedfiles /mnt/nfs_share
chmod 2775 /mnt/nfs_share
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_share
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_share
```

### Opción B: Montar Recurso Samba/CIFS

#### B.1 Instalar Cliente Samba

```bash
# Instalar herramientas CIFS
apt update && apt install cifs-utils

# Verificar instalación
which mount.cifs
```

#### B.2 Crear Credenciales Seguras

```bash
# Crear archivo de credenciales
cat > /etc/cifs-credentials << EOF
username=tu_usuario
password=tu_password
domain=tu_dominio
EOF

# Proteger archivo
chmod 600 /etc/cifs-credentials
chown root:root /etc/cifs-credentials
```

#### B.3 Montar Recurso Samba

```bash
# Crear punto de montaje
mkdir -p /mnt/samba_share

# Montar temporalmente
mount -t cifs //192.168.1.60/shared /mnt/samba_share -o credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0

# Verificar montaje
df -h | grep cifs
```

#### B.4 Hacer Montaje Persistente

```bash
# Añadir a /etc/fstab
echo "//192.168.1.60/shared /mnt/samba_share cifs credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0,_netdev,nofail 0 0" >> /etc/fstab

# Probar configuración
umount /mnt/samba_share
mount /mnt/samba_share
```

**Explicación de opciones CIFS:**
- `credentials=`: Archivo con usuario/contraseña
- `iocharset=utf8`: Codificación de caracteres
- `vers=3.0`: Versión del protocolo SMB
- `_netdev`: Esperar red disponible
- `nofail`: No fallar arranque si no se puede montar

#### B.5 Configurar Permisos en Samba

```bash
# Aplicar permisos al recurso Samba montado
chown root:sharedfiles /mnt/samba_share
chmod 2775 /mnt/samba_share
setfacl -R -m g:sharedfiles:rwx /mnt/samba_share
setfacl -d -m g:sharedfiles:rwx /mnt/samba_share
```

### Opción C: Crear Directorio Local

```bash
# Crear directorio local para compartir
mkdir -p /mnt/local_share

# Aplicar configuración estándar
chown root:sharedfiles /mnt/local_share
chmod 2775 /mnt/local_share
setfacl -R -m g:sharedfiles:rwx /mnt/local_share
setfacl -d -m g:sharedfiles:rwx /mnt/local_share

# Crear estructura de ejemplo
mkdir -p /mnt/local_share/{documentos,imagenes,backups}
chown -R root:sharedfiles /mnt/local_share/*
```

---

## ✅ Verificación y Pruebas

### Prueba 1: Verificar Montajes

```bash
# En el host
df -h | grep -E "(nfs|cifs|/mnt)"
mount | grep -E "(nfs|cifs|/mnt)"

# Verificar permisos
ls -la /mnt/shared_data
getfacl /mnt/shared_data
```

### Prueba 2: Probar Escritura desde Contenedores

```bash
# Contenedor privilegiado (100)
pct exec 100 -- bash -c "echo 'Prueba desde privilegiado' > /mnt/shared/test_privilegiado.txt"

# Contenedor no privilegiado (101)  
pct exec 101 -- bash -c "echo 'Prueba desde no privilegiado' > /mnt/shared/test_no_privilegiado.txt"

# Verificar en el host
ls -la /mnt/shared_data/
# Ambos archivos deben tener grupo 'sharedfiles'
```

### Prueba 3: Verificar Permisos Cruzados

```bash
# Desde contenedor 100, modificar archivo creado por contenedor 101
pct exec 100 -- bash -c "echo 'Modificado por privilegiado' >> /mnt/shared/test_no_privilegiado.txt"

# Desde contenedor 101, modificar archivo creado por contenedor 100
pct exec 101 -- bash -c "echo 'Modificado por no privilegiado' >> /mnt/shared/test_privilegiado.txt"

# Verificar contenido
cat /mnt/shared_data/test_privilegiado.txt
cat /mnt/shared_data/test_no_privilegiado.txt
```

### Prueba 4: Verificar Persistencia tras Reinicio

```bash
# Reiniciar host
reboot

# Tras reinicio, verificar montajes automáticos
df -h | grep -E "(nfs|cifs)"
ls -la /mnt/shared_data/

# Verificar que contenedores pueden seguir escribiendo
pct start 100 && pct start 101
sleep 10
pct exec 100 -- bash -c "echo 'Post-reinicio privilegiado' > /mnt/shared/test_post_reboot.txt"
pct exec 101 -- bash -c "echo 'Post-reinicio no privilegiado' >> /mnt/shared/test_post_reboot.txt"
```

---

## 🔧 Solución de Problemas

### Error: "Permission denied" al escribir

**Síntomas:**
```bash
pct exec 101 -- bash -c "echo test > /mnt/shared/test.txt"
# bash: /mnt/shared/test.txt: Permission denied
```

**Diagnóstico:**
```bash
# Verificar permisos del directorio
ls -la /mnt/shared_data/
getfacl /mnt/shared_data/

# Verificar grupo en contenedor
pct exec 101 -- groups www-data
pct exec 101 -- id www-data
```

**Soluciones:**
1. **Falta grupo en contenedor:**
   ```bash
   pct exec 101 -- groupadd -g 1000 sharedfiles
   pct exec 101 -- usermod -aG sharedfiles www-data
   ```

2. **Faltan ACLs en host:**
   ```bash
   setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
   setfacl -d -m g:sharedfiles:rwx /mnt/shared_data
   ```

3. **Permisos base incorrectos:**
   ```bash
   chmod 2775 /mnt/shared_data
   chown root:sharedfiles /mnt/shared_data
   ```

### Error: "No such file or directory" al montar

**Síntomas:**
```bash
mount: /mnt/nfs_share: mount point does not exist
```

**Solución:**
```bash
# Crear punto de montaje
mkdir -p /mnt/nfs_share

# Verificar conectividad al servidor
ping 192.168.1.50
showmount -e 192.168.1.50
```

### Error: Archivos aparecen con propietario incorrecto

**Síntomas:**
```bash
ls -la /mnt/shared_data/
# -rw-r--r-- 1 100033 100033 5 sep 8 archivo.txt
```

**Diagnóstico:**
- UIDs/GIDs numéricos indican problema de mapeo
- 100033 = UID 33 (www-data) en contenedor no privilegiado

**Solución:**
```bash
# Verificar mapeo en configuración LXC
cat /etc/pve/lxc/101.conf | grep -E "(lxc.idmap|mp0)"

# Debe mostrar:
# lxc.idmap: u 0 100000 65536
# lxc.idmap: g 0 100000 65536
# mp0: /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1

# Corregir permisos con ACLs
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
```

### Error: Montaje no persiste tras reinicio

**Síntomas:**
- Tras reinicio, `df -h` no muestra el recurso montado
- Contenedores no pueden acceder a `/mnt/shared`

**Diagnóstico:**
```bash
# Verificar /etc/fstab
cat /etc/fstab | grep -E "(nfs|cifs)"

# Probar montaje manual
mount -a
```

**Solución:**
```bash
# Corregir entrada en /etc/fstab
# Para NFS:
192.168.1.50:/export/shared /mnt/nfs_share nfs rw,hard,nofail,_netdev 0 0

# Para Samba:
//192.168.1.60/shared /mnt/samba_share cifs credentials=/etc/cifs-credentials,_netdev,nofail 0 0

# Probar configuración
umount /mnt/nfs_share
mount /mnt/nfs_share
```

### Error: "Transport endpoint is not connected"

**Síntomas:**
```bash
ls /mnt/nfs_share
# ls: cannot access '/mnt/nfs_share': Transport endpoint is not connected
```

**Solución:**
```bash
# Desmontar forzosamente
umount -f /mnt/nfs_share

# O si no funciona:
umount -l /mnt/nfs_share  # lazy unmount

# Verificar conectividad
ping 192.168.1.50
showmount -e 192.168.1.50

# Remontar
mount /mnt/nfs_share
```

---

## 📋 Comandos de Referencia Rápida

### Gestión de Grupos
```bash
# Crear grupo con GID específico
groupadd -g 101000 sharedfiles

# Añadir usuario a grupo
usermod -aG sharedfiles usuario

# Ver grupos de un usuario
groups usuario
id usuario

# Ver miembros de un grupo
getent group sharedfiles
```

### Gestión de Permisos
```bash
# Permisos básicos con setgid
chmod 2775 /directorio
chown root:sharedfiles /directorio

# ACLs
setfacl -R -m g:sharedfiles:rwx /directorio    # Existente
setfacl -d -m g:sharedfiles:rwx /directorio    # Por defecto
getfacl /directorio                            # Ver ACLs
```

### Montajes de Red
```bash
# NFS
mount -t nfs servidor:/ruta /punto/montaje
showmount -e servidor

# Samba/CIFS  
mount -t cifs //servidor/recurso /punto/montaje -o credentials=/archivo
smbclient -L servidor
```

### Contenedores LXC
```bash
# Configurar punto de montaje
pct set ID -mp0 /host/path,mp=/container/path,backup=0,acl=1,shared=1

# Ejecutar comando en contenedor
pct exec ID -- comando

# Ver configuración
cat /etc/pve/lxc/ID.conf
```

---

## 🎯 Resumen Final

### Flujo Completo de Configuración

1. **Host**: Crear directorio + grupo + permisos + ACLs
2. **Recurso**: Montar NFS/Samba o usar directorio local  
3. **Contenedores**: Crear grupo + añadir usuarios
4. **Montaje**: Configurar puntos de montaje con `shared=1,acl=1`
5. **Verificar**: Probar escritura cruzada entre contenedores

### Puntos Clave

- **Grupo universal**: `sharedfiles` con GID 101000 en host, GID 1000 en contenedores no privilegiados
- **Setgid bit**: `chmod 2775` asegura herencia de grupo
- **ACLs**: Garantizan permisos consistentes independientemente de umask
- **shared=1**: Esencial para clusters y migraciones
- **_netdev**: Necesario en /etc/fstab para recursos de red

### Compatibilidad

Esta configuración funciona con:
- ✅ Contenedores privilegiados y no privilegiados
- ✅ NFS (todas las versiones)
- ✅ Samba/CIFS
- ✅ Directorios locales
- ✅ Clusters Proxmox
- ✅ Migraciones en vivo
- ✅ Backups con vzdump (excluye puntos de montaje)

Con esta guía tendrás un sistema robusto y escalable para compartir recursos entre tu host Proxmox y contenedores LXC, manteniendo permisos correctos y compatibilidad total.
```

