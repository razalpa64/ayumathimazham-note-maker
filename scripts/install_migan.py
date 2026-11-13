"""Install the pinned MI-GAN ONNX weights without committing them to git."""
import hashlib
import io
import os
from pathlib import Path
import tarfile
import urllib.request

MODEL_SHA256 = '6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b'
MODEL_SIZE = 28079181
URL = 'https://registry.npmjs.org/migan-onnx/-/migan-onnx-1.0.0.tgz'
MEMBER = 'package/models/migan_pipeline_v2.onnx'
TARGET = Path(__file__).resolve().parents[1] / 'models' / 'migan_pipeline_v2.onnx'


def main():
    if TARGET.exists() and hashlib.sha256(TARGET.read_bytes()).hexdigest() == MODEL_SHA256:
        print('MI-GAN model already installed and verified.')
        return
    print('Downloading pinned MI-GAN model package (~66 MB)...', flush=True)
    with urllib.request.urlopen(URL, timeout=120) as response:
        archive = response.read(100 * 1024 * 1024 + 1)
    if len(archive) > 100 * 1024 * 1024:
        raise ValueError('Model archive exceeds size limit')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        member = tar.getmember(MEMBER)
        if not member.isfile() or member.size != MODEL_SIZE:
            raise ValueError('Unexpected model file in archive')
        model = tar.extractfile(member).read(MODEL_SIZE + 1)
    if len(model) != MODEL_SIZE or hashlib.sha256(model).hexdigest() != MODEL_SHA256:
        raise ValueError('Model checksum mismatch')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(f'.{os.getpid()}.tmp')
    try:
        temporary.write_bytes(model)
        temporary.replace(TARGET)
    finally:
        temporary.unlink(missing_ok=True)
    print('MI-GAN model installed and SHA-256 verified.')


if __name__ == '__main__':
    main()
