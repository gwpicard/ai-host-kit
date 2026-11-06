from urllib.parse import urlsplit
import http.server,threading,tempfile,subprocess,os,json,hashlib,copy,io
from contextlib import redirect_stdout
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
  (p/'main.tf.json').write_text(json.dumps({'terraform':{'backend':{'s3':settings}},'resource':{'terraform_data':{'test':{'input':'synthetic-only'}}}}))
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
   gate.apply(plan,approval)
   blob=S3.objects['/test-state/place/state']
   assert b'synthetic-only' not in blob and b'synthetic-state-passphrase' not in blob
   assert all(c.encode() not in blob for c in creds)
   assert b'encrypted_data' in blob and '/test-state/place/state.tflock' not in S3.objects
   # A workspace selects a distinct object prefix and is identity-bound.
   gate.tofu('workspace','new','other')
   assert gate.target_identity() != original
   gate.tofu('workspace','select','default')
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
