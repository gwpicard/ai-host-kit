"""Install the pinned OpenTofu binary outside the source tree after checksum checks."""
import hashlib
import io
from pathlib import Path
import platform
import sys
import urllib.request
import zipfile

VERSION = '1.13.2'
CHECKSUMS = {
    'darwin_arm64': 'cb46112c095f1c4da721b6a18c8368f67341896a62205d1c117299e85993af61',
    'darwin_amd64': '2093d0f881d911eb133cf51d2d7e09f22da71b1e6465c60826a314d217b0b84e',
    'linux_amd64': '723bebb0df8411daff1e5fc3862e28ff5581fe5634087f4c29a9aa41d78208b5',
    'linux_arm64': '6e815c58a09ee957de606ff48cefad082942e70afc43b737ff975654c54ec453',
}


def install(destination):
    root = Path(__file__).resolve().parents[2]
    destination = Path(destination).resolve()
    if destination == root or root in destination.parents:
        raise ValueError('Choose a folder outside the repository.')
    machine = {'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine(), platform.machine())
    target = platform.system().lower() + '_' + machine
    if target not in CHECKSUMS:
        raise ValueError('This platform has no checked OpenTofu archive in this installer.')
    name = f'tofu_{VERSION}_{target}.zip'
    base = f'https://github.com/opentofu/opentofu/releases/download/v{VERSION}/'
    with urllib.request.urlopen(base + f'tofu_{VERSION}_SHA256SUMS', timeout=60) as response:
        sums = response.read().decode()
    published = [line.split()[0] for line in sums.splitlines() if line.split()[-1] == name]
    if published != [CHECKSUMS[target]]:
        raise ValueError('The published checksum differs from the pin. Stop and review the release.')
    with urllib.request.urlopen(base + name, timeout=60) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != CHECKSUMS[target]:
        raise ValueError('The archive checksum differs. Download it again before installing.')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        binary = zipped.read('tofu')
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'tofu').open('xb') as output:
        output.write(binary)
    (destination / 'tofu').chmod(0o755)
    print(f'Installed OpenTofu {VERSION} for {target}; published and pinned SHA-256 match.')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Usage: python3 .agents/tools/install-tofu.py <outside-folder>')
        install(sys.argv[1])
    except (OSError, ValueError, zipfile.BadZipFile):
        print('Could not install the verified OpenTofu binary. Check the destination and official release checksums.')
        sys.exit(1)
