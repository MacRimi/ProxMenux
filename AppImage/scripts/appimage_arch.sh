#!/bin/bash
# Shared native build/runtime architecture names. No emulated cross-builds.
pmx_appimage_arch() {
    case "$1" in
        x86_64|amd64)
            PMX_APPIMAGE_ARCH=x86_64
            PMX_APPIMAGE_TRIPLET=x86_64-linux-gnu
            PMX_APPIMAGE_SUFFIX=""
            ;;
        aarch64|arm64)
            PMX_APPIMAGE_ARCH=aarch64
            PMX_APPIMAGE_TRIPLET=aarch64-linux-gnu
            PMX_APPIMAGE_SUFFIX=-aarch64
            ;;
        *)
            echo "Unsupported Monitor AppImage architecture: $1" >&2
            return 1
            ;;
    esac
}
