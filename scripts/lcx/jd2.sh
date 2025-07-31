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

# Solicitar contraseña
while true; do
    PASSWORD=$(whiptail --title "Cuenta My JDownloader" --passwordbox "Introduce tu contraseña de My JDownloader:" 10 60 3>&1 1>&2 2>&3)
    if [ -z "$PASSWORD" ]; then
        whiptail --title "Error" --msgbox "No se ha introducido ninguna contraseña." 8 40
        exit 1
    fi

    CONFIRM_PASSWORD=$(whiptail --title "Confirmación de contraseña" --passwordbox "Repite tu contraseña para confirmar:" 10 60 3>&1 1>&2 2>&3)

    if [ "$PASSWORD" = "$CONFIRM_PASSWORD" ]; then
        break
    else
        whiptail --title "Error" --msgbox "Las contraseñas no coinciden. Intenta de nuevo." 8 50
    fi
done

# Confirmar datos
whiptail --title "Confirmar datos" --yesno "¿Deseas continuar con los siguientes datos?\n\nCorreo: $EMAIL\nContraseña: (establecida)\n\nEsta información se usará para vincular el contenedor con tu cuenta de My.JDownloader." 14 60
if [ $? -ne 0 ]; then
    whiptail --title "Cancelado" --msgbox "Instalación cancelada por el usuario." 8 40
    exit 1
fi

echo
echo "Instalando JDownloader en CT $CTID..."
echo

# Añadir repositorio alternativo para Java 8 y actualizar
pct exec "$CTID" -- wget -q http://www.mirbsd.org/~tg/Debs/sources.txt/wtf-bookworm.sources
pct exec "$CTID" -- mv wtf-bookworm.sources /etc/apt/sources.list.d/
pct exec "$CTID" -- apt update -y
pct exec "$CTID" -- apt install -y openjdk-8-jdk wget

# Crear carpeta y descargar JDownloader
pct exec "$CTID" -- mkdir -p /root/jdownloader
pct exec "$CTID" -- bash -c "cd /root/jdownloader && wget -q http://installer.jdownloader.org/JDownloader.jar"

# Crear archivo de configuración JSON para My JDownloader
pct exec "$CTID" -- bash -c "mkdir -p /root/jdownloader/cfg && cat > /root/jdownloader/cfg/org.jdownloader.api.myjdownloader.MyJDownloaderSettings.json" <<EOF

{
  "email" : "$EMAIL",
  "password" : "$PASSWORD",
  "enabled" : true
}
EOF

# Crear servicio systemd
pct exec "$CTID" -- bash -c "cat > /etc/systemd/system/jdownloader.service <<EOF
[Unit]
Description=JDownloader Headless
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/jdownloader
ExecStart=/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java -jar JDownloader.jar -norestart
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF"

# Activar y arrancar servicio
pct exec "$CTID" -- systemctl daemon-reexec
pct exec "$CTID" -- systemctl daemon-reload
pct exec "$CTID" -- systemctl enable jdownloader
pct exec "$CTID" -- systemctl start jdownloader

echo -e "\n\033[1;32m✅ JDownloader se ha instalado y está funcionando como servicio en el CT $CTID.\033[0m"
echo -e "\nPuedes acceder a \033[1;34mhttps://my.jdownloader.org\033[0m con tu cuenta para gestionarlo.\n"
