"""Regressions for consumed effects, partial retirement and retained images."""
import copy
import json
from pathlib import Path
import shutil
from unittest.mock import patch
from place_checks import RECIPE, FIXTURE, load, refused, resources, StandIn


def approval(gate, effect, path):
    path.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(effect),effect=effect['effect'],
        words='Synthetic fixture approval',approved_at='2000-01-01T00:00:00Z',method='foreground-terminal')))
    return path


def lanes(ops, gate, work):
    shutil.rmtree('hosting',ignore_errors=True)
    record=json.loads((FIXTURE/'place-record.json').read_text()); owned=resources(record)
    api=StandIn()
    def prepare(lane, ports):
        effect=ops.attempt_effect(ops.lane_effect(record,lane,ports),api.firewall_rules(102))
        path=work/(effect['attempt']+'.json')
        return effect,approval(gate,effect,path)
    def apply(effect,path):
        original=api.set_firewall
        def write(*args):
            receipt=Path('hosting/place-attempts')/(ops.fingerprint(effect)+'.json')
            assert receipt.is_file() and json.loads(receipt.read_text())['status']=='uncertain'
            return original(*args)
        with patch.object(api,'set_firewall',side_effect=write):
            return ops.set_lane(record,owned,effect['lane'],[int(r['port']) for r in effect['rules']],path,api,gate.match_effect,effect)
    old,path=prepare('public',[80,443]); apply(old,path)
    closed,close_path=prepare('internal',[]); apply(closed,close_path)
    # Both the original file and a copied approval must stay consumed.
    copied=work/'copied-approval.json';shutil.copyfile(path,copied)
    refused(lambda:apply(old,path));refused(lambda:apply(old,copied))
    assert len(api.writes)==2
    fresh,fresh_path=prepare('public',[80,443]);apply(fresh,fresh_path)
    assert len(api.writes)==3
    closed,close_path=prepare('internal',[]);apply(closed,close_path)
    pending,pending_path=prepare('public',[443])
    original=api.firewall_rules
    calls=0
    def read(identity):
        nonlocal calls
        calls+=1
        if calls==2: raise ValueError('Synthetic failed read-back')
        return original(identity)
    with patch.object(api,'firewall_rules',side_effect=read):
        refused(lambda:apply(pending,pending_path))
    receipts=list(Path('hosting/place-attempts').glob('*.json'))
    assert any(json.loads(p.read_text())['status']=='uncertain' for p in receipts)
    # Put the observed starting state back to isolate the consumed receipt guard.
    api.rules=[]
    refused(lambda:apply(pending,pending_path));refused(lambda:apply(pending,pending_path))
    assert len(api.writes)==5
    replacement,replacement_path=prepare('public',[443])
    api.rules=ops.lane_rules('public',[80])
    refused(lambda:apply(replacement,replacement_path))
    assert len(api.writes)==5


def docktail(ops, work):
    shutil.rmtree('hosting',ignore_errors=True)
    record=json.loads((FIXTURE/'place-record.json').read_text());api=StandIn()
    path=work/'docktail-reuse.json'
    effect=ops.docktail_effect(record,'canary',80,None)
    ops.register_docktail(record,'canary',80,path,api,lambda *a:None,effect)
    api.definition=None
    try: ops.register_docktail(record,'canary',80,path,api,lambda *a:None,effect)
    except (ValueError,OSError):pass
    else: raise AssertionError('Docktail approval was reused')
    assert len(api.writes)==1


