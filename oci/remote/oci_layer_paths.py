"""Canonicalize benign absolute tar member names for Proxmox's OCI reader.

Never extract a layer onto the host. Keep the verified publisher archive intact;
only the temporary import copy has rewritten tar headers and corresponding OCI
content digests. Parent traversal, ambiguous names and absolute hardlinks are
refused rather than made acceptable to the native extractor.
"""
from contextlib import contextmanager
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading

from oci_runtime import _json_member, _blob_name, _member, RuntimeResolutionError
from oci_ui import translate
from verify_oci_archive import verify_archive


def filehash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(item):
    name = item.name
    if '..' in name.split('/') or '\x00' in name:
        raise RuntimeResolutionError(translate('Unsafe OCI layer path:') + ' ' + repr(name))
    if item.islnk() and (item.linkname.startswith('/') or '..' in item.linkname.split('/')):
        raise RuntimeResolutionError(translate('Unsafe OCI layer path:') + ' ' + repr(item.linkname))
    if name.startswith('/'):
        # Do not invent import semantics for special files or link headers.
        if not (item.isdir() or item.isfile()) or item.sparse is not None:
            raise RuntimeResolutionError(translate('Unsafe OCI layer path:') + ' ' + repr(name))
        name = name.lstrip('/') or '.'
        if name == '.' and not item.isdir():
            raise RuntimeResolutionError(translate('Unsafe OCI layer path:') + ' ' + repr(item.name))
    return name


