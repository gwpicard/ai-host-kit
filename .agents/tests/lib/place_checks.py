"""Offline place rehearsals and protection removals. No provider API calls."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch
from checks import ROOT, run
import approval_gate_checks as checks

RECIPE = ROOT / '.agents/skills/recipes/coolify-hetzner'
FIXTURE = ROOT / '.agents/tests/fixtures/place'


def load(path):
    spec = importlib.util.spec_from_file_location('place_ops', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refused(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('A protected operation was accepted')


class StandIn:
    def __init__(self):
        self.writes = []
        self.rules = []
        self.definition = None
    def coolify_team(self): return {'id': 1}
    def set_firewall(self, identity, rules):
        self.writes.append(('firewall', identity, rules)); self.rules = rules
    def firewall_rules(self, identity): return self.rules
    def service_definition(self, name): return self.definition
    def service_ready(self, name): return True
    def register_service(self, effect):
        self.writes.append(('docktail', effect)); self.definition = {'ports': ['tcp:443']}
    def inventory(self, kind): return [{'id': 901}] if kind == 'volumes' else []


def resources(record):
    return {kind: dict(id=record['infrastructure'][kind + '_id'],
                      name='coolify' if kind == 'firewall' else record['place']['name'],
                      labels={'purpose':'ai-host-kit', 'place':record['place']['name']})
            for kind in ('server', 'firewall', 'ssh_key')}


def outcomes(ops, gate, work):
    record = json.loads((FIXTURE / 'place-record.json').read_text())
    owned = resources(record)
    api = StandIn()
    effect = ops.lane_effect(record, 'public', [80, 443])
    no_approval = work / 'missing-effect.json'
    refused(lambda: ops.set_lane(record, owned, 'public', [80, 443], no_approval, api, gate.match_effect))
    assert not api.writes
    # Synthetic approval applies only to stand-ins. Never a person's approval.
    approval = work / 'effect.json'
    approval.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(effect),effect=effect['effect'],words='Synthetic fixture approval',approved_at='2026-11-06T12:00:00Z',method='foreground-terminal')))
    ops.set_lane(record, owned, 'public', [80, 443], approval, api, gate.match_effect)
    assert api.rules == ops.lane_rules('public', [80, 443])
    refused(lambda: ops.set_lane(record, owned, 'public', [443], approval, api, gate.match_effect))
    for kind in owned:
        bad = copy.deepcopy(owned); bad[kind]['id'] += 1
        refused(lambda: ops.set_lane(record, bad, 'public', [80, 443], approval, api, gate.match_effect))
    for kind in owned:
        for field in ('name','labels'):
            bad=copy.deepcopy(owned)
            bad[kind][field]='wrong' if field=='name' else {'purpose':'other','place':'other'}
            refused(lambda:ops.set_lane(record,bad,'public',[80,443],approval,api,gate.match_effect))
    api.coolify_team=lambda:None
    refused(lambda:ops.set_lane(record,owned,'public',[80,443],approval,api,gate.match_effect))
    api.coolify_team=lambda:{'id':1}
    refused(lambda: ops.lane_rules('public', [8080]))
    refused(lambda: ops.lane_rules('internal', [443]))
    refused(lambda: ops.lane_rules('public', [True]))
    api.definition = {'ports': ['tcp:80']}
    refused(lambda: ops.register_docktail(record, 'canary', 8080, approval, api, lambda e,a: None))
    assert len(api.writes) == 1
    calls = []
    rows = ops.check_place(record, lambda host, port: calls.append(port) or False,
                           lambda address: '4.3.23', lambda: '3.9.0')
    assert 8080 in calls and all(status == 'passed' for _, status in rows)
    assert ops.check_place(record, lambda *a: True, lambda a: '4.3.23', lambda:'3.9.0')[0][1] == 'failed'
    assert ops.scoped_mcp(['read','read:sensitive','write','deploy'],'3.9.0')['args'][-1].endswith('@3.9.0')
    refused(lambda: ops.scoped_mcp(['root'],'3.9.0'))
    refused(lambda: ops.scoped_mcp(['read','read:sensitive','write','deploy'],'latest'))
    destroyed = []
    apply = lambda plan, approval: destroyed.append(plan)
    refused(lambda: ops.retire(record, owned, 'destroy-plan', approval, api, apply, lambda name: 'wrong'))
    assert not destroyed
    remaining = ops.retire(record, owned, 'destroy-plan', approval, api, apply, lambda name:name)
    assert destroyed == ['destroy-plan'] and remaining['volumes'] == [{'id':901}]
    # Positive and negative registration read-back paths.
    api.definition = None
    registered = []
    effect = ops.register_docktail(record,'canary',8080,None,api,lambda e,a:registered.append(e))
    assert registered == [effect] and effect['labels']['docktail.service.service-port'] == '443'
    destroy = {'resource_changes':[dict(type=kind,change={'actions':['delete'],'before':owned[label]})
               for kind,label in [('hcloud_server','server'),('hcloud_firewall','firewall'),('hcloud_ssh_key','ssh_key')]]}
    ops.destroy_plan_matches(record,destroy)
    changed=copy.deepcopy(destroy); changed['resource_changes'][0]['change']['actions']=['create']
    refused(lambda:ops.destroy_plan_matches(record,changed))
    changed=copy.deepcopy(destroy); changed['resource_changes'][0]['change']['before']['id']+=1
    refused(lambda:ops.destroy_plan_matches(record,changed))
    changed=copy.deepcopy(destroy); changed['resource_changes'].pop()
    refused(lambda:ops.destroy_plan_matches(record,changed))
    changed=copy.deepcopy(destroy); changed['resource_changes'].append(copy.deepcopy(destroy['resource_changes'][0]))
    refused(lambda:ops.destroy_plan_matches(record,changed))



def mutations(work):
    source = (RECIPE / 'scripts/place.py').read_text()
    cases = [
        ('ownership','str(resource["id"]) == str(expected[kind + "_id"])','True'),
        ('ownership labels','resource.get("labels") == {"purpose": "ai-host-kit", "place": name}','True'),
        ('ownership name','resource["name"] == ("coolify" if kind == "firewall" else name)','True'),
        ('claimed account read','api.coolify_team() is not None','True'),
        ('lane approval','    gate(effect, approval)\n    api.set_firewall','    api.set_firewall'),
        ('typed place name','confirm(name) == name','True'),
        ('root refusal','set(scopes) == SCOPES and len(scopes) == len(SCOPES)','True'),
        ('MCP pin','version == PINS["mcp"]','True'),
        ('write-once ports','before is None or before.get("ports") == ["tcp:443"]','True'),
        ('outside probe','PROBE_PORTS = {22, 80, 443, 8000, 8080, 6001, 6002}','PROBE_PORTS = {22, 80, 443, 8000, 6001, 6002}'),
        ('destroy ownership','    ownership(record, found)','    pass'),
        ('check result','status = "passed" if type(observed) is bool and observed == (port in approved) else "failed"','status = "passed"'),
    ]
    for name, old, new in cases:
        assert old in source and old != new, name
        path = work / 'mutated.py'; path.write_text(source.replace(old,new,1))
        try:
            outcomes(load(path), checks.load(), work)
        except AssertionError:
            print('Protection removal detected: ' + name)
        else:
            raise AssertionError('Protection removal escaped: ' + name)


def module(work):
    if not shutil.which('tofu'):
        print('could-not-run: OpenTofu 1.13.2 is required')
        raise SystemExit(2)
    target = work / 'module'
    shutil.copytree(RECIPE / 'tofu/hetzner-server', target, ignore=shutil.ignore_patterns('.terraform','*.tfstate*'))
    cache = RECIPE / 'tofu/hetzner-server/.terraform/providers'
    if cache.is_dir():
        shutil.copytree(cache, target / '.terraform/providers')
    run(['tofu','init','-backend=false','-input=false','-lockfile=readonly'],cwd=target)
    run(['tofu','validate'],cwd=target)
    events = run(['tofu','test','-verbose','-json'],cwd=target)
    plan = next(json.loads(line)['test_plan'] for line in events.stdout.splitlines() if json.loads(line).get('type')=='test_plan')
    summary = checks.load().summarise(plan)
    text = '\n'.join(summary['changes'])
    for resource in ('hcloud_server.place','hcloud_firewall.coolify','hcloud_ssh_key.place'):
        assert resource in text
    assert '0.0.0.0/0' not in '\n'.join(summary['internet'])
    assert any('no public inbound ports' in line for line in summary['internet'])
    assert summary == json.loads((FIXTURE/'fresh.summary.json').read_text())
    # The saved fixture comes from the same mocked plan; no ordinary cloud plan runs.
    fixture = json.loads((FIXTURE / 'fresh.show.json').read_text())
    assert {r['address'] for r in fixture['resource_changes']} == {r['address'] for r in plan['resource_changes']}
    source = (target/'main.tf').read_text()
    changes = [
        ('attached firewall','firewall_ids = [hcloud_firewall.coolify.id]','firewall_ids = []'),
        ('inbound default','name   = "coolify"','name   = "wrong"'),
        ('IPv6 coverage','ipv6_enabled = false','ipv6_enabled = true'),
        ('placeholder','cloud_init = file("${path.module}/cloud-init.sh")','cloud_init = "{{UNSET_1}}"'),
    ]
    for name, old, new in changes:
        assert old in source, name
        (target/'main.tf').write_text(source.replace(old,new,1))
        result = subprocess.run(['tofu','test','-no-color'],cwd=target,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        assert result.returncode != 0, name
        print('Module protection removal detected: ' + name)
    (target/'main.tf').write_text(source)
    # The pinned provider cannot consume a genuinely ephemeral bootstrap key.
    ephemeral=source.replace('cloud_init = file("${path.module}/cloud-init.sh")',
             'cloud_init = "${file("${path.module}/cloud-init.sh")}${var.bootstrap_key}"')
    ephemeral+='\nvariable "bootstrap_key" {\n type = string\n sensitive = true\n ephemeral = true\n default = "synthetic-only"\n}\n'
    (target/'main.tf').write_text(ephemeral)
    result=subprocess.run(['tofu','test','-no-color'],cwd=target,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    assert result.returncode != 0 and b'ephemeral' in result.stdout.lower()
    (target/'main.tf').write_text(source)
    print('Pinned provider refuses an ephemeral user-data value; no bootstrap key is retained by this module.')
    boot = target/'cloud-init.sh'; original=boot.read_text()
    for name, old, new in [('IPv4 apt','Acquire::ForceIPv4','Acquire::Alternate'),('tailnet order','tailscale ip -4','true')]:
        boot.write_text(original.replace(old,new))
        assert subprocess.run(['tofu','test','-no-color'],cwd=target,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).returncode != 0, name
        boot.write_text(original)
        print('Module protection removal detected: ' + name)


def record_checks(work):
    gate=checks.load()
    validator,formats=gate.records.dependencies()
    schema=json.loads((ROOT/'contracts/place-record.schema.json').read_text())
    record=json.loads((FIXTURE/'place-record.json').read_text())
    assert not list(validator(schema,format_checker=formats).iter_errors(record))
    for change in ('ownership','phase','tools','address','version'):
        bad=copy.deepcopy(record)
        if change=='ownership': del bad['infrastructure']['server_id']
        elif change=='phase': del bad['phase']
        elif change=='tools': bad['tools']=[{'name':'tool','host_record':'hosting/host-record.json'}]
        elif change=='address': bad['infrastructure']['tailnet_ipv4']='not-an-ip'
        else: bad['infrastructure']['versions']['mcp']='latest'
        assert list(validator(schema,format_checker=formats).iter_errors(bad)),change
    # Removing the place-stage required fields makes the same invalid record pass.
    changed=copy.deepcopy(schema); changed['properties']['infrastructure']['required'].remove('server_id')
    bad=copy.deepcopy(record); del bad['infrastructure']['server_id']
    assert not list(validator(changed,format_checker=formats).iter_errors(bad))
    print('Place-stage record protections checked against valid and invalid fixtures.')


def adapter_checks():
    import sys
    sys.path.insert(0,str(RECIPE/'scripts'))
    try:
        import api as transport
        import lane as lane_cli
        import retire as retire_cli
        record=json.loads((FIXTURE/'place-record.json').read_text())
        client=transport.API(record,'synthetic-only')
        calls=[]
        def request(method,url,token,body=None):
            calls.append((method,url,body))
            if url.endswith('/actions/set_rules'): return {'actions':[{'id':7}]}
            if url.endswith('/actions/7'): return {'action':{'status':'success'}}
            if url.endswith('/firewalls/102'): return {'firewall':{'rules':[]}}
            return {'volumes':[{'id':901}],'meta':{'pagination':{'next_page':None}}}
        client.request=request
        client.set_firewall(102,[])
        assert client.firewall_rules(102)==[]
        assert client.inventory('volumes')==[{'id':901}]
        assert [method for method,url,body in calls]==['POST','GET','GET','GET']
        assert all(url.startswith('https://api.hetzner.cloud/v1/') for method,url,body in calls)
        with tempfile.TemporaryDirectory(prefix='ai-host-kit-place-cli-') as tmp:
            folder=Path(tmp)
            effect=folder/'effect.json'; approval=folder/'approval.json'; new_record=folder/'record.json'
            command=['lane','prepare','--record',str(FIXTURE/'place-record.json'),'--lane','public','--port','443','--effect',str(effect)]
            with patch.object(sys,'argv',command): assert lane_cli.main()==0
            gate=checks.load(); value=json.loads(effect.read_text())
            approval.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(value),effect=value['effect'],words='Synthetic fixture approval',approved_at='2026-11-06T12:00:00Z',method='foreground-terminal')))
            fake=StandIn(); fake.owned_resources=lambda:resources(record)
            command[1]='apply'; command+=['--approval',str(approval),'--new-record',str(new_record)]
            with patch.object(sys,'argv',command), patch.object(lane_cli,'API',return_value=fake), patch.object(lane_cli.getpass,'getpass',return_value='synthetic-only'):
                assert lane_cli.main()==0
                assert new_record.is_file() and len(fake.writes)==1
                assert lane_cli.main()!=0 and len(fake.writes)==1
            # The retire adapter is rehearsed with a fake saved-plan reader;
            # the shared gate suite separately uses real encrypted saved plans.
            from types import SimpleNamespace
            from contextlib import contextmanager
            owned=resources(record)
            destroy={'resource_changes':[dict(type=kind,change={'actions':['delete'],'before':owned[label]}) for kind,label in [('hcloud_server','server'),('hcloud_firewall','firewall'),('hcloud_ssh_key','ssh_key')]]}
            @contextmanager
            def saved(*args): yield ('synthetic-plan','0'*64)
            @contextmanager
            def terminal(): yield None
            applied=[]
            retired=SimpleNamespace(require_encryption=lambda:None,check_version=lambda:None,saved_plan=saved,
                 planned_identity=lambda *a:None,tofu=lambda *a:subprocess.CompletedProcess(a,0,json.dumps(destroy).encode(),b''),
                 apply=lambda *a:applied.append(a),terminal=terminal,typed=lambda *a:record['place']['name'])
            command=['retire','--record',str(FIXTURE/'place-record.json'),'--plan','synthetic-plan','--approval',str(approval)]
            with patch.object(sys,'argv',command),patch.object(retire_cli,'API',return_value=fake),patch.object(retire_cli,'approval_gate',return_value=retired),patch.object(retire_cli.getpass,'getpass',return_value='synthetic-only'):
                assert retire_cli.main()==0 and len(applied)==1
                destroy['resource_changes'][0]['change']['actions']=['create']
                assert retire_cli.main()!=0 and len(applied)==1

    finally: sys.path.pop(0)
    print('Cloud route adapter rehearsed with an in-memory transport.')


def summary_removal(work):
    fixture=json.loads((FIXTURE/'fresh.show.json').read_text())
    expected=json.loads((FIXTURE/'fresh.summary.json').read_text())
    assert checks.load().summarise(fixture)==expected
    scratch=work/'summary-skill'; shutil.copytree(checks.SKILL,scratch)
    path=scratch/'scripts/approval_gate.py'; source=path.read_text()
    old="            result['internet'].append(f'{name}: no public inbound ports are opened by these firewall rules.')"
    assert old in source
    path.write_text(source.replace(old,'            pass',1))
    try: assert checks.load(scratch).summarise(fixture)==expected
    except AssertionError: print('Summary protection removal detected: fresh firewall port statement')
    else: raise AssertionError('Summary protection removal escaped')


def main():
    if checks.load().records.dependencies() is None:
        print('could-not-run: schema packages are missing')
        raise SystemExit(2)
    for relative in ['scripts/place.py','scripts/check.py','scripts/api.py','scripts/lane.py','scripts/retire.py','tofu/hetzner-server/main.tf','tofu/hetzner-server/cloud-init.sh','tofu/hetzner-server/.terraform.lock.hcl']:
        bundled=ROOT/'.agents/skills/host-fit/resources/recipes/coolify-hetzner'/relative
        assert bundled.is_file() and bundled.read_bytes()==(RECIPE/relative).read_bytes(),relative
    with tempfile.TemporaryDirectory(prefix='ai-host-kit-place-checks-') as temporary:
        work=Path(temporary)
        outcomes(load(RECIPE/'scripts/place.py'),checks.load(),work)
        mutations(work)
        module(work)
        summary_removal(work)
        record_checks(work)
        adapter_checks()
        from place_s3_checks import exercise, protection_removals
        exercise(work, checks)
        protection_removals(work, checks)
    print('Offline place checks passed; no live provider or model was used.')


if __name__ == '__main__': main()
