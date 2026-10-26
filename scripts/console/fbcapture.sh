#!/bin/sh
# Save the Linux framebuffer as a PNG, to review the console monitor as it
# really looks on HDMI/VGA (/dev/vcsN holds only text: no glyph shapes, no
# colours). Read-only: it reads the framebuffer device and its sysfs geometry
# and never writes to a terminal. Needs read access to /dev/fbN (root).
#
# Usage: fbcapture.sh [-f fbN] OUTPUT.png    (OUTPUT "-" = stdout, never a tty)
#
# Geometry is read on every run from /sys/class/graphics/fbN/virtual_size,
# stride and bits_per_pixel; the stride may be wider than width x bytes per
# pixel. Pixel formats: 32 bpp XRGB8888, 24 bpp RGB888 and 16 bpp RGB565,
# little endian (what efifb, simpledrm and the DRM fbdev emulation expose).
# FBCAPTURE_SYSFS and FBCAPTURE_DEVICE override the sysfs directory and the
# device node, so tests can use a fake framebuffer. Needs python3 (stdlib).

set -eu

die() {
    echo "fbcapture: $*" >&2
    exit 1
}

usage() {
    echo "usage: fbcapture.sh [-f fbN] OUTPUT.png  (OUTPUT - writes the PNG to stdout)" >&2
    exit 2
}

is_count() {
    case $1 in
        '' | *[!0-9]* | 0*) return 1 ;;
    esac
    [ "${#1}" -le 6 ]
}

attribute() {
    cat "$sysfs/$1" 2>/dev/null || die "cannot read $sysfs/$1"
}

fb=fb0
while getopts f:h opt; do
    case $opt in
        f) fb=$OPTARG ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))
[ "$#" -eq 1 ] || usage
output=$1
case $fb in
    fb[0-9] | fb[0-9][0-9]) ;;
    *) die "not a framebuffer name: $fb (expected fb0, fb1, ...)" ;;
esac

sysfs=${FBCAPTURE_SYSFS:-/sys/class/graphics/$fb}
device=${FBCAPTURE_DEVICE:-/dev/$fb}

size=$(attribute virtual_size)
stride=$(attribute stride)
bpp=$(attribute bits_per_pixel)
width=${size%%,*}
height=${size#*,}
if [ "$width,$height" != "$size" ] || ! is_count "$width" || ! is_count "$height" ||
    [ "$width" -gt 16384 ] || [ "$height" -gt 16384 ]; then
    die "unexpected virtual_size: $size"
fi
is_count "$stride" || die "unexpected stride: $stride"
case $bpp in
    16 | 24 | 32) ;;
    *) die "unsupported bits_per_pixel: $bpp (16, 24 or 32)" ;;
esac
[ "$stride" -ge $((width * bpp / 8)) ] || die "stride $stride is narrower than $width pixels at $bpp bpp"
[ -r "$device" ] || die "cannot read $device (run as root)"

if [ "$output" = - ]; then
    if [ -t 1 ]; then
        die "refusing to write a PNG to a terminal"
    fi
elif [ -L "$output" ] || { [ -e "$output" ] && [ ! -f "$output" ]; }; then
    die "$output exists and is not a regular file"
fi
command -v python3 >/dev/null 2>&1 || die "python3 is required"

exec python3 -I - "$device" "$width" "$height" "$stride" "$bpp" "$output" <<'PY'
import os
import stat
import struct
import sys
import zlib

device, output = sys.argv[1], sys.argv[6]
width, height, stride, bpp = (int(value) for value in sys.argv[2:6])
pixel_bytes = bpp // 8
expected = stride * height

raw = bytearray()
with open(device, "rb", buffering=0) as stream:
    while len(raw) < expected:
        block = stream.read(expected - len(raw))
        if not block:
            break
        raw += block
if len(raw) < expected:
    sys.exit(f"fbcapture: {device} gave {len(raw)} bytes, expected {expected} "
             f"({height} rows of {stride})")


def rgb(line):
    row = bytearray(width * 3)
    if bpp == 32:    # XRGB8888 little endian: B G R X
        row[0::3], row[1::3], row[2::3] = line[2::4], line[1::4], line[0::4]
    elif bpp == 24:  # RGB888 little endian: B G R
        row[0::3], row[1::3], row[2::3] = line[2::3], line[1::3], line[0::3]
    else:            # RGB565 little endian
        for index, (pixel,) in enumerate(struct.iter_unpack("<H", line)):
            row[3 * index:3 * index + 3] = bytes((
                (pixel >> 11) * 255 // 31, (pixel >> 5 & 63) * 255 // 63, (pixel & 31) * 255 // 31))
    return row


compressor = zlib.compressobj(6)
data = bytearray()
for y in range(height):
    start = y * stride
    data += compressor.compress(b"\x00" + rgb(raw[start:start + width * pixel_bytes]))
data += compressor.flush()


def chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", bytes(data)) + chunk(b"IEND", b""))

if output == "-":
    sys.stdout.buffer.write(png)
else:
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NOCTTY, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            sys.exit(f"fbcapture: {output} is not a regular file")
        os.ftruncate(descriptor, 0)
        stream.write(png)
print(f"fbcapture: {device} {width}x{height} stride {stride} {bpp} bpp -> {output}",
      file=sys.stderr)
PY
