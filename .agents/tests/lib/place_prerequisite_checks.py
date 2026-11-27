"""Exercise prerequisites and installation through the real offline commands."""
from contextlib import redirect_stdout, redirect_stderr
import argparse
import copy
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import urllib.error
import zipfile

from checks import ROOT
SOURCE=Path(os.environ.get('PREREQUISITE_SOURCE_ROOT',ROOT))
sys.path.insert(0,str(SOURCE/'.agents/skills/recipes/coolify-hetzner/scripts'))
import setup as flow
# These modules provide fixture pins, read replies and patch targets. On an
# older source tree they are absent, so find the current fixture helpers only
# after importing its command. Never attach them to that command.
sys.path.append(str(ROOT/'.agents/skills/recipes/coolify-hetzner/scripts'))
import toolchain
import preflight
import tailscale_reads
import console_pages
import api
import approval_gate_checks as plans
from prerequisite_standins import POLICY


def command(gate, *args):
    out=io.StringIO()
    with patch.object(flow,'approval_gate',return_value=gate),patch.object(sys,'argv',['setup',*map(str,args)]),redirect_stdout(out),redirect_stderr(out):
        try:status=flow.main()
        except SystemExit as error:status=error.code
    text=out.getvalue()
    assert not any(value in text for value in ('synthetic-read-secret','synthetic-bearer','synthetic-storage-private','synthetic-access-id'))
    return status,text


class Reply(io.BytesIO):
    status=200


class Reads:
    def __init__(self):
        self.policy=copy.deepcopy(POLICY); self.dns=True; self.https=True
        self.calls=[]; self.bad=None; self.token_bad=False
    def open(self,request,**kwargs):
        method=request.get_method();url=request.full_url;self.calls.append((method,url))
        assert kwargs['timeout']==20
        if url.endswith('/oauth/token'):
            assert method=='POST'
            body=parse_qs(request.data.decode())
            assert body['client_id']==['synthetic-read-id'] and body['client_secret']==['synthetic-read-secret']
            scopes=body['scope'][0].split()
            assert scopes in (tailscale_reads.PREFLIGHT_SCOPES,tailscale_reads.SERVICE_SCOPES)
            assert all(s.endswith(':read') for s in scopes)
            result=dict(access_token='synthetic-bearer',token_type='Bearer',expires_in=3600)
            if self.token_bad:result['expires_in']=0
            return Reply(json.dumps(result).encode())
        if 'your-objectstorage.com' in url:
            assert method=='HEAD' and request.data is None
            assert url=='https://fsn1.your-objectstorage.com/fixture-state'
            # Independently recompute SigV4. Wrong key, path, region, headers
            # or date cannot pass the stand-in.
            stamp=request.get_header('X-amz-date');day=stamp[:8]
            scope=day+'/fsn1/s3/aws4_request';payload=hashlib.sha256(b'').hexdigest()
            host=urlsplit(url).netloc
            signed='host;x-amz-content-sha256;x-amz-date'
            canonical='\n'.join(['HEAD','/fixture-state','',
                'host:'+host+'\nx-amz-content-sha256:'+payload+'\nx-amz-date:'+stamp+'\n',signed,payload])
            message='AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
            key=b'AWS4synthetic-storage-private'
            for v in (day,'fsn1','s3','aws4_request'):key=hmac.new(key,v.encode(),hashlib.sha256).digest()
            signature=hmac.new(key,message.encode(),hashlib.sha256).hexdigest()
            assert request.get_header('Authorization')=='AWS4-HMAC-SHA256 Credential=synthetic-access-id/'+scope+', SignedHeaders='+signed+', Signature='+signature
            if self.bad=='bucket':raise urllib.error.HTTPError(url,403,'private',{},None)
            return Reply()
        assert method=='GET' and request.data is None
        assert request.get_header('Authorization')=='Bearer synthetic-bearer'
        assert request.get_header('Accept')=='application/json'
        route=url.removeprefix('https://api.tailscale.com/api/v2/tailnet/-/')
        assert route in ('acl','dns/preferences','settings'),route
        if self.bad==route:raise urllib.error.HTTPError(url,403,'private',{},None)
        return Reply(json.dumps({'acl':self.policy,'dns/preferences':dict(magicDNS=self.dns),
                                'settings':dict(httpsEnabled=self.https)}[route]).encode())


