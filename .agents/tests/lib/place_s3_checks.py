from urllib.parse import urlsplit
import http.server,threading,tempfile,subprocess,os,json,hashlib,copy,io
from contextlib import redirect_stdout, redirect_stderr, contextmanager
from unittest.mock import patch
from pathlib import Path
class S3(http.server.BaseHTTPRequestHandler):
 objects={}
 def log_message(self,*a): pass
 def do_GET(self):
  original = self.path
  self.path = urlsplit(self.path).path
  if 'list-type=' in original:
   payload=b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>test-state</Name><IsTruncated>false</IsTruncated></ListBucketResult>'
  elif self.path in self.objects: payload=self.objects[self.path]
  else:
   self.send_response(404); self.end_headers(); return
  self.send_response(200); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)
 def do_HEAD(self):
  self.path = urlsplit(self.path).path
  self.send_response(200 if self.path in self.objects else 404); self.end_headers()
 def do_PUT(self):
  self.path = urlsplit(self.path).path
  n=int(self.headers.get('Content-Length',0)); value=self.rfile.read(n)
  if self.headers.get('If-None-Match')=='*' and self.path in self.objects:
   self.send_response(412); self.end_headers(); return
  self.objects[self.path]=value; self.send_response(200); self.send_header('ETag','"'+hashlib.md5(value).hexdigest()+'"'); self.end_headers()
 def do_DELETE(self):
  self.path = urlsplit(self.path).path
  self.objects.pop(self.path,None); self.send_response(204); self.end_headers()

