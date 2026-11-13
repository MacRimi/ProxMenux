"""Opt-in, bounded OCI blob cache; exported archives remain self-contained."""
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from oci_installation_state import private_directory
from oci_ui import translate, msg_warn

KIND = 'proxmenux.shared-oci-blobs.v1'
HEX = re.compile(r'[0-9a-f]{64}')
class CacheUnavailable(ValueError):
    """Optional cache failure; the caller can use a normal OCI transfer."""


REGISTRY_AUTH_FILE = '/etc/pve/priv/proxmenux/registry-auth.json'


def enabled():
    return os.environ.get('PROXMENUX_OCI_LAYER_CACHE') == '1'


def root_for(archive):
    override = os.environ.get('PROXMENUX_OCI_LAYER_CACHE_ROOT')
    return Path(override) if override else Path(archive).parent / '.proxmenux-oci-layer-cache'


def prepare(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('Unsafe shared layer cache')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Shared layer cache must be private and owned by this user')
    marker = root / 'format.json'
    # Inspect initialization files only after taking the bootstrap lock: an
    # atomic marker writer may currently own a temporary file in this directory.
    fd = os.open(root/'.bootstrap.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if marker.exists():
            if marker.is_symlink():
                raise ValueError('Unrecognized shared layer cache')
            saved = json.loads(marker.read_text())
            if not isinstance(saved, dict) or saved.get('kind') != KIND:
                raise ValueError('Unrecognized shared layer cache')
        else:
            if any(p.name != '.bootstrap.lock' for p in root.iterdir()):
                raise ValueError('Unrecognized shared layer cache')
            marker_fd, temporary = tempfile.mkstemp(prefix='.format-', dir=root)
            try:
                with os.fdopen(marker_fd, 'w') as output:
                    json.dump({'kind': KIND}, output)
                    output.flush(); os.fsync(output.fileno())
                os.replace(temporary, marker)
            finally:
                Path(temporary).unlink(missing_ok=True)
        for folder in (root/'sha256', root/'locks'):
            if folder.is_symlink():raise ValueError('Unsafe shared layer cache directory')
            private_directory(folder)
    finally:
        os.close(fd)


@contextmanager
def locked(root, exclusive=False, blob=None):
    lock = root/'locks'/(blob+'.lock') if blob else root/'cache.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive or blob else fcntl.LOCK_SH)
        yield
    finally:
        os.close(fd)


def hash_file(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        digest = hashlib.sha256()
        while chunk := os.read(fd, 4 * 1024**2):
            digest.update(chunk)
        return digest.hexdigest()
    finally:os.close(fd)


def validate_blobs(root, wanted=None):
    removed=[]
    for path in (root/'sha256').iterdir():
        if path.name.startswith('.seed-') and not path.is_symlink() and path.is_file():
            continue
        if not HEX.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            raise ValueError('Unsafe shared blob entry')
        if wanted is not None and 'sha256:' + path.name not in wanted:
            continue
        with locked(root,blob=path.name):
            if not path.exists():continue
            if hash_file(path)!=path.name:
                path.unlink();removed.append(path.name)
    return removed


def seed(root, archives, wanted):
    """An existing installed archive can provide unchanged, digest-checked blobs."""
    for path in archives:
        if not path:continue
        path=Path(path)
        if path.is_symlink()or not path.is_file():continue
        try:
            with tarfile.open(path) as tar:
                for item in tar.getmembers():
                    name=item.name.removeprefix('./');parts=name.split('/')
                    if len(parts)!=3 or parts[:2]!=['blobs','sha256'] or not HEX.fullmatch(parts[2])or not item.isfile():continue
                    if 'sha256:'+parts[2] not in wanted:continue
                    destination=root/'sha256'/parts[2]
                    with locked(root,blob=parts[2]):
                        if destination.exists():continue
                        fd,temporary=tempfile.mkstemp(dir=root/'sha256',prefix='.seed-')
                        temporary=Path(temporary)
                        try:
                            digest=hashlib.sha256();stream=tar.extractfile(item)
                            with os.fdopen(fd,'wb')as output:
                                while chunk:=stream.read(4*1024**2):output.write(chunk);digest.update(chunk)
                                output.flush();os.fsync(output.fileno())
                            if digest.hexdigest()==parts[2]:os.replace(temporary,destination)
                        finally:temporary.unlink(missing_ok=True)
        except (OSError,tarfile.TarError):
            # An optional seed is never a substitute for a verified new image.
            continue


def pack(layout, root, destination):
    index=json.loads((layout/'index.json').read_text())
    if len(index['manifests'])!=1:raise ValueError('A single-platform image is required')
    references=set()
    def read(digest):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):raise ValueError('Invalid shared blob digest')
        path=root/'sha256'/digest[7:]
        if path.stat().st_size>16*1024**2:raise ValueError('Oversized OCI metadata')
        content=path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=digest[7:]:raise ValueError('Invalid shared metadata')
        references.add(digest)
        return json.loads(content)
    manifest=read(index['manifests'][0]['digest'])
    read(manifest['config']['digest'])
    references.update(layer['digest']for layer in manifest['layers'])
    with tarfile.open(destination,'w',format=tarfile.PAX_FORMAT)as archive:
        def add(path, name):
            info = archive.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mode = 0o644
            with path.open('rb') as source:archive.addfile(info, source)
        for digest in sorted(references):
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):raise ValueError('Invalid shared blob digest')
            path=root/'sha256'/digest[7:]
            if path.is_symlink()or not path.is_file():raise ValueError('Unsafe shared blob')
            add(path,'blobs/sha256/'+digest[7:])
            os.utime(path,None)
        # Metadata last also makes accidental partial exports less reusable.
        for name in ('oci-layout', 'index.json'):
            add(layout/name, name)


def prune(root, maximum=None):
    root=Path(root)
    if not root.exists():return 0
    prepare(root)
    maximum = budget() if maximum is None else maximum
    if maximum < 0: raise ValueError('Invalid shared layer cache budget')
    with locked(root,exclusive=True):
        for temporary in (root/'sha256').glob('.seed-*'):
            if temporary.is_file() and not temporary.is_symlink():temporary.unlink()
        for temporary in root.glob('layout-*'):
            if temporary.is_dir() and not temporary.is_symlink():shutil.rmtree(temporary)
        files=sorted((p for p in(root/'sha256').iterdir()if HEX.fullmatch(p.name)and p.is_file()and not p.is_symlink()),key=lambda p:p.stat().st_mtime_ns)
        total=sum(p.stat().st_size for p in files);freed=0
        for path in files:
            if total<=maximum:break
            size=path.stat().st_size;path.unlink();freed+=size;total-=size
            # Exclusive cache lock excludes all users of these per-blob locks.
            (root/'locks'/(path.name+'.lock')).unlink(missing_ok=True)
    return freed


def check_space(cache, archive_directory, size, available=None):
    """Budget the seed/download blobs and exported tar before stopping guests."""
    available = available or (lambda path: shutil.disk_usage(path).free)
    same_device = cache.stat().st_dev == archive_directory.stat().st_dev
    needed = int(size * (2.2 if same_device else 1.1)) + 256 * 1024**2
    if available(archive_directory) < needed:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(archive_directory))
    if not same_device and available(cache) < int(size * 1.1) + 256 * 1024**2:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(cache))


