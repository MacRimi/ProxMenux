# 📘 Guía Completa: Compartir Recursos entre Proxmox Host y Contenedores LXC

## 📋 Índice

### 🎯 Conceptos Fundamentales
- [¿Qué son los permisos en Linux?](#qué-son-los-permisos-en-linux)
- [Usuarios y grupos en Linux](#usuarios-y-grupos-en-linux)
- [¿Qué son las ACLs?](#qué-son-las-acls)
- [Contenedores privilegiados vs no privilegiados](#contenedores-privilegiados-vs-no-privilegiados)

### 🛠️ Configuración Práctica
- [Crear directorio local compartido](#crear-directorio-local-compartido)
- [Configurar recurso NFS](#configurar-recurso-nfs)
- [Configurar recurso Samba](#configurar-recurso-samba)
- [Montar recursos en contenedores](#montar-recursos-en-contenedores)

### 🔧 Casos Prácticos
- [Ejemplo completo: NFS](#ejemplo-completo-nfs)
- [Ejemplo completo: Samba](#ejemplo-completo-samba)
- [Ejemplo completo: Directorio local](#ejemplo-completo-directorio-local)

### 🚨 Solución de Problemas
- [Errores comunes y soluciones](#errores-comunes-y-soluciones)
- [Comandos de verificación](#comandos-de-verificación)

---

## 🎯 Conceptos Fundamentales

### ¿Qué son los permisos en Linux?

En Linux, cada archivo y directorio tiene **permisos** que determinan quién puede hacer qué con ellos.

#### Tipos de permisos:
- **r (read/lectura)**: Ver el contenido
- **w (write/escritura)**: Modificar el contenido  
- **x (execute/ejecución)**: Ejecutar archivos o acceder a directorios

#### Niveles de permisos:
- **Usuario propietario (u)**: El dueño del archivo
- **Grupo propietario (g)**: El grupo al que pertenece el archivo
- **Otros (o)**: Todos los demás usuarios

#### Ejemplo práctico:
```bash
ls -l /mnt/shared_data/archivo.txt
-rw-rw-r-- 1 root sharedfiles 1024 sep 8 archivo.txt
```

**Desglose:**
- `-rw-rw-r--`: Permisos (explicado abajo)
- `root`: Usuario propietario
- `sharedfiles`: Grupo propietario
- `1024`: Tamaño en bytes

**Permisos desglosados:**
- Primer `-`: Tipo de archivo (- = archivo, d = directorio)
- `rw-`: Usuario puede leer y escribir, no ejecutar
- `rw-`: Grupo puede leer y escribir, no ejecutar
- `r--`: Otros solo pueden leer

### Usuarios y grupos en Linux

#### ¿Qué es un usuario?
Un **usuario** es una identidad en el sistema. Cada usuario tiene:
- **UID (User ID)**: Número único que lo identifica
- **Nombre**: Como `root`, `www-data`, `nextcloud`
- **Grupo principal**: Su grupo por defecto

#### ¿Qué es un grupo?
Un **grupo** es una colección de usuarios que comparten permisos. Cada grupo tiene:
- **GID (Group ID)**: Número único que lo identifica
- **Nombre**: Como `sharedfiles`, `www-data`, `users`

#### ¿Por qué usar grupos en Proxmox?
```bash
# Sin grupo común - PROBLEMÁTICO
# Host: archivo pertenece a "root"
# LXC1: usuario "www-data" no puede escribir
# LXC2: usuario "nextcloud" no puede escribir

# Con grupo común - SOLUCIÓN
# Host: archivo pertenece a grupo "sharedfiles"
# LXC1: "www-data" está en grupo "sharedfiles" → puede escribir
# LXC2: "nextcloud" está en grupo "sharedfiles" → puede escribir
```

#### Comandos útiles:
```bash
# Ver usuarios del sistema
cat /etc/passwd

# Ver grupos del sistema
cat /etc/group

# Ver a qué grupos pertenece un usuario
groups www-data

# Ver información completa de un usuario
id www-data
```

### ¿Qué son las ACLs?

**ACL (Access Control Lists)** son permisos **extendidos** que van más allá de los permisos básicos de Linux.

#### ¿Por qué necesitamos ACLs?
Los permisos básicos solo permiten **un usuario** y **un grupo** por archivo. Las ACLs permiten:
- Múltiples usuarios con diferentes permisos
- Múltiples grupos con diferentes permisos
- Permisos por defecto para archivos nuevos

#### Ejemplo sin ACLs (limitado):
```bash
# Solo podemos dar permisos a UN grupo
chown root:sharedfiles /mnt/shared_data
chmod 775 /mnt/shared_data
# ¿Qué pasa si necesitamos que otro grupo también tenga acceso?
```

#### Ejemplo con ACLs (flexible):
```bash
# Podemos dar permisos a MÚLTIPLES grupos
setfacl -m g:sharedfiles:rwx /mnt/shared_data
setfacl -m g:developers:rwx /mnt/shared_data
setfacl -m g:backup:r-x /mnt/shared_data
```

#### ¿Por qué son cruciales con NFS?
**NFS no entiende nombres, solo números (UID/GID)**:
```bash
# En el servidor NFS
# Usuario "www-data" tiene UID 33, GID 33

# En el cliente NFS  
# Usuario "www-data" tiene UID 33, GID 33
# ✅ Coinciden → funciona

# Pero si los números no coinciden:
# Servidor: "www-data" UID 33
# Cliente: "www-data" UID 1001  
# ❌ NFS ve usuarios diferentes → permisos rotos
```

**Las ACLs solucionan esto** asegurando que el grupo tenga permisos sin importar qué usuario específico cree el archivo.

### Contenedores privilegiados vs no privilegiados

#### Contenedor Privilegiado
- **UID/GID idénticos** al host
- `root` en contenedor = `root` en host (UID 0)
- **Más simple** de configurar
- **Menos seguro** (escape = root en host)

#### Contenedor No Privilegiado  
- **UID/GID desplazados** +100000
- `root` en contenedor (UID 0) = usuario 100000 en host
- **Más complejo** de configurar
- **Más seguro** (escape = usuario sin privilegios)

#### Mapeo de IDs en contenedores no privilegiados:
```bash
# Contenedor → Host
UID 0 → UID 100000      (root)
UID 33 → UID 100033     (www-data)  
UID 1000 → UID 101000   (usuario normal)

GID 0 → GID 100000      (root)
GID 33 → GID 100033     (www-data)
GID 1000 → GID 101000   (grupo personalizado)
```

---

## 🛠️ Configuración Práctica

### Crear directorio local compartido

#### Paso 1: Crear directorio y grupo en el host
```bash
# Crear directorio
mkdir -p /mnt/shared_data

# Crear grupo universal (si no existe)
groupadd -g 101000 sharedfiles 2>/dev/null || true

# Verificar que se creó correctamente
getent group sharedfiles
# Salida: sharedfiles:x:101000:
```

#### Paso 2: Configurar permisos base
```bash
# Asignar propietario y grupo
chown root:sharedfiles /mnt/shared_data

# Permisos con setgid (bit especial)
chmod 2775 /mnt/shared_data
```

**¿Qué significa `2775`?**
- **2**: Bit setgid → archivos nuevos heredan el grupo `sharedfiles`
- **7**: Propietario (root) → lectura, escritura, ejecución
- **7**: Grupo (sharedfiles) → lectura, escritura, ejecución  
- **5**: Otros → lectura, ejecución (sin escritura)

#### Paso 3: Aplicar ACLs
```bash
# ACLs para contenido existente
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data

# ACLs por defecto para contenido nuevo
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data

# Verificar ACLs aplicadas
getfacl /mnt/shared_data
```

### Configurar recurso NFS

#### Paso 1: Instalar servidor NFS
```bash
# En Debian/Ubuntu
apt update
apt install -y nfs-kernel-server

# En CentOS/RHEL
yum install -y nfs-utils
systemctl enable nfs-server
systemctl start nfs-server
```

#### Paso 2: Configurar exportación
```bash
# Editar archivo de exportaciones
nano /etc/exports

# Añadir línea (ajustar red según tu configuración)
/mnt/shared_data 192.168.1.0/24(rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000)
```

**Explicación de opciones:**
- `rw`: Lectura y escritura
- `sync`: Confirma escritura antes de responder
- `no_subtree_check`: Evita verificaciones innecesarias
- `all_squash`: Mapea todos los usuarios al anónimo
- `anonuid=0`: Usuario anónimo = root (UID 0)
- `anongid=101000`: Grupo anónimo = sharedfiles (GID 101000)

#### Paso 3: Activar exportación
```bash
# Recargar configuración
exportfs -ra

# Verificar exportaciones activas
exportfs -v
showmount -e localhost
```

#### Paso 4: Configurar firewall (si está activo)
```bash
# UFW (Ubuntu)
ufw allow from 192.168.1.0/24 to any port nfs

# Firewalld (CentOS)
firewall-cmd --permanent --add-service=nfs
firewall-cmd --reload
```

### Configurar recurso Samba

#### Paso 1: Instalar servidor Samba
```bash
# En Debian/Ubuntu
apt update
apt install -y samba samba-common-bin

# En CentOS/RHEL
yum install -y samba samba-client
systemctl enable smb nmb
systemctl start smb nmb
```

#### Paso 2: Configurar compartición
```bash
# Hacer backup de configuración original
cp /etc/samba/smb.conf /etc/samba/smb.conf.backup

# Editar configuración
nano /etc/samba/smb.conf
```

Añadir al final del archivo:
```ini
[shared_data]
    comment = Directorio compartido
    path = /mnt/shared_data
    browseable = yes
    read only = no
    valid users = @sharedfiles
    force group = sharedfiles
    create mask = 0664
    directory mask = 2775
    force create mode = 0664
    force directory mode = 2775
```

**Explicación de opciones:**
- `valid users = @sharedfiles`: Solo miembros del grupo pueden acceder
- `force group = sharedfiles`: Fuerza que archivos pertenezcan al grupo
- `create mask = 0664`: Permisos para archivos nuevos
- `directory mask = 2775`: Permisos para directorios nuevos (con setgid)

#### Paso 3: Crear usuario Samba
```bash
# Crear usuario del sistema (si no existe)
useradd -r -s /bin/false -g sharedfiles sambauser

# Crear usuario Samba
smbpasswd -a sambauser
# Te pedirá contraseña

# Añadir usuario existente al grupo
usermod -aG sharedfiles sambauser
```

#### Paso 4: Reiniciar servicios
```bash
# Verificar configuración
testparm

# Reiniciar servicios
systemctl restart smbd nmbd
```

### Montar recursos en contenedores

#### Paso 1: Configurar contenedor privilegiado

**¿Por qué necesitamos configurar grupos en contenedores privilegiados?**

Aunque los contenedores privilegiados comparten los mismos UID/GID que el host, **NO comparten automáticamente los grupos**. Cada contenedor tiene su propio `/etc/group`.

```bash
# 1.1 Entrar al contenedor
pct exec 100 -- bash

# 1.2 Crear grupo idéntico al host
groupadd -g 101000 sharedfiles

# ¿Por qué GID 101000?
# Porque es el mismo GID que usamos en el host
# En privilegiados: GID contenedor = GID host

# 1.3 Añadir usuarios relevantes al grupo
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Si tienes otros usuarios específicos
usermod -aG sharedfiles nextcloud 2>/dev/null || true
usermod -aG sharedfiles jellyfin 2>/dev/null || true

# 1.4 Verificar membresía
groups root
groups www-data

# 1.5 Salir del contenedor
exit
```

#### Paso 2: Configurar contenedor no privilegiado

```bash
# 2.1 Entrar al contenedor
pct exec 101 -- bash

# 2.2 Crear grupo con GID mapeado
groupadd -g 1000 sharedfiles
# Importante: GID 1000 en contenedor = GID 101000 en host

# 2.3 Listar todos los usuarios disponibles
echo "Usuarios disponibles en el contenedor:"
awk -F: '$3>=1000 && $1!="nobody" {print "- " $1 " (UID: " $3 ")"}' /etc/passwd

# También mostrar usuarios del sistema comunes
echo "Usuarios del sistema comunes:"
for user in root www-data nginx apache mysql postgres redis; do
    if id "$user" >/dev/null 2>&1; then
        echo "- $user ($(id -u $user))"
    fi
done

# 2.4 Añadir usuarios al grupo
# Usuarios básicos siempre necesarios
usermod -aG sharedfiles root
usermod -aG sharedfiles www-data

# Usuarios específicos según aplicaciones instaladas
usermod -aG sharedfiles nextcloud 2>/dev/null || true
usermod -aG sharedfiles jellyfin 2>/dev/null || true
usermod -aG sharedfiles plex 2>/dev/null || true
usermod -aG sharedfiles mysql 2>/dev/null || true
usermod -aG sharedfiles postgres 2>/dev/null || true

# 2.5 Verificar configuración
echo "Verificando configuración de usuarios:"
for user in root www-data nextcloud jellyfin; do
    if id "$user" >/dev/null 2>&1; then
        echo "Usuario $user:"
        id "$user"
        echo ""
    fi
done

# 2.6 Salir del contenedor
exit
```

**Comando para añadir TODOS los usuarios automáticamente:**
```bash
# Dentro del contenedor no privilegiado
# Añadir todos los usuarios con UID >= 1000 al grupo sharedfiles
awk -F: '$3>=1000 && $1!="nobody" {print $1}' /etc/passwd | while read user; do
    usermod -aG sharedfiles "$user"
    echo "Añadido $user al grupo sharedfiles"
done

# Añadir usuarios del sistema importantes
for user in root www-data nginx apache mysql postgres redis; do
    if id "$user" >/dev/null 2>&1; then
        usermod -aG sharedfiles "$user"
        echo "Añadido $user al grupo sharedfiles"
    fi
done
```

#### Paso 3: Montar directorios en contenedores

```bash
# 3.1 Para contenedor privilegiado (ID 100)
pct set 100 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1

# 3.2 Para contenedor no privilegiado (ID 101)  
pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1

# 3.3 Reiniciar contenedores para activar montajes
pct reboot 100
pct reboot 101

# Esperar a que arranquen
sleep 15
```

**Explicación de parámetros:**
- `mp0`: Punto de montaje 0 (puedes usar mp1, mp2, etc.)
- `/mnt/shared_data`: Ruta en el host
- `mp=/mnt/shared`: Ruta dentro del contenedor
- `backup=0`: Excluir del backup automático
- `acl=1`: Habilitar soporte para ACLs
- `shared=1`: **IMPORTANTE** - Permite migración en clusters sin copiar datos

---

## 🔧 Casos Prácticos

### Ejemplo completo: NFS

#### Escenario: Servidor NFS en host, cliente en contenedor

**Paso 1: Preparar servidor NFS en host**
```bash
# Crear directorio y configurar permisos
mkdir -p /mnt/nfs_export
groupadd -g 101000 sharedfiles 2>/dev/null || true
chown root:sharedfiles /mnt/nfs_export
chmod 2775 /mnt/nfs_export
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_export
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_export

# Configurar exportación NFS
echo "/mnt/nfs_export 192.168.1.0/24(rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000)" >> /etc/exports
exportfs -ra
```

**Paso 2: Montar NFS desde otro host**
```bash
# En otro servidor Proxmox
mkdir -p /mnt/nfs_client

# Montar temporalmente para probar
mount -t nfs 192.168.1.50:/mnt/nfs_export /mnt/nfs_client

# Hacer persistente tras reinicio
echo "192.168.1.50:/mnt/nfs_export /mnt/nfs_client nfs rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2,_netdev 0 0" >> /etc/fstab
```

**Explicación del fstab:**
- `rw`: Lectura y escritura
- `hard`: Reintentar indefinidamente si hay problemas
- `nofail`: No bloquear arranque si no está disponible
- `rsize/wsize=131072`: Tamaño de buffer (128KB) para mejor rendimiento
- `timeo=600`: Timeout de 60 segundos (600 décimas)
- `retrans=2`: Reintentar 2 veces antes de timeout
- `_netdev`: Esperar a que la red esté lista
- `0 0`: No hacer dump ni fsck (siempre para recursos de red)

**Paso 3: Configurar contenedor para usar NFS**
```bash
# Configurar permisos en el host cliente
groupadd -g 101000 sharedfiles 2>/dev/null || true
chown root:sharedfiles /mnt/nfs_client
setfacl -R -m g:sharedfiles:rwx /mnt/nfs_client
setfacl -d -m g:sharedfiles:rwx /mnt/nfs_client

# Montar en contenedor
pct set 102 -mp0 /mnt/nfs_client,mp=/mnt/shared_nfs,backup=0,acl=1,shared=1
pct reboot 102
```

### Ejemplo completo: Samba

#### Escenario: Montar recurso Samba externo en host y compartir con contenedores

**Paso 1: Montar Samba en host**
```bash
# Instalar cliente Samba
apt install -y cifs-utils

# Crear directorio de montaje
mkdir -p /mnt/samba_share

# Crear archivo de credenciales
cat > /etc/cifs-credentials << EOF
username=tu_usuario
password=tu_contraseña
domain=tu_dominio
EOF

# Proteger credenciales
chmod 600 /etc/cifs-credentials

# Montar temporalmente para probar
mount -t cifs //192.168.1.60/shared_folder /mnt/samba_share -o credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0

# Hacer persistente
echo "//192.168.1.60/shared_folder /mnt/samba_share cifs credentials=/etc/cifs-credentials,iocharset=utf8,vers=3.0,_netdev,nofail 0 0" >> /etc/fstab
```

**Paso 2: Configurar permisos para contenedores**
```bash
# Configurar grupo y permisos
groupadd -g 101000 sharedfiles 2>/dev/null || true
chown root:sharedfiles /mnt/samba_share
chmod 2775 /mnt/samba_share
setfacl -R -m g:sharedfiles:rwx /mnt/samba_share
setfacl -d -m g:sharedfiles:rwx /mnt/samba_share
```

**Paso 3: Montar en contenedores**
```bash
# Contenedor privilegiado
pct set 103 -mp0 /mnt/samba_share,mp=/mnt/samba,backup=0,acl=1,shared=1

# Contenedor no privilegiado  
pct set 104 -mp0 /mnt/samba_share,mp=/mnt/samba,backup=0,acl=1,shared=1

# Reiniciar contenedores
pct reboot 103 104
```

### Ejemplo completo: Directorio local

#### Escenario: Compartir directorio local del host con múltiples contenedores

**Paso 1: Crear y configurar directorio**
```bash
# Crear directorio principal
mkdir -p /mnt/local_shared

# Crear subdirectorios por aplicación
mkdir -p /mnt/local_shared/{nextcloud,jellyfin,backup,common}

# Configurar permisos base
groupadd -g 101000 sharedfiles 2>/dev/null || true
chown -R root:sharedfiles /mnt/local_shared
chmod -R 2775 /mnt/local_shared

# Aplicar ACLs recursivamente
setfacl -R -m g:sharedfiles:rwx /mnt/local_shared
setfacl -R -d -m g:sharedfiles:rwx /mnt/local_shared
```

**Paso 2: Montar en múltiples contenedores**
```bash
# Nextcloud (contenedor 105) - acceso completo
pct set 105 -mp0 /mnt/local_shared,mp=/mnt/shared,backup=0,acl=1,shared=1

# Jellyfin (contenedor 106) - solo su directorio
pct set 106 -mp0 /mnt/local_shared/jellyfin,mp=/mnt/media,backup=0,acl=1,shared=1

# Backup (contenedor 107) - acceso de solo lectura
pct set 107 -mp0 /mnt/local_shared,mp=/mnt/backup_source,backup=0,acl=1,shared=1,ro=1

# Reiniciar todos
pct reboot 105 106 107
```

---

## 🚨 Solución de Problemas

### Errores comunes y soluciones

#### Error: "Permission denied" al escribir desde contenedor no privilegiado

**Síntomas:**
```bash
# Dentro del contenedor
touch /mnt/shared/test.txt
# touch: cannot touch '/mnt/shared/test.txt': Permission denied
```

**Diagnóstico:**
```bash
# En el host, verificar permisos
ls -la /mnt/shared_data/
getfacl /mnt/shared_data/

# En el contenedor, verificar usuario
id
groups
```

**Soluciones:**
```bash
# 1. Verificar que el grupo existe en el contenedor
pct exec 101 -- getent group sharedfiles

# 2. Si no existe, crearlo
pct exec 101 -- groupadd -g 1000 sharedfiles

# 3. Añadir usuario al grupo
pct exec 101 -- usermod -aG sharedfiles www-data

# 4. Verificar ACLs en el host
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data
```

#### Error: "Stale file handle" en montajes NFS

**Síntomas:**
```bash
ls /mnt/nfs_mount
# ls: cannot access '/mnt/nfs_mount': Stale file handle
```

**Solución:**
```bash
# Desmontar forzadamente
umount -f /mnt/nfs_mount

# Limpiar cache NFS
echo 3 > /proc/sys/vm/drop_caches

# Volver a montar
mount -t nfs servidor:/export /mnt/nfs_mount
```

#### Error: Archivos aparecen con propietario incorrecto

**Síntomas:**
```bash
ls -l /mnt/shared/
# -rw-r--r-- 1 100033 100033 1024 sep 8 archivo.txt
```

**Explicación:**
El archivo muestra UID/GID numéricos porque el sistema no encuentra nombres correspondientes.

**Solución:**
```bash
# Verificar mapeo de IDs
# En contenedor no privilegiado: UID 33 → Host UID 100033

# Crear grupo con GID correcto en host si es necesario
groupadd -g 100033 container-www-data

# O mejor, usar el grupo universal
chown -R root:sharedfiles /mnt/shared/
```

#### Error: "Transport endpoint is not connected" en Samba

**Síntomas:**
```bash
ls /mnt/samba_mount
# ls: cannot access '/mnt/samba_mount': Transport endpoint is not connected
```

**Solución:**
```bash
# Desmontar
umount /mnt/samba_mount

# Verificar conectividad
ping servidor_samba
smbclient -L //servidor_samba -U usuario

# Remontar con opciones específicas
mount -t cifs //servidor/share /mnt/samba_mount -o username=user,vers=3.0,iocharset=utf8
```

### Comandos de verificación

#### Verificar configuración de permisos
```bash
# Verificar permisos básicos
ls -la /mnt/shared_data/

# Verificar ACLs
getfacl /mnt/shared_data/

# Verificar grupos
getent group sharedfiles

# Verificar usuarios en grupo
getent group sharedfiles | cut -d: -f4
```

#### Verificar montajes NFS
```bash
# Ver exportaciones disponibles
showmount -e servidor_nfs

# Ver montajes activos
mount | grep nfs
df -h | grep nfs

# Verificar estadísticas NFS
nfsstat -c  # Cliente
nfsstat -s  # Servidor
```

#### Verificar montajes Samba
```bash
# Ver recursos compartidos disponibles
smbclient -L //servidor_samba -U usuario

# Ver montajes activos
mount | grep cifs
df -h | grep cifs

# Probar conectividad
smbclient //servidor/share -U usuario
```

#### Verificar configuración de contenedores
```bash
# Ver configuración de contenedor
cat /etc/pve/lxc/101.conf | grep mp

# Ver montajes dentro del contenedor
pct exec 101 -- df -h
pct exec 101 -- mount | grep /mnt

# Verificar permisos dentro del contenedor
pct exec 101 -- ls -la /mnt/shared/
pct exec 101 -- getfacl /mnt/shared/
```

#### Probar escritura desde contenedores
```bash
# Crear archivo de prueba desde contenedor privilegiado
pct exec 100 -- bash -c 'echo "Prueba desde privilegiado" > /mnt/shared/test_privileged.txt'

# Crear archivo de prueba desde contenedor no privilegiado
pct exec 101 -- bash -c 'echo "Prueba desde no privilegiado" > /mnt/shared/test_unprivileged.txt'

# Verificar en el host
ls -la /mnt/shared_data/test_*.txt
getfacl /mnt/shared_data/test_*.txt
```

#### Script de diagnóstico completo
```bash
#!/bin/bash
# Guardar como: diagnostico_permisos.sh

echo "=== DIAGNÓSTICO DE PERMISOS COMPARTIDOS ==="
echo

echo "1. Verificando directorio compartido:"
ls -la /mnt/shared_data/
echo

echo "2. Verificando ACLs:"
getfacl /mnt/shared_data/
echo

echo "3. Verificando grupo sharedfiles:"
getent group sharedfiles
echo

echo "4. Verificando montajes NFS:"
mount | grep nfs
echo

echo "5. Verificando montajes Samba:"
mount | grep cifs
echo

echo "6. Verificando configuración de contenedores:"
for ct in $(pct list | awk 'NR>1 {print $1}'); do
    echo "Contenedor $ct:"
    grep mp /etc/pve/lxc/$ct.conf 2>/dev/null || echo "  Sin montajes configurados"
done
echo

echo "7. Probando escritura desde host:"
if touch /mnt/shared_data/test_host.txt 2>/dev/null; then
    echo "  ✅ Host puede escribir"
    rm -f /mnt/shared_data/test_host.txt
else
    echo "  ❌ Host NO puede escribir"
fi

echo
echo "=== FIN DEL DIAGNÓSTICO ==="
```

---

## 📝 Resumen de mejores prácticas

### ✅ Configuración correcta
1. **Usar grupo universal** `sharedfiles` con GID 101000
2. **Aplicar setgid** (chmod 2775) para herencia automática
3. **Configurar ACLs** por defecto para garantizar permisos
4. **Usar shared=1** en montajes para compatibilidad con clusters
5. **Excluir de backups** (backup=0) para evitar duplicación
6. **Habilitar ACLs** (acl=1) en montajes de contenedores

### ❌ Errores a evitar
1. No crear el grupo en los contenedores
2. Olvidar el bit setgid (2775)
3. No aplicar ACLs por defecto
4. Usar rutas diferentes entre nodos del cluster
5. No configurar _netdev en fstab para recursos de red
6. Usar fsck (último número ≠ 0) en recursos de red

### 🔧 Comandos esenciales
```bash
# Configuración básica de directorio compartido
mkdir -p /mnt/shared_data
groupadd -g 101000 sharedfiles
chown root:sharedfiles /mnt/shared_data
chmod 2775 /mnt/shared_data
setfacl -R -m g:sharedfiles:rwx /mnt/shared_data
setfacl -d -m g:sharedfiles:rwx /mnt/shared_data

# Montaje en contenedor
pct set ID -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1,shared=1

# Configuración en contenedor no privilegiado
pct exec ID -- groupadd -g 1000 sharedfiles
pct exec ID -- usermod -aG sharedfiles www-data
```

Esta guía te permitirá configurar correctamente recursos compartidos entre Proxmox y contenedores LXC, garantizando permisos adecuados y compatibilidad con clusters.
```