def prerequisites(work):
    gate=plans.load(SOURCE/'.agents/skills/setup-hosting')
    config=json.loads((ROOT/'.agents/skills/recipes/coolify-hetzner/setup.example.json').read_text())
    config['backend']['bucket']='fixture-state'
    secrets=work/'fixture.env';secrets.write_text('TAILSCALE_READ_CLIENT_ID=synthetic-read-id\nTAILSCALE_READ_CLIENT_SECRET=synthetic-read-secret\nSTORAGE_ACCESS_KEY=synthetic-access-id\nSTORAGE_SECRET_KEY=synthetic-storage-private\n')
    secrets.chmod(0o600);config['secrets']=str(secrets)
    progress=work/'progress.json';state=dict(root=str(work),config=config,done=[],uncertain=None)
    progress.write_text(json.dumps(state));saved=progress.read_bytes()
    reads=Reads()
    base=['--progress',progress,'--plan',work/'forbidden.plan']
    # Tool verification has its own command cases below. These stand-ins
    # replace only the read transports; no policy write or tofu plan is allowed.
    with patch.object(toolchain,'verify_tools'),patch.object(preflight.urllib.request,'build_opener',return_value=reads), \
         patch.object(gate,'plan',side_effect=AssertionError('A refused preflight reached planning')):
        status,text=command(gate,'preflight',*base);assert status==0,'Preflight command did not accept valid read prerequisites: '+text
        assert 'Preflight passed' in text and progress.read_bytes()==saved
        for section in ('tagOwners','autoApprovers','ssh'):
            reads.policy=copy.deepcopy(POLICY);reads.policy.pop(section)
            for verb in ('preflight','plan'):
                status,text=command(gate,verb,*base)
                assert status!=0 and 'Preflight refused planning' in text,text
                assert 'Access controls > JSON editor' in text and section in text
                assert 'https://login.tailscale.com/admin/acls/file' in text
                assert progress.read_bytes()==saved and not (work/'forbidden.plan').exists()
        reads.policy=copy.deepcopy(POLICY)
        # Missing individual tags, wrong ownership and SSH targets also fail.
        for edit in (lambda p:p['tagOwners'].pop('tag:server'),
                     lambda p:p['tagOwners'].update({'tag:container':['autogroup:admin']}),
                     lambda p:p['autoApprovers']['services'].update({'tag:container':['tag:other']}),
                     lambda p:p['ssh'][0].update(users=['ubuntu']),
                     lambda p:p['ssh'][0].update(src=['autogroup:member'])):
            reads.policy=copy.deepcopy(POLICY);edit(reads.policy)
            assert command(gate,'plan',*base)[0]!=0
        reads.policy=copy.deepcopy(POLICY)
        for attribute in ('dns','https'):
            setattr(reads,attribute,False)
            status,text=command(gate,'plan',*base)
            assert status!=0 and 'DNS > MagicDNS' in text and 'Enable HTTPS' in text,text
            setattr(reads,attribute,True)
        for failed in ('bucket','acl','dns/preferences','settings'):
            reads.bad=failed
            status,text=command(gate,'plan',*base);assert status!=0,text
            assert 'console' in text and progress.read_bytes()==saved
        reads.bad=None
        reads.policy['grants']=[dict(src=['*'],dst=['*'],ip=['*'])]
        status,text=command(gate,'preflight',*base)
        assert status==0 and 'allow all' in text and 'tcp:443' in text and 'svc:place-canary' in text,text
        assert 'does not remove' in text
        reads.token_bad=True
        status,text=command(gate,'plan',*base);assert status!=0 and 'Preflight refused' in text
        reads.token_bad=False
        with patch.object(toolchain,'verify_tools',side_effect=ValueError('private')):
            status,text=command(gate,'plan',*base);assert status!=0 and 'install-tools' in text
        assert all(method in ('GET','HEAD') or url.endswith('/oauth/token') for method,url in reads.calls)
        assert not list(work.glob('*.identity.json')) and progress.read_bytes()==saved
    # Success reaches the real plan path, after all reads, never before them.
    secrets.write_text(secrets.read_text()+'STATE_PASSPHRASE=synthetic-long-passphrase\nHETZNER_PROJECT_TOKEN=synthetic-cloud\nTAILSCALE_AUTH_KEY=tskey-auth-synthetic\n')
    with patch.object(toolchain,'verify_tools'),patch.object(preflight.urllib.request,'build_opener',return_value=reads), \
         patch.object(gate,'plan',side_effect=lambda p:Path(p).write_bytes(b'synthetic saved plan')):
        status,text=command(gate,'plan',*base);assert status==0,text
        assert json.loads(progress.read_text())['saved_plan']==str((work/'forbidden.plan').resolve())
    # An inherited override is a refusal, never an alternate bucket endpoint.
    with patch.dict(os.environ,{'AWS_PROFILE':'synthetic-profile'}),patch.object(toolchain,'verify_tools'),patch.object(preflight.urllib.request,'build_opener',return_value=reads):
        assert command(gate,'preflight',*base)[0]!=0
    # Exercise the actual tool verifier through preflight as well as the
    # installer. Its version and package reads are independent stand-ins.
    pin=toolchain.pins();install=work/'tools';package=install/'node_modules'/pin['package']
    package.mkdir(parents=True);(package/'dist').mkdir();(package/'dist/index.js').touch()
    (package/'package.json').write_text(json.dumps(dict(name=pin['package'],version=pin['version'])))
    lock={'packages':{'':dict(dependencies={pin['package']:pin['version']}),
        'node_modules/'+pin['package']:dict(version=pin['version'],integrity=pin['integrity'])}}
    (install/'package-lock.json').write_text(json.dumps(lock))
    versions=dict(line.split('==') for line in toolchain.requirements(gate).read_text().splitlines())
    with patch.object(preflight.urllib.request,'build_opener',return_value=reads),patch.object(gate,'check_version'), \
         patch.object(toolchain.importlib.metadata,'version',side_effect=lambda name:versions[name]), \
         patch.object(toolchain.shutil,'which',return_value='/fixture/tool'):
        status,text=command(gate,'preflight',*base,'--mcp-package',package/'package.json');assert status==0,text
        for fault in ('lock','python','tofu','runtime'):
            with patch.object(gate,'plan',side_effect=AssertionError('Bad tools reached plan')):
                if fault=='lock':
                    lock['packages']['node_modules/'+pin['package']]['integrity']='bad'
                    (install/'package-lock.json').write_text(json.dumps(lock))
                    status,text=command(gate,'plan',*base,'--mcp-package',package/'package.json')
                    lock['packages']['node_modules/'+pin['package']]['integrity']=pin['integrity']
                    (install/'package-lock.json').write_text(json.dumps(lock))
                elif fault=='python':
                    with patch.object(toolchain.importlib.metadata,'version',side_effect=toolchain.importlib.metadata.PackageNotFoundError('fixture')):
                        status,text=command(gate,'plan',*base,'--mcp-package',package/'package.json')
                elif fault=='tofu':
                    with patch.object(gate,'check_version',side_effect=ValueError('wrong version')):
                        status,text=command(gate,'plan',*base,'--mcp-package',package/'package.json')
                else:
                    with patch.object(toolchain.shutil,'which',return_value=None):
                        status,text=command(gate,'plan',*base,'--mcp-package',package/'package.json')
                assert status!=0 and 'install-tools' in text,(fault,text)
    # Service stages request Services Read alone. A failed exchange cannot
    # fall back to the broad API token or consume a write approval.
    gate.configure_secrets(secrets)
    with patch.object(tailscale_reads.urllib.request,'build_opener',return_value=reads),redirect_stdout(io.StringIO()):
        assert tailscale_reads.read_token(gate)=='synthetic-bearer'
        reads.token_bad=True
        try:tailscale_reads.read_token(gate,fallback=lambda:(_ for _ in ()).throw(AssertionError('Broad fallback after OAuth failure')))
        except ValueError:pass
        else:raise AssertionError('Bad token accepted')
    print('Passed: real preflight and plan refusal paths, signed bucket reads and exact OAuth read scopes')


