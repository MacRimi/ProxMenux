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
CPython 3.11 and 3.13 WebSocket/image runtimes. It does not upload artifacts,
change release assets, or modify an installed Monitor.

This build lane is a prerequisite for ARM distribution, not a declaration of
PXVIRT or Raspberry Pi hardware compatibility. ARM release/checksum publication,
installer selection and validation on the maintainer's PXVIRT lab remain separate
steps before ARM installations can use a published image. The current release
and installer distribution remain unchanged.
