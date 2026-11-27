"""Retirement outcomes in setup progress, through the real setup and retire commands."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from checks import ROOT
import approval_gate_checks as fixtures

RECIPE=ROOT/'.agents/skills/recipes/coolify-hetzner'
FIXTURE=ROOT/'.agents/tests/fixtures/place'
sys.path.insert(0,str(RECIPE/'scripts'))
import setup as flow
import retire as cli
from place import fingerprint

TOKEN='synthetic-only'
OUTPUTS=dict(server_id=101,firewall_id=102,ssh_key_id=103,ipv4_address='192.0.2.10')
CATEGORIES=('servers','firewalls','ssh_keys','volumes','networks','floating_ips','primary_ips',
            'load_balancers','placement_groups','certificates','images')


def owned(record):
    return {kind:dict(id=record['infrastructure'][kind+'_id'],name='coolify' if kind=='firewall' else record['place']['name'],
                      labels={'purpose':'ai-host-kit','place':record['place']['name']})
            for kind in ('server','firewall','ssh_key') if kind+'_id' in record['infrastructure']}


class Cloud:
    def __init__(self,record,listed=None,unreadable=()):
        self.record=record;self.listed=listed or {};self.unreadable=unreadable
    def owned_resources(self,partial=False):return owned(self.record)
    def inventory(self,kind):
        if kind in self.unreadable:raise OSError('Synthetic unreadable category')
        return self.listed.get(kind,[])


class Place:
    """A prepared place whose apply has run, with a journal and one receipt."""
    def __init__(self,work,full=False):
        self.work=work;self.root=work/'root';self.root.mkdir()
        hosting=work/'hosting';hosting.mkdir()
        self.record=json.loads((FIXTURE/'place-record.json').read_text())
        self.choice=hosting/'place-record.json'
        # After the record stage, the choice file holds the created record.
        self.choice.write_text(json.dumps(self.record if full else record_choice(self.record)))
        self.journal=hosting/'place-attempts';self.journal.mkdir()
        (self.journal/'generation').write_text('[1, 2, 3]')
        self.receipt=self.journal/('0'*64+'.json');self.receipt.write_text(json.dumps(dict(status='completed')))
        self.plan=work/'destroy-1.plan';self.plan.write_bytes(b'synthetic encrypted destroy plan')
        self.approval=work/'approval-1.json';self.approval.write_text('{}')
        self.gate=fixtures.load()
        backend=json.loads((RECIPE/'tofu/backend.example.json').read_text())
        state=dict(config=dict(place=self.record['place'],secrets=str(work/'absent.env'),canary_name='canary',backend=backend),
                   choice_path=str(self.choice),choice_sha256=fingerprint(record_choice(self.record)),
                   root=str(self.root),done=[],uncertain=None,journal=[1,2,3],applied=True,outputs=dict(OUTPUTS),
                   provider_plans={self.gate.digest(self.plan.read_bytes()):fingerprint(TOKEN)},
                   saved_plan=str(self.plan),saved_approval=str(self.approval))
        if full:
            state.update(done=list(flow.STEPS),record=self.record,tailnet_suffix='fixture.ts.net',server_uuid='server-one',
                         destination_uuid='destination-one',project_uuid='p',docktail_uuid='d',register_uuid='r')
        else:
            state['recovery_record']=dict(place=self.record['place'],tools=[],infrastructure=dict(
                server_id=101,firewall_id=102,ssh_key_id=103))
        self.progress=hosting/'place-progress.json';self.progress.write_text(json.dumps(state))

    def state(self):return json.loads(self.progress.read_text())

    def command(self,*args,**patches):
        out=io.StringIO();err=io.StringIO()
        with patch.object(sys,'argv',['setup',*map(str,args),'--progress',str(self.progress)]), \
             patch.object(flow,'approval_gate',return_value=self.gate), \
             patch.object(self.gate,'configure_secrets',create=True), \
             patch.object(flow,'prompt',return_value=TOKEN), redirect_stdout(out), redirect_stderr(err):
            status=flow.main()
        return status,out.getvalue(),err.getvalue()

    def retire(self,cloud,partial):
        plan=dict(resource_changes=[dict(address='module.place.'+kind+('.coolify' if kind=='hcloud_firewall' else '.place'),
            type=kind,change=dict(actions=['delete'],before=value)) for kind,value in
            zip(('hcloud_server','hcloud_firewall','hcloud_ssh_key'),owned(self.record).values())])
        @contextmanager
        def saved(*args):yield ('synthetic-plan',self.gate.digest(self.plan.read_bytes()))
        @contextmanager
        def terminal():yield None
        applied=[]
        with patch.object(self.gate,'require_encryption'),patch.object(self.gate,'check_version'), \
             patch.object(self.gate,'saved_plan',saved),patch.object(self.gate,'planned_identity'), \
             patch.object(self.gate,'tofu',return_value=subprocess.CompletedProcess([],0,json.dumps(plan).encode(),b'')), \
             patch.object(self.gate,'apply',side_effect=lambda *a:applied.append(a)), \
             patch.object(self.gate,'terminal',terminal),patch.object(self.gate,'typed',return_value=self.record['place']['name']), \
             patch.object(cli,'API',return_value=cloud):
            args=['retire','--plan',self.plan,'--approval',self.approval]
            args+=['--partial'] if partial else ['--choice',self.choice]
            result=self.command(*args)
        assert len(applied)==1,result
        return result


def record_choice(record):
    choice=copy.deepcopy(record);choice.pop('infrastructure');return choice


def unchanged_evidence(place,before):
    # Receipts and the journal generation are never edited, restored or removed.
    assert sorted(path.name for path in place.journal.iterdir())==sorted(before)
    for name,text in before.items():assert (place.journal/name).read_text()==text


def evidence(place):return {path.name:path.read_text() for path in place.journal.iterdir()}


def planned(place):
    """Run create planning with stand-ins after preflight; report whether a plan was saved."""
    from prerequisite_standins import ready
    calls=[]
    # The prompt stand-in types every value, so a terminal stand-in is present.
    @contextmanager
    def terminal():yield None
    with ready(flow),patch.object(place.gate,'plan',side_effect=lambda *a,**k:calls.append(a)),patch.object(flow,'bind_provider'), \
         patch.object(place.gate,'terminal',terminal):
        status,out,err=place.command('plan','--plan',place.work/'create-2.plan')
    return status,out+err,calls


def completed(work,partial):
    place=Place(work,full=not partial);before=evidence(place);old=place.state()
    status,out,err=place.retire(Cloud(place.record,listed=dict(volumes=[{'id':901}])),partial)
    assert status==0,out+err
    state=place.state()
    assert state['applied'] is False and 'outputs' not in state and state['done']==[] and state['uncertain'] is None,state
    for key in ('record','recovery_record','server_uuid','destination_uuid','project_uuid','docktail_uuid',
                'register_uuid','tailnet_suffix','saved_plan','saved_approval'):
        assert key not in state,key
    assert state['journal']==old['journal'] and state['provider_plans']==old['provider_plans']
    entry=state['retired'][-1]
    assert entry['mode']==('partial' if partial else 'full')
    assert entry['plan_sha256']==place.gate.digest(place.plan.read_bytes())
    assert entry['inventory']['volumes']==[901] and entry['inventory']['servers']==[]
    # Evidence of the destroyed server moves into the entry rather than vanishing.
    assert entry['previous']['outputs']==OUTPUTS and entry['previous']['applied'] is True
    if not partial:
        assert entry['previous']['done']==flow.STEPS and entry['previous']['server_uuid']=='server-one'
    unchanged_evidence(place,before)
    # Bootstrap and later stages cannot act on the retired identities.
    with patch.object(flow,'wait_bootstrap',side_effect=AssertionError('Bootstrap read a retired place')):
        status,out,err=place.command('bootstrap','--address','100.64.0.10')
    assert status!=0 and 'Apply first' in err,err
    with patch.object(flow,'place_lock',side_effect=AssertionError('Discovery locked retired identities')):
        status,out,err=place.command('discover','--server-uuid','server-one','--destination-uuid','destination-one')
    assert status!=0 and 'Bootstrap must pass' in err,err
    if partial:
        # The choice is unchanged, so a new create can be planned.
        status,text,calls=planned(place)
        assert status==0 and len(calls)==1,text
        assert place.state()['saved_plan_kind']=='create'
    else:
        # The record stage replaced the choice; planning refuses before preflight.
        with patch.object(flow.preflight,'run',side_effect=AssertionError('Preflight ran for a replaced choice')):
            status,text,calls=planned(place)
        assert status!=0 and not calls and 'choice file differs' in text,text
    print('Passed: completed '+('partial' if partial else 'full')+' retirement leaves a clean progress with its evidence')


def partial(work):completed(work,True)
def full(work):completed(work,False)


def incomplete(work):
    for name,cloud in (('unreadable',lambda record:Cloud(record,unreadable=('images',))),
                       ('listed',lambda record:Cloud(record,listed=dict(servers=[{'id':101}])))):
        folder=work/name;folder.mkdir()
        place=Place(folder);before=evidence(place);old=place.state()
        status,out,err=place.retire(cloud(place.record),True)
        assert status==(2 if name=='unreadable' else 0),out+err
        assert 'Progress still counts the place as applied' in out,out
        state=place.state()
        assert state['applied'] is True and state['outputs']==OUTPUTS and 'retired' not in state
        assert {key:value for key,value in state.items() if key!='retirement_incomplete'}==old
        assert state['retirement_incomplete'][-1]['plan_sha256']==place.gate.digest(place.plan.read_bytes())
        unchanged_evidence(place,before)
        with patch.object(flow.preflight,'run',side_effect=AssertionError('Preflight ran for an applied place')):
            status,text,calls=planned(place)
        assert status!=0 and not calls and 'incomplete retirement' in text.splitlines()[0],text
    print('Passed: incomplete retirement keeps the place applied and planning refuses with the reason')


def applied(work):
    # Progress left by an older kit still says applied after retirement.
    place=Place(work);before=place.state()
    with patch.object(flow.preflight,'run',side_effect=AssertionError('Preflight ran for an applied place')):
        status,text,calls=planned(place)
    assert status!=0 and not calls and 'do not apply a place twice' in text.splitlines()[0],text
    create=work/'create-2.plan';create.write_bytes(b'synthetic create plan')
    with patch.object(place.gate,'approve',side_effect=AssertionError('A create plan was approved for an applied place')):
        status,out,err=place.command('approve','--plan',create,'--approval',work/'approval-2.json')
    assert status!=0 and 'do not apply a place twice' in err.splitlines()[0],err
    # A destroy plan for the applied place can still be approved.
    approved=[]
    with patch.object(place.gate,'approve',side_effect=lambda *a:approved.append(a)):
        status,out,err=place.command('approve','--plan',place.plan,'--approval',work/'approval-3.json')
    assert status==0 and len(approved)==1,err
    state=place.state()
    assert {key:value for key,value in state.items() if key not in ('saved_plan','saved_approval')}=={
        key:value for key,value in before.items() if key not in ('saved_plan','saved_approval')}
    print('Passed: an applied place refuses a new create at plan and approve, and keeps destroy approval')


def main():
    cases=dict(partial=partial,full=full,incomplete=incomplete,applied=applied)
    previous=Path.cwd()
    try:
        with tempfile.TemporaryDirectory(prefix='place-retirement-') as tmp:
            for name,run in cases.items():
                work=Path(tmp)/name;work.mkdir();run(work)
    finally:os.chdir(previous)
    return 0


if __name__=='__main__':sys.exit(main())
