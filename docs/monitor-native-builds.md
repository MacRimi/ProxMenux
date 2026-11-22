# Native Monitor AppImage builds

The builder selects its native architecture using `uname -m`. Supported targets
are x86_64 and aarch64 (ARM64). It selects matching appimagetool executables,
separate download caches, manylinux wheels and GNU library paths. Cross-building
by overriding a target variable is intentionally unsupported: APT packages and
other native Python dependencies must also match the build machine.

Run `bash AppImage/scripts/build_appimage.sh` on a Linux builder with Node.js,
Python/pip, APT and the usual AppImage build dependencies. AMD64 keeps the existing
`ProxMenux-VERSION.AppImage` name; ARM64 produces
`ProxMenux-VERSION-aarch64.AppImage`.

The native validation workflow builds both architectures on GitHub's native
Ubuntu 22.04 runners, extracts each AppImage without FUSE, and imports its bundled
CPython 3.11 and 3.13 WebSocket/image runtimes, including the extracted launcher
with only its final server execution intercepted. It does not upload artifacts,
change release assets, or modify an installed Monitor.

This build lane is a prerequisite for ARM distribution, not a declaration of
PXVIRT or Raspberry Pi hardware compatibility. ARM release/checksum publication,
installer selection and validation on the maintainer's PXVIRT lab remain separate
steps before ARM installations can use a published image. The current release
and installer distribution remain unchanged.

## Borg host backups on ARM64

Borg 1.2.8 publishes an AMD64 standalone executable but no ARM64 equivalent.
ARM64 builds therefore include a small adapter that uses `/usr/bin/borg` from
the host's native `borgbackup` package. Without that package it exits with a
clear error; it never runs the AMD64 binary. The host-backup helper likewise
refuses AMD64 cached/downloaded binaries on non-AMD64 hosts. The existing AMD64
standalone binary and checksum remain unchanged. Operators must install their
native distro package separately; this build does not install it on the host.

ARM64 uses the official versioned appimagetool 1.9.1 with SHA256 verification;
the existing AMD64 packaging tool remains unchanged.