def partial(ops):
    record=json.loads((FIXTURE/'place-record.json').read_text());owned=resources(record)
    state=dict(config=dict(place=record['place']))
    values=dict(root_module=dict(child_modules=[dict(resources=[dict(mode='managed',
        address='module.place.hcloud_firewall.coolify',type='hcloud_firewall',values=owned['firewall'])])]))
    recovery=ops.partial_record(state,values)
    plan=dict(resource_changes=[dict(address='module.place.hcloud_firewall.coolify',type='hcloud_firewall',
        change=dict(actions=['delete'],before=owned['firewall']))])
    ops.destroy_plan_matches(recovery,plan,partial=True)
    bad=copy.deepcopy(plan);bad['resource_changes'].append(dict(address='terraform_data.foreign',type='terraform_data',change=dict(actions=['delete'],before={'id':'foreign'})))
    refused(lambda:ops.destroy_plan_matches(recovery,bad,partial=True))
    foreign=copy.deepcopy(values);foreign['root_module']['child_modules'][0]['resources'][0]['address']='hcloud_firewall.foreign'
    refused(lambda:ops.partial_record(state,foreign))
    foreign=copy.deepcopy(plan);foreign['resource_changes'][0]['address']='hcloud_firewall.foreign'
    refused(lambda:ops.destroy_plan_matches(recovery,foreign,partial=True))
    changed=copy.deepcopy(owned['firewall']);changed['id']+=1
    calls=[];api=StandIn()
    gate=lambda *a:calls.append(a)
    refused(lambda:ops.retire(recovery,{'firewall':changed},'plan','approval',api,gate,lambda n:n,partial=True))
    refused(lambda:ops.retire(recovery,{'firewall':owned['firewall']},'plan','approval',api,gate,lambda n:'wrong',partial=True))
    assert not calls
    refused(lambda:ops.retire(recovery,{'firewall':owned['firewall']},'plan','approval',api,lambda *a:(_ for _ in ()).throw(ValueError('Missing saved-plan approval')),lambda n:n,partial=True))
    remaining=ops.retire(recovery,{'firewall':owned['firewall']},'plan','approval',api,gate,lambda n:n,partial=True)
    assert calls==[('plan','approval')]


def images(ops):
    record=json.loads((FIXTURE/'place-record.json').read_text());api=StandIn()
    api.inventory=lambda kind:[{'id':902}] if kind=='images' else []
    assert ops.retire(record,resources(record),'plan','approval',api,lambda *a:None,lambda n:n).get('images')==[{'id':902}]
    api.inventory=lambda kind: (_ for _ in ()).throw(OSError('Synthetic unreadable images')) if kind=='images' else []
    assert ops.retire(record,resources(record),'plan','approval',api,lambda *a:None,lambda n:n).get('images','missing') is None


def recovery_cli(work, checks):
    import sys
    from contextlib import contextmanager
    from types import SimpleNamespace
    import subprocess
    sys.path.insert(0,str(RECIPE/'scripts'))
    try:
        import retire as cli
        ops=load(RECIPE/'scripts/place.py')
        record=json.loads((FIXTURE/'place-record.json').read_text());owned=resources(record)
        recovery=dict(place=record['place'],tools=[],infrastructure=dict(firewall_id=102))
        progress=work/'partial-progress.json'
        progress.write_text(json.dumps(dict(root=str(Path.cwd()),recovery_record=recovery,
            provider_plans={'0'*64:ops.fingerprint('synthetic-only')})))
        plan=dict(resource_changes=[dict(address='module.place.hcloud_firewall.coolify',type='hcloud_firewall',
            change=dict(actions=['delete'],before=owned['firewall']))])
        @contextmanager
        def saved(*args):yield ('synthetic-plan','0'*64)
        @contextmanager
        def terminal():yield None
        applied=[]
        gate=SimpleNamespace(require_encryption=lambda:None,check_version=lambda:None,saved_plan=saved,
            planned_identity=lambda *a:None,tofu=lambda *a:subprocess.CompletedProcess(a,0,json.dumps(plan).encode(),b''),
            apply=lambda *a:applied.append(a),terminal=terminal,typed=lambda *a:record['place']['name'])
        api=StandIn();api.owned_resources=lambda partial:dict(firewall=owned['firewall'])
        args=['retire','--partial-progress',str(progress),'--plan','synthetic-plan','--approval','synthetic-approval']
        with patch.object(sys,'argv',args),patch.object(cli,'API',return_value=api),patch.object(cli,'approval_gate',return_value=gate),patch.object(cli,'hidden_value',return_value='synthetic-only'):
            assert cli.main()==0 and len(applied)==1
            plan['resource_changes'].append(dict(type='terraform_data',address='terraform_data.foreign',change=dict(actions=['delete'],before=dict(id='foreign'))))
            assert cli.main()!=0 and len(applied)==1
    finally:sys.path.pop(0)


