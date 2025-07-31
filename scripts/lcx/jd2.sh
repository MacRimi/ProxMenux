#!/bin/bash

# Script para instalar JDownloader en un contenedor LXC desde el host Proxmox
# Autor: MacRimi

# Mostrar lista de CTs
CT_LIST=$(pct list | awk 'NR>1 {print $1, $3}')
if [ -z "$CT_LIST" ]; then
    whiptail --title "Error" --msgbox "No hay contenedores LXC disponibles en el sistema." 8 50
    exit 1
fi

# Seleccionar CT
CTID=$(whiptail --title "Instalación de JDownloader" --menu "Selecciona el contenedor donde instalar JDownloader:" 20 60 10 $CT_LIST 3>&1 1>&2 2>&3)
if [ -z "$CTID" ]; then
    whiptail --title "Cancelado" --msgbox "No se ha seleccionado ningún contenedor." 8 40
    exit 1
fi

# Solicitar email
EMAIL=$(whiptail --title "Cuenta My JDownloader" --inputbox "Introduce tu correo electrónico para vincular JDownloader:" 10 60 3>&1 1>&2 2>&3)
if [ -z "$EMAIL" ]; then
    whiptail --title "Error" --msgbox "No se ha introducido ningún correo." 8 40
    exit 1
fi

# Solicitar contraseña con confirmación
while true; do
    PASSWORD=$(whiptail --title "Cuenta My JDownloader" --passwordbox "Introduce tu contraseña de My JDownloader:" 10 60 3>&1 1>&2 2>&3)
    [ -z "$PASSWORD" ] && whiptail --title "Error" --msgbox "No se ha introducido ninguna contraseña." 8 40 && exit 1

    CONFIRM=$(whiptail --title "Confirmación de contraseña" --passwordbox "Repite tu contraseña para confirmar:" 10 60 3>&1 1>&2 2>&3)
    [ "$PASSWORD" = "$CONFIRM" ] && break
    whiptail --title "Error" --msgbox "Las contraseñas no coinciden. Intenta de nuevo." 8 50
done

# Confirmación final
whiptail --title "Confirmar datos" --yesno "¿Deseas continuar con los siguientes datos?\n\nCorreo: $EMAIL\nContraseña: (oculta)\n\nEsta información se usará para vincular el contenedor con tu cuenta de My.JDownloader." 14 60
[ $? -ne 0 ] && whiptail --title "Cancelado" --msgbox "Instalación cancelada por el usuario." 8 40 && exit 1

clear
echo "🔍 Detectando sistema operativo dentro del CT $CTID..."
OS_ID=$(pct exec "$CTID" -- awk -F= '/^ID=/{gsub("\"",""); print $2}' /etc/os-release)

echo "Sistema detectado: $OS_ID"
echo "🧰 Preparando entorno..."

case "$OS_ID" in
  debian)
    # Repositorio adicional para Java 8
    pct exec "$CTID" -- wget -q http://www.mirbsd.org/~tg/Debs/sources.txt/wtf-bookworm.sources
    pct exec "$CTID" -- mv wtf-bookworm.sources /etc/apt/sources.list.d/
    pct exec "$CTID" -- apt update -y
    pct exec "$CTID" -- apt install -y openjdk-8-jdk wget
    JAVA_PATH="/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"
    ;;
  ubuntu)
    pct exec "$CTID" -- apt update -y
    pct exec "$CTID" -- apt install -y openjdk-8-jdk wget
    JAVA_PATH="/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"
    ;;
  alpine)
    pct exec "$CTID" -- apk update
    pct exec "$CTID" -- apk add openjdk8 wget
    JAVA_PATH="/usr/lib/jvm/java-1.8-openjdk/bin/java"
    ;;
  *)
    echo "❌ Sistema operativo no soportado: $OS_ID"
    exit 1
    ;;
esac

# Crear carpeta de instalación
pct exec "$CTID" -- mkdir -p /opt/jdownloader
pct exec "$CTID" -- bash -c 'cd /opt/jdownloader && curl -O https://installer.jdownloader.org/JDownloader.jar'

# Crear servicio según sistema
if [[ "$OS_TYPE" == "alpine" ]]; then
    # Servicio OpenRC para Alpine
    pct exec "$CTID" -- bash -c 'cat > /etc/init.d/jdownloader <<EOF
#!/sbin/openrc-run

command="/usr/bin/java"
command_args="-jar /opt/jdownloader/JDownloader.jar -norestart"
pidfile="/var/run/jdownloader.pid"
name="JDownloader"

depend() {
    need net
}
EOF'

    pct exec "$CTID" -- chmod +x /etc/init.d/jdownloader
    pct exec "$CTID" -- rc-update add jdownloader default
    pct exec "$CTID" -- rc-service jdownloader start

else
    # Servicio systemd para Debian/Ubuntu
    pct exec "$CTID" -- bash -c 'cat > /etc/systemd/system/jdownloader.service <<EOF
[Unit]
Description=JDownloader
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/jdownloader
ExecStart=/usr/bin/java -jar JDownloader.jar -norestart
Restart=always

[Install]
WantedBy=multi-user.target
EOF'

    pct exec "$CTID" -- systemctl daemon-reexec
    pct exec "$CTID" -- systemctl daemon-reload
    pct exec "$CTID" -- systemctl enable jdownloader
    pct exec "$CTID" -- systemctl start jdownloader
fi

echo -e "\n\033[1;32m✅ JDownloader se ha instalado correctamente en el CT $CTID y está funcionando como servicio.\033[0m"
echo -e "\n➡️ Accede a \033[1;34mhttps://my.jdownloader.org\033[0m con tu cuenta para gestionarlo.\n"