def oauth_stage(work):
    import place_stage_checks as stages
    import urllib.request
    for invalid in (False,True):
        scenario=stages.Scenario(work/('invalid' if invalid else 'valid'),'register')
        secrets=scenario.folder/'fixture.env'
        secrets.write_text('TAILSCALE_READ_CLIENT_ID=synthetic-read-id\nTAILSCALE_READ_CLIENT_SECRET=synthetic-read-secret\n')
        secrets.chmod(0o600)
        state=scenario.read();state['config']['secrets']=str(secrets);flow.save(scenario.progress,state)
        # The changed non-secret path needs a fresh effect and approval.
        scenario.effect.unlink();scenario.approval.unlink()
        assert scenario.command('prepare','--step','register','--effect',scenario.effect)[0]==0
        scenario.approve(scenario.effect,scenario.approval)
        before=scenario.progress.read_bytes();service=stages.Services();service.progress=scenario.progress
        exchanges=[]
        with stages.standins(service):
            original=urllib.request.build_opener()
            class OAuth:
                def open(self,request,**kwargs):
                    if getattr(request,'full_url','').endswith('/oauth/token'):
                        data=parse_qs(request.data.decode());assert data['scope']==['services:read']
                        assert request.get_method()=='POST';exchanges.append(data['scope'])
                        return Reply(json.dumps(dict(access_token=stages.TAILSCALE,token_type='Bearer',expires_in=0 if invalid else 3600)).encode())
                    return original.open(request,**kwargs)
            with patch.object(urllib.request,'build_opener',return_value=OAuth()):
                status,text=scenario.run()
        assert exchanges==[['services:read']],'Register did not exchange the read credential for services:read: '+text
        if invalid:
            assert status!=0 and not service.writes and scenario.progress.read_bytes()==before,text
            assert not list(scenario.journal.glob('*.json')),'Invalid OAuth input consumed approval'
        else:assert status==0 and len(service.writes)==1,text
    print('Passed: real register stage uses read OAuth; invalid exchange preserves approval and receipt boundaries')


