"""Check that the fresh-install release files and runtime pins agree, offline."""
import json
from pathlib import Path
import re
import sys

FILES = {'install.sh': 'scripts/install.sh', 'upgrade.sh': 'scripts/upgrade.sh',
         'upgrade-postgres.sh': 'scripts/upgrade-postgres.sh',
         'docker-compose.yml': 'docker-compose.yml',
         'docker-compose.prod.yml': 'docker-compose.prod.yml', '.env.production': '.env.production'}


def check(recipe):
    dependencies = json.loads((recipe/'dependencies.json').read_text())
    version = dependencies['coolify']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Coolify needs an exact stable version.')
    pins = dependencies['coolify_files']
    if set(pins) != set(FILES):
        raise ValueError('Coolify release file pins are incomplete.')
    cloud = (recipe/'tofu/hetzner-server/cloud-init.sh').read_text()
    manifest = cloud.split("done <<'HOST_KIT_COOLIFY_FILES'\n", 1)[1].split('\nHOST_KIT_COOLIFY_FILES\n', 1)[0]
    expected = []
    for name, path in FILES.items():
        pin = pins[name]
        url = f'https://raw.githubusercontent.com/coollabsio/coolify/v{version}/{path}'
        if pin['url'] != url or not re.fullmatch(r'[0-9a-f]{64}', pin.get('sha256', '')):
            raise ValueError('Coolify release or checksum differs: ' + name)
        expected.append(f"{pin['sha256']} {name} {url}")
    if manifest.splitlines() != expected:
        raise ValueError('Cloud-init release files differ from dependencies.json.')
    if f'COOLIFY_VERSION={version}\n' not in cloud or f'LATEST_VERSION={version}\\n' not in cloud:
        raise ValueError('Cloud-init image version differs from its release files.')
    helper = dependencies['coolify_helper']
    if f'LATEST_HELPER_VERSION={helper}\\n' not in cloud:
        raise ValueError('Cloud-init helper version differs.')
    source = (recipe/'scripts/place.py').read_text()
    if f'coolify="{version}"' not in source:
        raise ValueError('Runtime version pins differ from dependencies.json.')
    for guard in ['sha256sum --check --status', 'exit 1', "('install.sh', 5), ('upgrade.sh', 4)", 'if changed != count:', 'AUTOUPDATE=false', 'HEALTH_WAIT=600', 'MAX_WAIT=600']:
        if guard not in cloud:
            raise ValueError('Cloud-init verification or preparation is missing: ' + guard)
    if cloud.index('sha256sum --check --status') > cloud.index('HOST_KIT_PREPARE'):
        raise ValueError('Coolify scripts must be verified before preparation.')


if __name__ == '__main__':
    try:
        check(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]/'skills/recipes/coolify-hetzner')
    except (ValueError, KeyError, IndexError, OSError) as error:
        print('Coolify pin check failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
    print('Coolify release, checksums and runtime pins agree.')