def budget():
    value = int(os.environ.get('PROXMENUX_OCI_LAYER_CACHE_BYTES', str(2*1024**3)))
    if value < 0:
        raise ValueError('Invalid shared layer cache budget')
    return value


def pull(source, architecture, destination, archives, candidate, run, available=None):
    # Resolve at use time too: a login may have been saved since imports.
    # Keep an explicitly selected auth file, as the other image readers do.
    if not os.environ.get('REGISTRY_AUTH_FILE') and os.path.isfile(REGISTRY_AUTH_FILE):
        os.environ['REGISTRY_AUTH_FILE'] = REGISTRY_AUTH_FILE
    root = root_for(destination)
    try:
        maximum = budget()  # Validate before Skopeo; cleanup cannot mask its error.
        prepare(root)
        check_space(root, Path(destination).parent, int(candidate.get('size') or 0), available)
        try:
            with locked(root):
                wanted = set(candidate.get('layers') or [])
                if candidate.get('manifest_digest'):
                    wanted.add(candidate['manifest_digest'])
                validate_blobs(root, wanted)
                seed(root, archives, wanted)
                with tempfile.TemporaryDirectory(prefix='layout-', dir=root) as directory:
                    layout = Path(directory)
                    run(['skopeo','copy','--override-arch',architecture,'--dest-shared-blob-dir',str(root),source,'oci:'+str(layout)+':candidate'])
                    pack(layout, root, destination)
        finally:
            try:
                prune(root, maximum)
            except (OSError, ValueError, TypeError, KeyError):
                msg_warn(translate('The final cleanup did not complete:') + ' ' + str(root))
                # Optional maintenance must never replace the transfer error or
                # invalidate an already complete export. Retry on the next pull.
                pass
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError) as error:
        raise CacheUnavailable(str(error)) from error