def update_effects(work):
    from place_stage_checks import Scenario
    for step in ('docktail','start-docktail'):
        scenario=Scenario(work/step,step)
        assert 'update_check=true' in json.loads(scenario.effect.read_text())['effect'],'Prepared '+step+' effect omitted update_check=true'
    dependency=json.loads((SOURCE/'.agents/skills/recipes/coolify-hetzner/dependencies.json').read_text())['docktail']
    assert dependency['update_check'] is True and dependency['update_check_reason']
    print('Passed: prepared create and start effects disclose the retained outbound update check')


def installer(work):
    gate=plans.load(SOURCE/'.agents/skills/setup-hosting')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as zipped:zipped.writestr('tofu',b'fixture tofu executable')
    good=archive.getvalue();checksum=hashlib.sha256(good).hexdigest();pin=toolchain.pins()
    for case in ('good','published','archive','tofu-version','python-version','mcp-version','integrity','missing-dist',
                 'npm-error','npm-config-error','npm-timeout','npm-missing','pip-error','download-error'):
        target=work/case;calls=[]
        class Download:
            def open(self,url,**kwargs):
                assert url.startswith('https://github.com/opentofu/opentofu/releases/download/v1.13.2/')
                if case=='download-error':raise OSError('synthetic-read-secret')
                return Reply(((('0'*64 if case=='published' else checksum)+'  tofu_1.13.2_linux_amd64.zip\n').encode()) if url.endswith('SHA256SUMS') else (b'corrupt' if case=='archive' else good))
        def process(args,**kwargs):
            args=list(map(str,args));calls.append(args)
            assert kwargs['stdin']==subprocess.DEVNULL and not any(k.startswith(('TF_','AWS_')) for k in kwargs['env'])
            if args[0].endswith('/tofu'):
                return subprocess.CompletedProcess(args,0,json.dumps(dict(terraform_version='0.0.0' if case=='tofu-version' else '1.13.2')).encode(),b'')
            if '-m' in args and 'venv' in args:
                (target/'venv/bin').mkdir(parents=True);(target/'venv/bin/python3').touch()
            elif 'pip' in args:
                assert '--isolated' in args and '--only-binary=:all:' in args and '--no-deps' in args
                if case=='pip-error':return subprocess.CompletedProcess(args,1,b'',b'private pip diagnostics')
            elif '-c' in args:
                versions=dict(line.split('==') for line in toolchain.requirements(gate).read_text().splitlines())
                if case=='python-version':versions['jsonschema']='0.0.0'
                return subprocess.CompletedProcess(args,0,json.dumps(versions).encode(),b'')
            elif args[0]=='npm':
                assert '--ignore-scripts' in args and '--save-exact' in args
                assert pin['package']+'@'+pin['version'] in args
                user=Path(kwargs['env']['NPM_CONFIG_USERCONFIG'])
                global_config=Path(kwargs['env']['NPM_CONFIG_GLOBALCONFIG'])
                if user.samefile(global_config):
                    message='double-loading config "'+str(global_config)+'" as "global", previously loaded as "user"'
                    print('npm stand-in: '+message)
                    return subprocess.CompletedProcess(args,1,b'',('Exit prior to config file resolving\ncause\n'+message+'\n').encode())
                assert user.is_file() and global_config.is_file()
                assert user.read_bytes()==global_config.read_bytes()==b''
                assert user.parent==global_config.parent==target/('coolify-mcp-'+pin['version'])
                assert user.stat().st_mode & 0o777 == global_config.stat().st_mode & 0o777 == 0o600
                assert set(kwargs['env'])=={'PATH','HOME','NPM_CONFIG_USERCONFIG','NPM_CONFIG_GLOBALCONFIG','NPM_CONFIG_CACHE'}
                if case=='npm-error':
                    (target/'npm-cache').mkdir()
                    return subprocess.CompletedProcess(args,1,b'non-summary output',
                        b'private non-summary diagnostics\nnpm error code ECONFIG\n\x1b[31mnpm error local fixture failed\x1b[0m\x07\n')
                if case=='npm-config-error':
                    return subprocess.CompletedProcess(args,1,b'',
                        b'Exit prior to config file resolving\ncause\ndouble-loading config "/fixture" as "global", previously loaded as "user"\n')
                if case=='npm-timeout':raise subprocess.TimeoutExpired(args,600,stderr=b'private timeout diagnostics')
                if case=='npm-missing':raise FileNotFoundError('synthetic-read-secret')
                root=Path(args[args.index('--prefix')+1]);package=root/'node_modules'/pin['package']
                package.mkdir(parents=True);(package/'dist').mkdir()
                if case!='missing-dist':(package/'dist/index.js').touch()
                (package/'package.json').write_text(json.dumps(dict(name=pin['package'],version='0.0.0' if case=='mcp-version' else pin['version'])))
                (root/'package-lock.json').write_text(json.dumps(dict(lockfileVersion=3,packages={
                    '':dict(dependencies={pin['package']:pin['version']}),
                    'node_modules/'+pin['package']:dict(version=pin['version'],integrity='bad' if case=='integrity' else pin['integrity'])})))
            else:raise AssertionError(args)
            return subprocess.CompletedProcess(args,0,b'',b'')
        with patch.object(toolchain.platform,'system',return_value='Linux'),patch.object(toolchain.platform,'machine',return_value='x86_64'), \
             patch.object(toolchain,'CHECKSUMS',{'linux_amd64':checksum}),patch.object(toolchain.urllib.request,'build_opener',return_value=Download()), \
             patch.object(toolchain.subprocess,'run',side_effect=process),patch.object(toolchain.shutil,'which',return_value='/fixture/tool'),patch.object(gate,'secrets_directory_safe'):
            status,text=command(gate,'install-tools','--tools-home',target)
            assert (status==0)==(case=='good'),'Installer result differed for '+case+': '+text
            if case=='good':
                assert 'SHA-256' in text and 'SHA-512' in text and 'lifecycle scripts were disabled' in text
                assert 'Tools installed' in text
                before=len(calls)
                status,text=command(gate,'install-tools','--tools-home',target)
                assert status!=0 and len(calls)==before
                assert 'already exists' in text and '--tools-home' in text
            else:
                assert 'Tools installed' not in text
                stage=('OpenTofu' if case in ('published','archive','tofu-version','download-error') else
                       'Python environment' if case in ('python-version','pip-error') else 'MCP')
                assert 'Tool installation failed during '+stage in text,text
                assert 'Nothing was removed' in text and 'inspect and remove' in text and '--tools-home' in text,text
                present=[target/name for name in ('opentofu','venv','coolify-mcp-'+pin['version'],'npm-cache') if (target/name).exists()]
                if present:assert 'Folders present (possibly incomplete): '+', '.join(map(str,present))+'.' in text,text
                else:assert 'No tool destination folders are present' in text,text
                if case.startswith('npm-'):
                    assert (target/'opentofu/tofu').read_bytes()==b'fixture tofu executable'
                    assert (target/'venv/bin/python3').is_file()
                    assert (target/('coolify-mcp-'+pin['version'])/'package.json').is_file()
                    before=len(calls)
                    assert command(gate,'install-tools','--tools-home',target)[0]!=0 and len(calls)==before
                if case=='npm-error':
                    assert 'npm error code ECONFIG' in text and 'npm error local fixture failed' in text,text
                    assert '\x1b' not in text and '\x07' not in text and 'private non-summary' not in text
                if case=='npm-config-error':
                    assert 'Exit prior to config file resolving' in text and 'double-loading config "/fixture"' in text,text
                if case=='npm-timeout':assert 'timed out' in text and 'private timeout' not in text
            assert not any(value in text for value in ('Before apply','partial retirement','plan-destroy','uncertain write')),text
    print('Passed: real installer path, checksum, wheel versions, npm scripts and lock integrity refusals')


