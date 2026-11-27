"""Install pinned tools once in the person's lasting local kit folder."""
from contextlib import contextmanager
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from place import OperationRefused, Refused

VERSION = '1.13.2'
CHECKSUMS = {
    'darwin_arm64': 'cb46112c095f1c4da721b6a18c8368f67341896a62205d1c117299e85993af61',
    'darwin_amd64': '2093d0f881d911eb133cf51d2d7e09f22da71b1e6465c60826a314d217b0b84e',
    'linux_amd64': '723bebb0df8411daff1e5fc3862e28ff5581fe5634087f4c29a9aa41d78208b5',
    'linux_arm64': '6e815c58a09ee957de606ff48cefad082942e70afc43b737ff975654c54ec453',
}


def default_home():
    return Path.home()/'.local/share/ai-host-kit'


def install_tofu(destination):
    destination = Path(destination)
    machine = {'aarch64':'arm64', 'x86_64':'amd64'}.get(platform.machine(), platform.machine())
    target = platform.system().lower()+'_'+machine
    if target not in CHECKSUMS: raise OperationRefused('No OpenTofu checksum pin exists for this platform.')
    name = 'tofu_'+VERSION+'_'+target+'.zip'
    base = 'https://github.com/opentofu/opentofu/releases/download/v'+VERSION+'/'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base+'tofu_'+VERSION+'_SHA256SUMS', timeout=60) as response:
        sums = response.read(1024*1024).decode()
    if [line.split()[0] for line in sums.splitlines() if line.split() and line.split()[-1] == name] != [CHECKSUMS[target]]:
        raise OperationRefused('The published OpenTofu checksum differs from the platform pin.')
    with opener.open(base+name, timeout=60) as response: archive = response.read(150*1024*1024)
    if hashlib.sha256(archive).hexdigest() != CHECKSUMS[target]:
        raise OperationRefused('The OpenTofu archive checksum differs from the pin.')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped: binary = zipped.read('tofu')
    destination.mkdir(parents=True, exist_ok=True)
    with (destination/'tofu').open('xb') as output: output.write(binary)
    (destination/'tofu').chmod(0o755)
    print('Verified OpenTofu '+VERSION+': published SHA-256, platform pin and archive bytes match. No release signature was checked.')


def requirements(gate):
    return Path(gate.__file__).resolve().parent.parent/'resources/schema-requirements.txt'


def run(args):
    result = subprocess.run(list(map(str,args)), env={'PATH':os.environ.get('PATH','')},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=600)
    if result.returncode:
        raise OperationRefused('A tool command failed with exit status '+str(result.returncode)+'.')
    return result.stdout


def verify_python(gate, executable=None):
    expected = dict(line.split('==') for line in requirements(gate).read_text().splitlines() if line and not line.startswith('#'))
    if executable:
        script = 'import importlib.metadata,json; print(json.dumps({n:importlib.metadata.version(n) for n in '+repr(list(expected))+'}))'
        observed = json.loads(run([executable,'-I','-c',script]))
    else:
        try: observed = {name:importlib.metadata.version(name) for name in expected}
        except importlib.metadata.PackageNotFoundError:
            raise OperationRefused('A pinned Python requirement is missing. Use the installed kit environment.') from None
    if observed != expected: raise OperationRefused('The Python environment differs from the pinned requirements.')


def verify_tools(gate):
    gate.check_version()
    verify_python(gate)
    if shutil.which('tailscale') is None:
        raise OperationRefused('Install the Tailscale client before planning.')


def install(gate, home=None):
    home = Path(home or default_home()).expanduser().absolute()
    destinations = [home/'opentofu', home/'venv']
    try:
        install_steps(gate, home, destinations)
    except OperationRefused as error:
        present = [path for path in destinations if path.exists()]
        folders = ('Folders present (possibly incomplete): '+', '.join(map(str,present))+'.'
                   if present else 'No tool destination folders are present.')
        raise OperationRefused(str(error)+'\nTools home: '+str(home)+'. '+folders+
            '\nNothing was removed. Before retrying in this home, inspect and remove any existing '+
            'tool destinations: '+', '.join(map(str,destinations))+'. '+
            'Alternatively, retry install-tools with --tools-home pointing to a new home.') from None


@contextmanager
def installation_step(name):
    try:
        yield
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired,zipfile.BadZipFile) as error:
        if isinstance(error, Refused): reason = str(error)
        elif isinstance(error, subprocess.TimeoutExpired): reason = 'A tool command timed out.'
        elif isinstance(error, OSError): reason = 'Local file or download access failed.'
        else: reason = 'Tool output or package metadata could not be verified.'
        raise OperationRefused('Tool installation failed during '+name+'. '+reason) from None


def install_steps(gate, home, destinations):
    with installation_step('checking the installation folder'):
        for part in [home, *home.parents]:
            if part.is_symlink(): raise OperationRefused('The tools folder must not use symlinks.')
        # No overwrite or removal of an existing tool environment.
        if any(path.exists() for path in destinations):
            raise OperationRefused('A tool destination already exists. Keep it; inspect and verify it before choosing a new installation folder.')
        home.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            gate.secrets_directory_safe(descriptor,home/'unused',reason='Keep installed tools outside every Git repository.')
        finally: os.close(descriptor)
    # venv is created at its lasting path so its scripts retain that path.
    with installation_step('OpenTofu installation and verification'):
        install_tofu(destinations[0])
        verify = run([destinations[0]/'tofu','version','-json'])
        if json.loads(verify).get('terraform_version') != VERSION:
            raise OperationRefused('The installed OpenTofu binary reports a different version.')
    with installation_step('Python environment installation and verification'):
        run([sys.executable,'-I','-m','venv',destinations[1]])
        python = destinations[1]/'bin/python3'
        run([python,'-I','-m','pip','--isolated','install','--only-binary=:all:','--no-deps',
             '--disable-pip-version-check','-r',requirements(gate)])
        verify_python(gate, python)
        print('Verified every Python requirement version. Only binary wheels were permitted; no source build scripts ran.')
    print('Tools installed in '+str(home)+'. Put '+str(home/'opentofu')+' and '+str(home/'venv/bin')+' on PATH.')