def exercise(work, checks):
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),S3)
 assert server.server_port != 3000
 S3.objects={}
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  p=work/'s3'; p.mkdir()
  (p/'encryption.tf').write_bytes((checks.ROOT/'tofu/encryption.tf').read_bytes())
  endpoint=f'http://127.0.0.1:{server.server_port}'
  settings=dict(bucket='test-state',key='place/state',region='fsn1',endpoints={'s3':endpoint},workspace_key_prefix='places',use_path_style=True,skip_credentials_validation=True,skip_region_validation=True,skip_requesting_account_id=True,skip_metadata_api_check=True,skip_s3_checksum=True,shared_credentials_files=['/dev/null'],shared_config_files=['/dev/null'],use_lockfile=True,max_retries=1)
  (p/'main.tf.json').write_text(json.dumps({'terraform':{'backend':{'s3':settings}},'resource':{'terraform_data':{kind:{'input':'synthetic-only'} for kind in ('server','firewall','key_resource')}},'output':{key:{'value':value} for key,value in dict(server_id=101,firewall_id=102,ssh_key_id=103,ipv4_address='192.0.2.10').items()}}))
  env={k:v for k,v in os.environ.items() if not k.startswith(('AWS_','TF_','TOFU_'))}
  env.update(TF_VAR_host_state_passphrase='synthetic-state-passphrase')
  creds=('synthetic-access', 'synthetic-secret')
  child=dict(env,AWS_ACCESS_KEY_ID=creds[0],AWS_SECRET_ACCESS_KEY=creds[1],AWS_EC2_METADATA_DISABLED='true',AWS_SHARED_CONFIG_FILE='/dev/null',AWS_SHARED_CREDENTIALS_FILE='/dev/null')
  result=subprocess.run(['tofu','init','-input=false'],cwd=p,env=child,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
  assert result.returncode == 0, 'S3 stand-in init failed; raw output withheld'
  metadata=p/'.terraform/terraform.tfstate'; saved=json.loads(metadata.read_text())
  assert all(c not in metadata.read_text() for c in creds)
  gate=checks.load(); gate.S3_CREDENTIALS=creds
  # Only this in-process test admits the loopback endpoint. No environment or CLI bypass.
  gate.S3_ENDPOINTS={endpoint:'fsn1'}
  with patch.dict(os.environ,env,clear=True), checks.directory(p), redirect_stdout(io.StringIO()):
   plan=p/'plan'; gate.plan(plan)
   original=gate.target_identity()
   before=dict(S3.objects)
   try: gate.apply(plan,p/'missing-approval.json')
   except ValueError: pass
   else: raise AssertionError('Missing plan approval was accepted')
   assert S3.objects == before
   for field, value in [('bucket','other-state'),('key','other/state'),('region','hel1'),('workspace_key_prefix','other'),('endpoints',{'s3':'https://hel1.your-objectstorage.com'}),('use_path_style',False),('profile','alternative')]:
    altered=copy.deepcopy(saved); altered['backend']['config'][field]=value; metadata.write_text(json.dumps(altered))
    try:
     target=gate.target_identity()
     assert target != original, field
     try: gate.planned_identity(plan,gate.digest(plan.read_bytes()))
     except ValueError: pass
     else: raise AssertionError('Changed destination accepted: '+field)
    except ValueError: pass
    finally: metadata.write_text(json.dumps(saved))
   for key in ['AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_PROFILE','AWS_CONFIG_FILE','AWS_SHARED_CREDENTIALS_FILE','AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_S3','AWS_REGION','AWS_DEFAULT_REGION','AWS_WEB_IDENTITY_TOKEN_FILE','AWS_CONTAINER_CREDENTIALS_FULL_URI','AWS_CA_BUNDLE','HTTPS_PROXY','http_proxy','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR','TF_WORKSPACE','TOFU_ENCRYPTION']:
    with patch.dict(os.environ,{key:'synthetic-override'}):
     try: gate.target_identity()
     except ValueError: pass
     else: raise AssertionError('Ambient override accepted: '+key)
   gate.S3_CREDENTIALS=('different-synthetic-access',creds[1])
   assert gate.target_identity() != original
   gate.S3_CREDENTIALS=creds
   sha=gate.digest(plan.read_bytes()); summary=gate.read_plan(plan)
   record=dict(schema_version='1.0',plan_sha256=sha,approved_at='2026-11-06T12:00:00Z',words='Synthetic local fixture only',confirmation='approve '+gate.short_hash(sha),method='terminal-checksum',summary=summary,target=original)
   approval=p/'synthetic-approval.json'; approval.write_text(json.dumps(record))
   partial_cli(p, checks, gate, creds)
   blob=S3.objects['/test-state/place/state']
   assert b'synthetic-only' not in blob and b'synthetic-state-passphrase' not in blob
   assert all(c.encode() not in blob for c in creds)
   assert b'encrypted_data' in blob and '/test-state/place/state.tflock' not in S3.objects
   with patch.dict(os.environ,{'TF_VAR_host_state_passphrase':'wrong-synthetic-passphrase'}), redirect_stderr(io.StringIO()) as errors:
    assert gate.tofu('show','-json').returncode != 0
   assert 'check the storage keys and passphrase' in errors.getvalue()
   assert 'wrong-synthetic-passphrase' not in errors.getvalue()
   # A workspace selects a distinct object prefix and is identity-bound.
   assert gate.tofu('workspace','new','other').returncode == 0
   assert gate.target_identity() != original
   assert gate.tofu('workspace','select','default').returncode == 0
   assert gate.target_identity() == original
  print('S3 loopback checks passed: encrypted state, lock lifecycle, approval, destination and credential identity, overrides and workspaces.')
 finally:
  server.shutdown(); server.server_close()


def settings_checks(gate, settings):
 good=copy.deepcopy(settings)
 good['endpoints']={'s3':'https://fsn1.your-objectstorage.com'}
 gate.S3_ENDPOINTS={'https://fsn1.your-objectstorage.com':'fsn1'}
 gate.s3_settings(good)
 for field,value in [('profile','alternative'),('shared_credentials_files',['/tmp/credentials']),('skip_metadata_api_check',False),('access_key','synthetic-access'),('endpoints',{'s3':'https://other.invalid'}),('region','hel1')]:
  bad=copy.deepcopy(good); bad[field]=value
  try: gate.s3_settings(bad)
  except ValueError: pass
  else: raise AssertionError('Unsafe S3 setting accepted: '+field)


def protection_removals(work, checks):
 import shutil
 settings=json.loads((checks.ROOT/'.agents/skills/recipes/coolify-hetzner/tofu/backend.example.json').read_text())
 settings_checks(checks.load(),settings)
 scratch=work/'mutated-storage-skill'; shutil.copytree(checks.SKILL,scratch)
 path=scratch/'scripts/approval_gate.py'; original=path.read_text()
 for name,old,new in [
  ('S3 credential source',"if set(effective) - allowed or any(effective.get(k) != v for k, v in fixed.items()):",'if False:'),
  ('S3 endpoint pair',"if set(active) != {'s3'} or S3_ENDPOINTS.get(endpoint) != effective.get('region'):",'if False:')]:
  assert old in original,name
  path.write_text(original.replace(old,new,1))
  try: settings_checks(checks.load(scratch),settings)
  except AssertionError: print('Storage protection removal detected: '+name)
  else: raise AssertionError('Storage protection removal escaped: '+name)
 path.write_text(original)
 actual=checks.load
 for index,(name,old,new) in enumerate([
  ('storage overrides','    if redirecting:','    if False:'),
  ('storage credential identity','str(metadata), credentials_sha','str(metadata)')]):
  assert old in original,name
  path.write_text(original.replace(old,new,1))
  isolated=work/('s3-mutation-'+str(index)); isolated.mkdir()
  with patch.object(checks,'load',side_effect=lambda:actual(scratch)):
   try: exercise(isolated,checks)
   except AssertionError: print('Storage protection removal detected: '+name)
   else: raise AssertionError('Storage protection removal escaped: '+name)
 path.write_text(original)


def credential_order(gate, creds):
 """Observe the actual child environment before any OpenTofu process starts."""
 gate.S3_CREDENTIALS=None
 @contextmanager
 def terminal(): yield None
 def child(*args, **kwargs):
  if args[0][1]=='version':
   assert 'AWS_ACCESS_KEY_ID' not in kwargs['env'] and 'AWS_SECRET_ACCESS_KEY' not in kwargs['env']
   return subprocess.CompletedProcess(args,0,b'{}',b'')
  assert kwargs['env'].get('AWS_ACCESS_KEY_ID') == creds[0], 'OpenTofu reached S3 before storage credentials'
  assert kwargs['env'].get('AWS_SECRET_ACCESS_KEY') == creds[1], 'OpenTofu reached S3 without the secret key'
  return subprocess.CompletedProcess(args,0,b'{}',b'')
 for command in [('show','-json'),('output','-json'),('state','pull'),('workspace','show'),('plan',),('apply',),('init',),('version','-json')]:
  gate.configure_secrets()
  with patch.object(gate,'terminal',terminal), patch.object(gate,'typed',side_effect=list(creds)), patch.object(gate.subprocess,'run',side_effect=child):
   gate.tofu(*command)
  assert gate.S3_CREDENTIALS == (None if command[0]=='version' else creds)


def partial_cli(p, checks, gate, creds):
 """Real encrypted S3 plans and applies; provider and node facts are stand-ins.

 Built-in terraform_data resources replace the three cloud resources. Their
 show JSON is projected onto the owned addresses, so recovery and deletion
 checks run unchanged without contacting a provider.
 """
 import sys
 from place_checks import RECIPE, FIXTURE, resources
 sys.path.insert(0,str(RECIPE/'scripts'))
 try:
  import setup as flow
  import retire as retirement
  record=json.loads((FIXTURE/'place-record.json').read_text())
  owned=resources(record)
  progress=p/'progress.json'
  choice=p/'choice.json'
  choice.write_text(json.dumps(dict(schema_version='1.0',choice=dict(host='coolify-hetzner',proven=False,answers={},accepted_shortfalls=[]))))
  state=dict(root=str(p),config=dict(place=record['place'],encrypted_state=record['encrypted_state']),
             choice_path=str(choice),choice_sha256=flow.fingerprint(json.loads(choice.read_text())),
             journal=flow.journal_identity(p/'place-attempts'),done=[])
  flow.bind_provider(state,p/'plan','synthetic-state-passphrase',gate,remember=True)
  flow.save(progress,state)
  secrets=p/'fixture-secrets.env'
  secrets.write_text('STORAGE_ACCESS_KEY='+creds[0]+'\nSTORAGE_SECRET_KEY='+creds[1]+'\n')
  secrets.chmod(0o600)
  state['config']['secrets']=str(secrets)
  flow.save(progress,state)
  def command(*args):
   with patch.object(sys,'argv',['setup',*args,'--progress',str(progress)]), patch.object(flow,'approval_gate',return_value=gate), patch.object(flow,'prompt',return_value='synthetic-state-passphrase'):
    return flow.main()
  assert command('apply','--plan',str(p/'plan'),'--approval',str(p/'synthetic-approval.json')) == 0
  assert json.loads(progress.read_text())['applied'] is True
  # Failed reads are retried until the deadline; a fake clock keeps this instant.
  import node
  clock=[0]
  def wait(record,read):return node.wait_bootstrap(record,read,sleep=lambda s:clock.__setitem__(0,clock[0]+s),clock=lambda:clock[0],report=lambda m:None)
  with patch.object(flow,'read_node',side_effect=OSError('Synthetic failed bootstrap')) as node_read,patch.object(flow,'wait_bootstrap',side_effect=wait):
   assert command('bootstrap','--address','100.64.0.10') == 1
   assert node_read.call_count>1 and all(call.args==('100.64.0.10',) for call in node_read.call_args_list) and clock[0]==1200
  assert 'record' not in json.loads(progress.read_text())
  credential_order(gate,creds)
  # Remove the helper call only in a disposable skill copy. The same assertion
  # must fail before a child process can reach the bucket, then pass restored.
  import shutil
  scratch=p/'credential-mutation';shutil.copytree(checks.SKILL,scratch)
  source=scratch/'scripts/approval_gate.py';original=source.read_text()
  old="        storage_credentials()"
  assert old in original
  source.write_text(original.replace(old,'        pass',1))
  try: credential_order(checks.load(scratch),creds)
  except AssertionError as error:
   assert 'before storage credentials' in str(error)
   print('Protection removal detected: OpenTofu reached S3 before storage credentials',file=sys.__stdout__)
  else: raise AssertionError('Credential ordering removal escaped')
  source.write_text(original);credential_order(checks.load(scratch),creds)
  actual=gate.tofu
  calls=[]
  def tofu(*args):
   result=actual(*args)
   calls.append(args[0])
   if args[:2] == ('show','-json') and result.returncode == 0:
    shown=json.loads(result.stdout)
    if 'values' in shown:
     shown['values']['root_module']=dict(child_modules=[dict(resources=[dict(mode='managed',
      address='module.place.hcloud_'+kind+('.coolify' if kind=='firewall' else '.place'),
      type='hcloud_'+kind,values=owned[kind]) for kind in owned])])
    for item in shown.get('resource_changes',[]):
     kind='ssh_key' if item['name']=='key_resource' else item['name']
     item.update(address='module.place.hcloud_'+kind+('.coolify' if kind=='firewall' else '.place'),type='hcloud_'+kind)
     item['change']['before']=owned[kind]
    result=subprocess.CompletedProcess(result.args,0,json.dumps(shown).encode(),b'')
   return result
  @contextmanager
  def terminal():
   from types import SimpleNamespace
   yield SimpleNamespace(write=lambda *a:None,flush=lambda:None,fileno=lambda:0)
  api=type('LocalAPI',(),{'owned_resources':lambda self,partial:owned, 'inventory':lambda self,kind:[]})()
  plan=p/'partial-destroy.plan';approval=p/'partial-approval.json'
  with patch.object(gate,'tofu',side_effect=tofu), patch.object(gate,'terminal',terminal), patch.object(retirement,'API',return_value=api), patch.object(retirement,'hidden_value',side_effect=AssertionError('Retirement requested a second project token')):
   # A fresh invocation must prompt before the first direct remote state read.
   gate.S3_CREDENTIALS=None
   with patch.object(gate,'typed',side_effect=list(creds)):
    assert command('plan-destroy','--partial','--plan',str(plan)) == 0
   gate.S3_CREDENTIALS=None
   with patch.object(gate,'typed',side_effect=list(creds)):
    assert command('plan-destroy','--plan',str(p/'full-destroy.plan')) == 0
   recovered=json.loads(progress.read_text())
   assert recovered['recovery_record']['infrastructure']==dict(server_id=101,firewall_id=102,ssh_key_id=103)
   assert plan.is_file() and gate.identity_path(plan).is_file()
   assert command('summary','--plan',str(plan)) == 0
   # Synthetic terminal consent applies only to this disposable loopback place.
   sha=gate.digest(plan.read_bytes())
   with patch.object(gate.termios,'tcflush'), patch.object(gate,'checksum_input',return_value=gate.short_hash(sha)), patch.object(gate,'typed',return_value='Synthetic local retirement approval'):
    assert command('approve','--plan',str(plan),'--approval',str(approval)) == 0
   with patch.object(gate,'typed',return_value=record['place']['name']):
    assert command('retire','--partial','--plan',str(plan),'--approval',str(approval)) == 0
  assert 'apply' in calls and '/test-state/place/state.tflock' not in S3.objects
  os.environ['TF_VAR_host_state_passphrase']='synthetic-state-passphrase'
  shown=actual('show','-json');assert shown.returncode==0
  assert not json.loads(shown.stdout).get('values',{}).get('root_module',{}).get('resources')
  # The public error contains a useful reason, never raw backend diagnostics.
  with patch.object(gate.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'',b'synthetic-private-diagnostic')), redirect_stderr(io.StringIO()) as errors:
   actual('show','-json')
  assert 'check the storage keys and passphrase' in errors.getvalue()
  assert 'synthetic-private-diagnostic' not in errors.getvalue()
  print('Restored credential guard passed every OpenTofu command.',file=sys.__stdout__)
  print('Failed-bootstrap S3 partial CLI retirement passed: recovery, summary, terminal approval, destroy and empty remote state.',file=sys.__stdout__)
 finally:
  sys.path.pop(0)