@contextmanager
def layer_tar(archive, descriptor):
    stream = archive.extractfile(_member(archive, _blob_name(descriptor['digest'])))
    media = descriptor.get('mediaType', '')
    if 'zstd' not in media:
        with stream, tarfile.open(fileobj=stream, mode='r|gz' if 'gzip' in media else 'r|') as layer:
            yield layer
        return
    process = subprocess.Popen(['zstd', '-dc'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    errors = []
    def feed():
        try:
            shutil.copyfileobj(stream, process.stdin)
        except (OSError, BrokenPipeError) as error:
            errors.append(error)
        finally:
            process.stdin.close(); stream.close()
    thread = threading.Thread(target=feed, daemon=True); thread.start()
    complete = False
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as layer:
            yield layer
        # Drain padding so the decompressor/feeder cannot block on a full pipe.
        while process.stdout.read(1024*1024):
            pass
        complete = True
    finally:
        process.stdout.close()
        if not complete and process.poll() is None:
            process.terminate()
        code = process.wait(); thread.join()
    if code or errors:
        raise RuntimeResolutionError(translate('Cannot prepare the OCI archive:') + ' zstd')


def changed_layers(source):
    changed = []
    with tarfile.open(source) as archive:
        index = _json_member(archive, 'index.json')
        if len(index.get('manifests', [])) != 1:
            raise RuntimeResolutionError(translate('The OCI archive does not contain exactly one manifest'))
        manifest = _json_member(archive, _blob_name(index['manifests'][0]['digest']))
        for descriptor in manifest['layers']:
            names, touched = {}, False
            with layer_tar(archive, descriptor) as layer:
                for item in layer:
                    name = canonical(item)
                    key = '/'.join(part for part in name.split('/') if part not in ('', '.'))
                    if key in names and names[key] != item.name and (names[key].startswith('/') or item.name.startswith('/')):
                        raise RuntimeResolutionError(translate('Unsafe OCI layer path:') + ' ' + repr(item.name))
                    names[key] = item.name
                    touched |= name != item.name
            changed.append(touched)
    return changed


class HashWriter:
    def __init__(self, output):
        self.output = output; self.hash = hashlib.sha256()
    def write(self, data):
        self.hash.update(data); return self.output.write(data)


def prepare(source, destination):
    """Return an integrity-bound import descriptor, or None for canonical images."""
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise RuntimeResolutionError(translate('Cannot prepare the OCI archive:') + ' ' + str(source))
    changes = changed_layers(source)
    if not any(changes):
        return None
    verify_archive(source)
    source_hash = filehash(source)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(str(destination))
    partial = destination.with_name(destination.name + '.partial')
    try:
        with tempfile.TemporaryDirectory(prefix='oci-paths-', dir=destination.parent) as folder, tarfile.open(source) as archive:
            index = _json_member(archive, 'index.json')
            manifest = _json_member(archive, _blob_name(index['manifests'][0]['digest']))
            config = _json_member(archive, _blob_name(manifest['config']['digest']))
            diffs = config.get('rootfs', {}).get('diff_ids', [])
            if len(diffs) != len(manifest['layers']):
                raise RuntimeResolutionError(translate('Cannot prepare the OCI archive:') + ' diff_ids')
            replacements = {}
            for position, (descriptor, change) in enumerate(zip(manifest['layers'], changes)):
                if not change: continue
                path = Path(folder)/str(position)
                with path.open('xb') as output, gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0, compresslevel=3) as zipped:
                    writer = HashWriter(zipped)
                    with tarfile.open(fileobj=writer, mode='w|', format=tarfile.PAX_FORMAT) as out, layer_tar(archive, descriptor) as layer:
                        for item in layer:
                            new = copy.copy(item); new.name = canonical(item)
                            new.pax_headers = {k:v for k,v in item.pax_headers.items() if k != 'path'}
                            out.addfile(new, layer.extractfile(item) if item.isfile() else None)
                digest = 'sha256:' + filehash(path)
                replacements[_blob_name(digest)] = path
                manifest['layers'][position] = {**descriptor, 'digest':digest, 'size':path.stat().st_size,
                    'mediaType': ('application/vnd.docker.image.rootfs.diff.tar.gzip' if 'docker' in descriptor.get('mediaType','') else 'application/vnd.oci.image.layer.v1.tar+gzip')}
                diffs[position] = 'sha256:' + writer.hash.hexdigest()
            def metadata(value, filename):
                path=Path(folder)/filename;path.write_text(json.dumps(value))
                digest='sha256:'+filehash(path);replacements[_blob_name(digest)]=path
                return {'digest':digest,'size':path.stat().st_size}
            manifest['config'] = {**manifest['config'], **metadata(config, 'config')}
            index['manifests'][0] = {**index['manifests'][0], **metadata(manifest, 'manifest')}
            # Keep exactly the reachable blob graph, not duplicate metadata or old layers.
            keep={_blob_name(x['digest']) for x in manifest['layers']+[manifest['config'],index['manifests'][0]]}
            with partial.open('xb') as raw:
                os.chmod(partial,0o600)
                with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as target:
                    for name in sorted(keep):
                        if name in replacements:
                            path=replacements[name];item=tarfile.TarInfo(name);item.size=path.stat().st_size;item.mode=0o644
                            with path.open('rb') as content:target.addfile(item,content)
                        else:
                            item=copy.copy(_member(archive,name));item.name=name;item.pax_headers={}
                            target.addfile(item,archive.extractfile(_member(archive,name)))
                    import io
                    for name,data in [('oci-layout',b'{"imageLayoutVersion":"1.0.0"}'),('index.json',json.dumps(index).encode())]:
                        item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644;target.addfile(item,io.BytesIO(data))
                raw.flush();os.fsync(raw.fileno())
            verify_archive(partial)
            if changed_layers(partial) != [False]*len(changes) or filehash(source) != source_hash:
                raise RuntimeResolutionError(translate('Cannot prepare the OCI archive:') + ' changed source')
            os.replace(partial,destination)
        return {'path':str(destination),'sha256':filehash(destination),'source_sha256':source_hash}
    finally:
        partial.unlink(missing_ok=True)


def validate(source, prepared):
    if not prepared:
        return str(source)
    path=Path(prepared['path'])
    if path.is_symlink() or filehash(source)!=prepared['source_sha256'] or filehash(path)!=prepared['sha256']:
        raise RuntimeResolutionError(translate('Cannot prepare the OCI archive:') + ' changed import copy')
    verify_archive(path)
    return str(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','journal'])
    parser.add_argument('source',type=Path);parser.add_argument('target',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='prepare':print(json.dumps(prepare(args.source,args.target)))
        else:print(validate(args.source,json.loads(args.target.read_text()).get('import_image')))
    except (OSError,ValueError,KeyError,RuntimeError,tarfile.TarError) as error:
        print(str(error),file=__import__('sys').stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
