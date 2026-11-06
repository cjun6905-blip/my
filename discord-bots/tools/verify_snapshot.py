"""Verify a public snapshot without importing Bot code or contacting any service."""
import ast,hashlib,json,pathlib,re,sys
ROOT=pathlib.Path(__file__).resolve().parents[1] if pathlib.Path(__file__).parent.name=='tools' else pathlib.Path(__file__).parent/'my/discord-bots'
forbidden={'.pem','.key','.p12','.pfx','.db','.sqlite','.sqlite3','.log','.zip','.gz','.tgz','.pyc'}
patterns=[re.compile(p) for p in [r'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}',r'AIza[0-9A-Za-z_-]{30,}',r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',r'\b[MNOP][A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}\b',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+']]
fleet=json.loads((ROOT/'fleet.json').read_text());assert fleet['bot_count']==len(fleet['profiles'])==35
errors=[];source_count=python_count=jsonc_count=0
for bot in fleet['profiles']:
 base=ROOT/bot['path'];manifest=json.loads((base/'snapshot-manifest.json').read_text())
 for item in manifest['files']:
  p=base/item['path']
  if not p.is_file():errors.append(str(p.relative_to(ROOT))+': missing');continue
  raw=p.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=item['published_sha256']:errors.append(str(p.relative_to(ROOT))+': hash mismatch')
  source_count+=1
for p in ROOT.rglob('*'):
 if not p.is_file():continue
 rel=p.relative_to(ROOT)
 if p.suffix.lower() in forbidden or '.runtime' in rel.parts or p.name in {'.env','.speech.env','.imagegen.env','.imagegen-openai.env'}:errors.append(str(rel)+': forbidden runtime file')
 data=p.read_bytes()
 try:text=data.decode('utf-8')
 except UnicodeDecodeError:continue
 if any(pattern.search(text) for pattern in patterns):errors.append(str(rel)+': credential pattern')
 if p.suffix=='.py':
  try:ast.parse(text);python_count+=1
  except SyntaxError:errors.append(str(rel)+': Python syntax error')
 if p.suffix=='.json':
  try:json.loads(text)
  except ValueError:
   if p.name.startswith('tsconfig') and 'compilerOptions' in text:jsonc_count+=1
   else:errors.append(str(rel)+': invalid JSON')
if errors:
 print(json.dumps({'passed':False,'errors':errors},ensure_ascii=False));raise SystemExit(1)
print(json.dumps({'passed':True,'bots':35,'runtime_source_files':source_count,'python_files':python_count,'typescript_jsonc_configs':jsonc_count,'credential_findings':0,'runtime_data_files':0}))