def real_npm(work):
    if shutil.which('npm') is None or shutil.which('node') is None:
        print('could-not-run: Node and npm are needed for the offline npm installation check')
        return 2
    import base64
    pin=toolchain.pins();home=work/'home';home.mkdir()
    marker=work/'lifecycle-ran';archive=work/'fixture.tgz'
    script='node -e '+json.dumps('require("fs").writeFileSync('+json.dumps(str(marker))+', "ran")')
    metadata=dict(name=pin['package'],version=pin['version'],scripts={name:script for name in ('preinstall','install','postinstall')})
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in [('package.json',json.dumps(metadata).encode()),('dist/index.js',b'// offline fixture\n')]:
            member=tarfile.TarInfo('package/'+name);member.size=len(data);tar.addfile(member,io.BytesIO(data))
    integrity='sha512-'+base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    # This generated config must be ignored. No real home or config is read.
    (home/'.npmrc').write_text('registry=http://127.0.0.1:1\nignore-scripts=false\nforce=true\n')
    gate=plans.load(SOURCE/'.agents/skills/setup-hosting')
    versions=dict(line.split('==') for line in toolchain.requirements(gate).read_text().splitlines())
    real_run=subprocess.run
    class ProbeComplete(Exception):pass
    def process(args,**kwargs):
        args=list(map(str,args))
        if 'pass_fds' in kwargs:return real_run(args,**kwargs)
        if args[0]=='npm':
            # Keep the installer's flags and environment; replace only the
            # registry package with a local tarball and require offline mode.
            result=real_run([*args[:-1],str(archive),'--offline'],cwd=work,**kwargs)
            assert result.returncode==0,'Real offline npm failed: '+toolchain.npm_error_summary(result.stderr)
            mcp=Path(args[args.index('--prefix')+1])
            lock=json.loads((mcp/'package-lock.json').read_text())
            assert lock['packages']['node_modules/'+pin['package']]['integrity']==integrity
            assert json.loads((mcp/'node_modules'/pin['package']/'package.json').read_text())==metadata
            assert not marker.exists(),'npm ran a lifecycle script'
            version=real_run(['npm','--version'],cwd=work,env=kwargs['env'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            assert version.returncode==0
            print('Passed: real npm '+version.stdout.decode().strip()+' installed a local tarball offline with isolated configs, disabled lifecycle scripts and matching lock integrity')
            raise ProbeComplete
        if '-c' in args:output=versions
        elif args[0].endswith('/tofu'):output=dict(terraform_version='1.13.2')
        else:output={}
        return subprocess.CompletedProcess(args,0,json.dumps(output).encode(),b'')
    with patch.object(toolchain,'install_tofu'),patch.object(toolchain.subprocess,'run',side_effect=process):
        try:toolchain.install(gate,home)
        except ProbeComplete:pass
        else:raise AssertionError('Installer did not reach real npm')
    return 0


def pages(work):
    gate=plans.load(SOURCE/'.agents/skills/setup-hosting')
    opened=[]
    with patch.object(console_pages,'open_url',side_effect=opened.append):
        for provider,data in json.loads(console_pages.MAP.read_text())['providers'].items():
            for key,item in data['entries'].items():
                assert all(field in item for field in ('url','menu_path','button','field','shown_once'))
                status,text=command(gate,'console','--page',provider+'.'+key,'--address','100.64.0.10')
                assert status==0 and data['version'] in text and 'Button:' in text and 'Value shown only once:' in text,'Console command omitted versioned page guidance: '+text
        assert len(opened)==sum(len(p['entries']) for p in json.loads(console_pages.MAP.read_text())['providers'].values())
    # The gate's shared prompt path must open guidance before reading values,
    # including the storage pair used outside setup.py.
    from contextlib import contextmanager
    @contextmanager
    def terminal():yield None
    gate.SECRET_VALUES={};gate.S3_CREDENTIALS=None
    console_pages.configure(gate,dict(place=dict(name='test-place'),infrastructure=dict(tailnet_ipv4='100.64.0.10')))
    events=[]
    def typed(*args,**kwargs):
        assert events and events[-1][0]=='open'
        events.append(('typed',None));return 'synthetic-value'
    with patch.object(gate,'terminal',terminal),patch.object(gate,'typed',side_effect=typed),patch.object(console_pages,'open_url',side_effect=lambda url:events.append(('open',url))),redirect_stdout(io.StringIO()):
        gate.storage_credentials()
        for key in console_pages.SECRET_PAGES:gate.secret(key,'Fixture',shown=key.endswith('_ID'))
    # A new secrets context cannot retain another place's console callback.
    gate.configure_secrets()
    assert gate.CONSOLE_GUIDANCE is None
    print('Passed: versioned console command and guidance before shared secret prompts')


def retirement_pages(work):
    from contextlib import contextmanager
    from place_checks import resources
    import retire
    record=json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
    record['infrastructure']['plumbing']=dict(project_uuid='project-one',docktail_uuid='docktail-one',
        canary_uuid='canary-one',tailnet_service_name='place-canary')
    path=work/'record.json';path.write_text(json.dumps(record));owned=resources(record)
    shown=dict(format_version='1.2',resource_changes=[dict(type='hcloud_'+kind,
        change=dict(actions=['delete'],before=value,after=None)) for kind,value in owned.items()])
    @contextmanager
    def saved(*args):yield ('fixture-plan','a'*64)
    @contextmanager
    def terminal():yield None
    applied=[]
    gate=SimpleNamespace(require_encryption=lambda:None,check_version=lambda:None,saved_plan=saved,
        planned_identity=lambda *args:None,tofu=lambda *args:subprocess.CompletedProcess(args,0,json.dumps(shown).encode(),b''),
        terminal=terminal,typed=lambda *args:record['place']['name'],apply=lambda *args:applied.append(args))
    cloud=SimpleNamespace(owned_resources=lambda **kwargs:owned,inventory=lambda kind:[])
    out=io.StringIO()
    with patch.object(retire,'API',return_value=cloud),patch.object(sys,'argv',['retire','--record',str(path),'--plan','fixture-plan','--approval','fixture-approval']),redirect_stdout(out),redirect_stderr(out):
        status=retire.main(gate=gate,token='synthetic-cloud')
    text=out.getvalue();assert status==0 and len(applied)==1,text
    for value in ('Services > svc:place-canary','Delete service','Machines > test-place','Remove',
                  'Settings > Trust credentials','Revoke','API access tokens'):
        assert value in text,'Retirement guidance omitted '+value
    for page in ('services','machines','settings/trust-credentials','settings/keys'):
        assert 'https://login.tailscale.com/admin/'+page in text,page
    # An interrupted setup can retire before plumbing reaches the final
    # record. Its retained non-secret config still names the canary to review.
    record['infrastructure'].pop('plumbing');path.write_text(json.dumps(record));out=io.StringIO()
    with patch.object(retire,'API',return_value=cloud),patch.object(sys,'argv',['retire','--record',str(path),'--plan','fixture-plan','--approval','fixture-approval']),redirect_stdout(out),redirect_stderr(out):
        status=retire.main(gate=gate,token='synthetic-cloud',console_context=dict(place='test-place',canary='interrupted-canary'))
    assert status==0 and 'Services > svc:interrupted-canary' in out.getvalue()
    print('Passed: real retire command lists service, machine, OAuth credentials and API token with pages and buttons')


CASES = ('prerequisites','oauth_stage','update_effects','installer','pages','retirement_pages')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=(*CASES,'real_npm'))
    args=parser.parse_args()
    for name in ([args.case] if args.case else CASES):
        case=globals()[name]
        with tempfile.TemporaryDirectory(prefix='ai-host-kit-prerequisites-') as temp:
            status=case(Path(temp).resolve())
            if status:return status
    return 0


if __name__=='__main__':sys.exit(main())
