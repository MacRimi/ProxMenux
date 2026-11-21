"""Names owned by the OCI image cache, without loading or changing its state."""
import re

NAME = re.compile(r'(?:proxmenux-update-[a-z0-9]+-[0-9a-f]{64}'
                  r'|(?:image|linuxserver)-[A-Za-z0-9._-]+_[a-z0-9]+_[0-9a-f]{16})\.tar')


def is_oci_archive(name):
    return isinstance(name, str) and NAME.fullmatch(name) is not None
