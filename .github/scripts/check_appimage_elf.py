"""Reject foreign ELF files in a native AppDir without executing any binary."""
import argparse
from pathlib import Path
import struct


def check(directory, architecture):
    expected = {'x86_64': 62, 'aarch64': 183}[architecture]
    checked = 0
    for path in Path(directory).rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            header = stream.read(20)
        if not header.startswith(b'\x7fELF'):
            continue
        if len(header) != 20 or header[5] not in (1, 2):
            raise ValueError(f'Invalid ELF header: {path}')
        machine = struct.unpack('<H' if header[5] == 1 else '>H', header[18:20])[0]
        if machine != expected:
            raise ValueError(f'Foreign ELF machine {machine} in {architecture} AppDir: {path}')
        checked += 1
    if not checked:
        raise ValueError('No native ELF files found in AppDir')
    return checked


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('architecture', choices=('x86_64', 'aarch64'))
    args = parser.parse_args()
    print(f'PASS: {check(args.directory, args.architecture)} native ELF files')
