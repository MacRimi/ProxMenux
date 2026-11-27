# syntax=docker/dockerfile:1

# Stage 1: Base build environment matching the official Ubuntu 22.04 CI runner.
# Ubuntu 22.04 (glibc 2.35) ensures extracted APT binaries run on both PVE 8 and PVE 9.
FROM ubuntu:22.04 AS builder-env

ENV DEBIAN_FRONTEND=noninteractive \
    APPIMAGE_EXTRACT_AND_RUN=1 \
    NEXT_TELEMETRY_DISABLED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils \
        ca-certificates \
        curl \
        desktop-file-utils \
        file \
        gnupg \
        libglib2.0-0 \
        libnspr4 \
        libnss3 \
        python3 \
        python3-pip \
        python3-venv \
        squashfs-tools \
        wget \
        xz-utils \
        zsync \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && python3 -m pip install --no-cache-dir --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Build Next.js dashboard and package the AppImage.
FROM builder-env AS builder

WORKDIR /workspace

# Cache npm dependencies separately from source changes
COPY AppImage/package.json AppImage/package-lock.json ./AppImage/
RUN cd AppImage && npm install --legacy-peer-deps

# Copy only the repository trees consumed by AppImage/scripts/build_appimage.sh
COPY scripts/lxc/plain_lxc_pve.pl scripts/lxc/PlainLxcRemoval.pm ./scripts/lxc/
COPY scripts/global/proxmox_platform.py ./scripts/global/
COPY json/app_tracking_hints.json json/runtime_verified_overrides.json ./json/
COPY AppImage ./AppImage

RUN apt-get update -qq \
    && chmod +x AppImage/scripts/build_appimage.sh \
    && bash AppImage/scripts/build_appimage.sh \
    && bash -c 'source AppImage/scripts/appimage_arch.sh \
        && pmx_appimage_arch "$(uname -m)" \
        && cd AppImage/dist \
        && sha256sum *.AppImage > "ProxMenux-Monitor${PMX_APPIMAGE_SUFFIX}.AppImage.sha256"'

# Stage 3: Minimal export stage containing only the built AppImage and SHA256.
# Build & extract directly to host:
#   docker build --output ./AppImage/dist .
FROM scratch AS artifact

COPY --from=builder /workspace/AppImage/dist/ /
CMD ["/ProxMenux-Monitor"]