def real_foreign_destroy(work, checks):
    # Repeat the review probe with an actual encrypted destroy plan containing
    # a built-in resource. No provider or download is involved.
    import os,sys
    import approval_gate_checks as fixtures
    project=work/'foreign-destroy';project.mkdir()
    (project/'main.tf.json').write_text(json.dumps(dict(resource=dict(terraform_data=dict(foreign=dict(input='synthetic-only'))))))
    shutil.copyfile(checks.ROOT/'tofu/encryption.tf',project/'encryption.tf')
    fixtures.tofu(project,'init','-input=false')
    fixtures.tofu(project,'apply','-auto-approve','-input=false')
    with checks.directory(project),patch.dict(os.environ,fixtures.ENV):
        gate=checks.load();plan=project/'destroy.plan';gate.plan(plan,destroy=True)
        approved=project/'approved.json';approved.write_text(json.dumps(fixtures.record_for(gate,plan)))
        with gate.saved_plan(plan) as (snapshot,sha):
            shown=json.loads(gate.tofu('show','-json',snapshot).stdout)
        ops=load(RECIPE/'scripts/place.py')
        record=json.loads((FIXTURE/'place-record.json').read_text())
        refused(lambda:ops.destroy_plan_matches(record,shown,partial=True))
        assert gate.tofu('state','list').stdout.strip()==b'terraform_data.foreign'
    print('Real encrypted foreign-resource destroy plan refused by partial recovery.')


def exercise(work, checks):
    ops=load(RECIPE/'scripts/place.py');gate=checks.load()
    # FileExistsError is a refusal from an exclusive receipt, like a gate refusal.
    def rejected(call):
        try: call()
        except (ValueError,OSError):return
        raise AssertionError('A protected operation was accepted')
    global refused
    refused=rejected
    for test in (lanes,docktail,partial,images):
        if test==lanes:test(ops,gate,work)
        elif test==docktail:test(ops,work)
        else:test(ops)
    recovery_cli(work,checks)
    real_foreign_destroy(work,checks)
    source=(RECIPE/'scripts/place.py').read_text()
    changes=[
        ('consumed lane approval',"os.O_WRONLY | os.O_CREAT | os.O_EXCL",'os.O_WRONLY | os.O_CREAT | os.O_TRUNC',lanes),
        ('attempt recorded before write',"    receipt = start_attempt(effect, approval, journal)\n    api.set_firewall(effect[\"firewall_id\"], effect[\"rules\"])","    api.set_firewall(effect[\"firewall_id\"], effect[\"rules\"])\n    receipt = start_attempt(effect, approval, journal)",lanes),
        ('observed firewall state',"effect.get('observed') == observed",'True',lanes),
        ('docktail approval reuse',"    receipt = start_attempt(effect, approval, journal)\n    api.register_service", "    receipt = Path('unused.json')\n    receipt.write_text('{}')\n    api.register_service",docktail),
        ('partial resource origin',"item.get('address') in expected",'True',partial),
        ('partial plan address',"item.get('address') == address",'True',partial),
        ('partial live ownership','str(resource["id"]) == str(expected[kind + "_id"])','True',partial),
        ('partial typed name','confirm(name) == name','True',partial),
        ('partial saved-plan gate','    gate(saved_destroy, approval)','    pass',partial),
        ('retained images',', "images"','',images),
    ]
    for name,old,new,test in changes:
        assert old in source,name
        path=work/'fix-mutated.py';path.write_text(source.replace(old,new,1));mutated=load(path)
        try:
            if test==lanes:test(mutated,gate,work)
            elif test==docktail:test(mutated,work)
            else:test(mutated)
        except AssertionError:print('Protection removal detected: '+name)
        else:raise AssertionError('Protection removal escaped: '+name)
        path.write_text(source)
    print('Approval reuse, partial recovery and image regressions passed.')
