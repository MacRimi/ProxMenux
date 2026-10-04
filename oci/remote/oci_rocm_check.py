#!/usr/bin/env python3
"""A real inference on the AMD GPU of a container, through ROCm.

That the MIGraphX provider is listed says nothing about the GPU of this host:
an image carries kernels for some generations only, and on any other the
first inference aborts. This runs a small convolution model on the GPU inside
the container and fails when it does not come back with a result.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# A model of five operators (convolution, pooling and a dense layer), enough
# to make ROCm compile and run on the GPU without downloading anything.
MODEL = (
    'CAg65wUKPAoBeAoBdwoBYhIBYyIEQ29udioVCgxrZXJuZWxfc2hhcGVAA0ADoAEHKhEKBHBhZHNAAUABQAFAAaABBwoMCgFjEgFy'
    'IgRSZWx1ChkKAXISAWciEUdsb2JhbEF2ZXJhZ2VQb29sCg8KAWcSAWYiB0ZsYXR0ZW4KFAoBZgoCZncKAmZiEgF5IgRHZW1tEgVw'
    'cm9iZSrAAwgECAMIAwgDEAFCAXdKsAOu/QA5e7v0POCS4LyqZLa9sDs6vdcWy70cFMU78DwJPpibSb2CJX69qqNIPVEuEj3xtSw8'
    'U4++vWu0P7vqZY49x6UJvn5wO71qr0K+dgwEvvuXPL4vlsC8WskBvkI43jwWaYA8QyKZvKzbgL4Lply9i+2euzylOTyXrxy+ELBD'
    'vZVmyL1epqW9pUXZPRNipb1fIlW7gB+1PfIKb70yAze8Bfw0PAgA0Ts15Pq9D3/5O74kCz54bR6+ZwCwPbWMQzyGX4O9uNdMPl0c'
    'nD1HnfW9vyz0O0o2bD17ppq8K9yLPcf22bv9pog9Ak4TPipgir1BaaY8U8U9vT+EUDwwI/O9LUhtvUe5oLwdEbg9nYrqPX2HB74m'
    'vqK9X3yEPRcGTL7itj29GGUfvOW3AD6fMI090AYGvfz3Fr3I9cy8aQIcPqtRL71lxvi8pWsQPczeRbyAnaG8NSnkvaIDl7rdsDW9'
    'r9LuPabAhT1DOh67a+KIPeg1C726edc914sNuhP0bj3+LwS+CgAOPUPfLL7talC+b235vCBOuL1eZIY889xlPj9Wqr06kX+9VESo'
    'PDHwST0qGQgEEAFCAWJKEAAAAAAAAAAAAAAAAAAAAAAqLAgECAIQAUICZndKIAmDkLy5sqi8S92PPUX0VD1istO9DrsBvIJBZztd'
    '9de9KhIIAhABQgJmYkoIAAAAAAAAAABaGwoBeBIWChQIARIQCgIIAQoCCAMKAggICgIICGITCgF5Eg4KDAgBEggKAggBCgIIAkIE'
    'CgAQDQ=='
)
PROBE = """
import base64, sys
import numpy as np
import onnxruntime as ort
options = ort.SessionOptions()
options.log_severity_level = 3
session = ort.InferenceSession(base64.b64decode(sys.argv[1]), options, providers=['MIGraphXExecutionProvider'])
assert session.get_providers()[0] == 'MIGraphXExecutionProvider', session.get_providers()
result = session.run(None, {'x': np.ones((1, 3, 8, 8), np.float32)})[0]
assert result.shape == (1, 2) and np.isfinite(result).all(), result
print('ROCm inference on the GPU: ok')
"""


def variables(config):
    """What the container tells ROCm about its GPU. A command run in the
    container does not receive the variables its application starts with."""
    found = re.findall(r'^lxc\.environment\.runtime: (.+)$', config, re.M)
    for line in re.findall(r'^env: (.+)$', config, re.M):
        found += line.split('\0')
    return [value for value in found if re.fullmatch(r'HSA_[A-Z_]+=[0-9A-Za-z.]+', value)]


def check(vmid, timeout=300):
    """Raises RuntimeError when the container cannot run the model on its GPU."""
    vmid = str(int(vmid))
    config = subprocess.run(['pct', 'config', vmid], capture_output=True, text=True, check=False).stdout
    try:
        result = subprocess.run(['pct', 'exec', vmid, '--', 'env', *variables(config), 'python', '-c', PROBE, MODEL],
                                capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('the GPU did not answer in time') from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['']
        raise RuntimeError(detail[0][:300])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    args = parser.parse_args()
    try:
        check(args.vmid)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
