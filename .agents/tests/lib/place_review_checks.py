"""Guard journal replacement, concurrent effects and post-destruction reporting."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
from place_checks import RECIPE, FIXTURE, load, resources, StandIn
from place_fix_checks import approval


def rejected(call):
    try: call()
    except (ValueError, OSError) as error: return str(error)
    raise AssertionError('An old effect was accepted')


def journals(ops, gate, work):
    record=json.loads((FIXTURE/'place-record.json').read_text())
    journal=work/'receipts';other=work/'other-receipts'
    api=StandIn()
    effect=ops.docktail_effect(record,'canary',80,None,journal)
    path=approval(gate,effect,work/'approved.json')
    ops.register_docktail(record,'canary',80,path,api,gate.match_effect,effect,journal)
    api.definition=None
    ops.journal_identity(other)
    assert 'journal' in rejected(lambda:ops.register_docktail(record,'canary',80,path,api,gate.match_effect,effect,other)).lower()
    parked=work/'parked';journal.rename(parked)
    for replacement in ('missing','empty','copied'):
        if replacement!='missing':journal.mkdir()
        if replacement=='copied':shutil.copyfile(parked/'generation',journal/'generation')
        text=rejected(lambda:ops.register_docktail(record,'canary',80,path,api,gate.match_effect,effect,journal))
        assert 'journal' in text.lower(),text
        if journal.exists():shutil.rmtree(journal)
    parked.rename(journal)
    assert len(api.writes)==1


def lane_wrapper(ops, gate, work):
    import lane as cli
    record=json.loads((FIXTURE/'place-record.json').read_text());api=StandIn()
    api.owned_resources=lambda:resources(record)
    record_path=work/'place.json';record_path.write_text(json.dumps(record))
    reader=SimpleNamespace(validate=lambda *a:False,read_json=lambda p:json.loads(Path(p).read_text()),
        dependencies=lambda:None)
    def command(command,lane,ports,effect,approved=None):
        args=['lane',command,'--record',str(record_path),'--lane',lane,'--effect',str(effect)]
        for port in ports:args+=['--port',str(port)]
        if approved:args+=['--approval',str(approved),'--new-record',str(work/'new.json')]
        with patch.object(sys,'argv',args):return cli.main()
    def prepared(lane,ports,name):
        effect=work/(name+'.json');assert command('prepare',lane,ports,effect)==0
        approved=approval(gate,json.loads(effect.read_text()),work/(name+'-approval.json'))
        return effect,approved
    # Allow only local record validation; all transports are stand-ins.
    with patch.object(cli,'OperationRefused',ops.OperationRefused),patch.object(cli,'load_reader',return_value=reader),patch.object(cli,'API',return_value=api),patch.object(cli,'hidden_value',return_value='synthetic-only'),patch.object(cli,'approval_gate',return_value=gate),patch.object(cli,'set_lane',ops.set_lane),patch.object(cli,'attempt_effect',ops.attempt_effect),patch.object(cli,'journal_identity',ops.journal_identity),patch.object(cli,'write_record',lambda *a:None):
        effect,approved=prepared('public',[80],'open')
        assert command('apply','public',[80],effect,approved)==0
        close,close_approval=prepared('internal',[],'close')
        assert command('apply','internal',[],close,close_approval)==0
        journal=work/'place-attempts';parked=work/'parked';journal.rename(parked)
        for mode in ('missing','empty','copied'):
            if mode!='missing':journal.mkdir()
            if mode=='copied':shutil.copyfile(parked/'generation',journal/'generation')
            out=io.StringIO()
            with redirect_stderr(out):assert command('apply','public',[80],effect,approved)!=0
            assert 'Inspect the live state and approve afresh' in out.getvalue(),out.getvalue()
            if journal.exists():shutil.rmtree(journal)
        parked.rename(journal)
        assert len(api.writes)==2


def concurrency(ops,gate,work):
    record=json.loads((FIXTURE/'place-record.json').read_text());api=StandIn()
    journal=work/'receipts'
    effects=[ops.attempt_effect(ops.lane_effect(record,'public',[port]),[],journal) for port in (80,443)]
    paths=[approval(gate,e,work/(str(i)+'.json')) for i,e in enumerate(effects)]
    barrier=threading.Barrier(2)
    original=api.firewall_rules
    def read(identity):
        snapshot=copy.deepcopy(original(identity))
        if not api.writes:
            try:barrier.wait(timeout=0.3)
            except threading.BrokenBarrierError:pass
        return snapshot
    api.firewall_rules=read
    def apply(i):
        try:
            ops.set_lane(record,resources(record),'public',[80 if i==0 else 443],paths[i],api,gate.match_effect,effects[i],journal)
            return 'written'
        except ValueError as error:return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(apply,range(2)))
    assert len(api.writes)==1 and results.count('written')==1,results
    refusal=next(r for r in results if r!='written')
    assert 'Another operation' in refusal or 'fresh lane effect' in refusal,refusal


def retirement(ops,work):
    import retire as cli
    record=json.loads((FIXTURE/'place-record.json').read_text());owned=resources(record)
    plan=dict(resource_changes=[dict(type='hcloud_'+kind,change=dict(actions=['delete'],before=value)) for kind,value in owned.items()])
    @contextmanager
    def saved(*args):yield ('plan','0'*64)
    @contextmanager
    def terminal():yield None
    destroyed=[]
    gate=SimpleNamespace(require_encryption=lambda:None,check_version=lambda:None,saved_plan=saved,planned_identity=lambda *a:None,
        tofu=lambda *a:subprocess.CompletedProcess(a,0,json.dumps(plan).encode(),b''),apply=lambda *a:destroyed.append(True),terminal=terminal,typed=lambda *a:record['place']['name'])
    api=StandIn();api.owned_resources=lambda:owned
    visited=[]
    def inventory(kind):
        visited.append(kind)
        if kind=='servers':raise OSError('Synthetic inventory failure')
        return [{'id':901}] if kind=='volumes' else []
    api.inventory=inventory
    reader=SimpleNamespace(validate=lambda *a:False,read_json=lambda *a:record)
    out=io.StringIO();err=io.StringIO()
    with patch.object(sys,'argv',['retire','--plan','plan','--approval','approval']),patch.object(cli,'load_reader',return_value=reader),patch.object(cli,'API',return_value=api),patch.object(cli,'approval_gate',return_value=gate),patch.object(cli,'hidden_value',return_value='synthetic-only'),patch.object(cli,'retire',ops.retire),redirect_stdout(out),redirect_stderr(err):
        assert cli.main()==2
    text=out.getvalue()
    assert destroyed==[True] and len(visited)==11
    assert 'Destruction completed' in text and 'servers: unchecked' in text and 'volumes: listed: 901' in text and 'images: empty' in text
    assert all(word in text for word in ['Object Storage','DNS','Tailscale','snapshot and backup images','Retirement incomplete'])
    assert 'Refused' not in text+err.getvalue()


def exercise(work,checks):
    sys.path.insert(0,str(RECIPE/'scripts'))
    try:
        ops=load(RECIPE/'scripts/place.py');gate=checks.load()
        for test in (journals,lane_wrapper,concurrency,retirement):
            folder=work/('review-'+test.__name__);folder.mkdir()
            if test==retirement:test(ops,folder)
            else:test(ops,gate,folder)
        source=(RECIPE/'scripts/place.py').read_text()
        start=source.index('def journal_identity(');end=source.index('\ndef attempt_effect',start)
        identity="def journal_identity(journal=None, create=True):\n    return list(bytes.fromhex(fingerprint(str(Path(journal or 'hosting/place-attempts').resolve()))))\n\n"
        journal_mutant=source[:start]+identity+source[end:]
        journal_mutant=journal_mutant.replace("    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL", "    path.parent.mkdir(parents=True,exist_ok=True)\n    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL",1)
        variants=[('journal generation',journal_mutant,lane_wrapper),('firewall serialisation',source.replace('@locked\ndef set_lane','def set_lane'),concurrency),('inventory continuation',source.replace("        except (OSError,ValueError,KeyError,TypeError):\n            return None", "        except (OSError,ValueError,KeyError,TypeError):\n            raise"),retirement)]
        for index,(name,mutant,test) in enumerate(variants):
            assert mutant!=source
            folder=work/('review-removal-'+str(index));folder.mkdir()
            path=folder/'place.py';path.write_text(mutant)
            try:
                if test==retirement:test(load(path),folder)
                else:test(load(path),gate,folder)
            except AssertionError:print('Protection removal detected: '+name)
            else:raise AssertionError('Protection removal escaped: '+name)
            path.write_text(source)
            restored=folder/'restored';restored.mkdir()
            if test==retirement:test(load(path),restored)
            else:test(load(path),gate,restored)
        print('Review probes and restored protections passed.')
    finally:sys.path.pop(0)
