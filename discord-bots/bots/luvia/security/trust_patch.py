"""Remove only Mozilla's published compromised-chain SPKIs, keeping TLS verification.

Source: https://www.openwall.com/lists/oss-security/2026/10/20/1
Run as root on Linux. System CA configuration is made persistent; private keys
and identity certificates are never touched. Optional PEM backups stay local.
"""
import base64,hashlib,importlib,json,os,pathlib,re,shutil,ssl,subprocess,sys
BLOCKED=set('''bd153ed7b0434f6886b17bce8bbe84ed340c7132d702a8f4fa318f756ecbd6f3
c619e4780ed8e0abeda24ad732567de4383a7ea941338f6d1a7d1b49ac792fe9
8d417db2dd8bf5e3084d1e3f196d583849d81bdd4c00c70b9d39369e96b8c782
e0254c7fcdc265e2f0f8a428dabb75ab4ae039b4872d62f5ee57f0877d5a8a4
43bffa19d6ef651451f6841e019931e96f6f2eaeff28ab4b6f1ce4576de2717
ebed6475c2c2d80fcb199f3fe8dd6e6b3ce60b77eb15d4e42c3dec0c6f5b5105
5c0660a2b164910d8ff589c18e14552e9e0ec237dcefe2cb736d41a4811f81a0
63ecefee431d49523bc1136c4e72d0206a477086caf606cd5cf025686c109cf8
49dd353dc2b919a3770645117d0e60c16115e7d1bc259eefe734b00ea434fe5f
ec4ffa1ad0ac88081314b7aaffef6a91f97cd57291bb5ba686c5415f5eb4f6b6
92c063d67e8f14db71d288e11266ffdaf69cbf115f7bab14f3bc2f68d25e0e30'''.split())
PEM=re.compile(b'-----BEGIN (?:TRUSTED )?CERTIFICATE-----.*?-----END (?:TRUSTED )?CERTIFICATE-----',re.S)
def tlv(data,pos):
 start=pos;tag=data[pos];pos+=1;n=data[pos];pos+=1
 if n&128:
  size=n&127;assert 0<size<=4;n=int.from_bytes(data[pos:pos+size],'big');pos+=size
 assert pos+n<=len(data)
 return tag,start,pos,pos+n
def spki(der):
 _,_,body,_=tlv(der,0);_,_,pos,_=tlv(der,body)
 if der[pos]==160:pos=tlv(der,pos)[3]
 for _ in range(5):pos=tlv(der,pos)[3]
 _,start,_,end=tlv(der,pos)
 return hashlib.sha256(der[start:end]).hexdigest()
def pem_der(pem):
 return base64.b64decode(b''.join(pem.splitlines()[1:-1]))
def bad(pem):return spki(pem_der(pem)) in BLOCKED
def patch(backup=None):
 changed=[]
 def save(path,body):
  path=pathlib.Path(path);old=path.read_bytes()
  if old==body:return
  if backup:
   q=pathlib.Path(backup)/str(path).lstrip('/');q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(str(path),str(q))
  # Keep original inode/permissions so system-managed symlinks stay valid.
  path.write_bytes(body);changed.append(str(path))
 conf=pathlib.Path('/etc/ca-certificates.conf')
 if conf.exists():
  rows=conf.read_text().splitlines();new=[]
  for line in rows:
   p=pathlib.Path('/usr/share/ca-certificates')/line.lstrip('!')
   if line and not line.startswith(('#','!')) and p.is_file() and any(bad(x) for x in PEM.findall(p.read_bytes())):line='!'+line
   new.append(line)
  save(conf,('\n'.join(new)+'\n').encode())
  r=subprocess.run(['update-ca-certificates'],stdout=subprocess.PIPE,stderr=subprocess.PIPE);assert r.returncode==0,'CA regeneration failed'
 elif pathlib.Path('/etc/pki/ca-trust/source').exists():
  d=pathlib.Path('/etc/pki/ca-trust/source/blacklist');d.mkdir(exist_ok=True)
  for der in ssl.create_default_context().get_ca_certs(binary_form=True):
   fingerprint=spki(der)
   if fingerprint in BLOCKED:
    p=d/('emudhra-block-'+fingerprint+'.pem');body=ssl.DER_cert_to_PEM_cert(der).encode()
    if not p.exists():p.write_bytes(body);p.chmod(0o644);changed.append(str(p))
  r=subprocess.run(['update-ca-trust','extract'],stdout=subprocess.PIPE,stderr=subprocess.PIPE);assert r.returncode==0,'CA regeneration failed'
 paths=set()
 for base in ('/etc/ssl','/etc/pki/ca-trust/extracted','/usr/local/share/ca-certificates'):
  root=pathlib.Path(base)
  if root.exists():
   for p in root.rglob('*'):
    if p.is_file() and p.suffix in ('.crt','.pem'):paths.add(p.resolve())
 for name in ('certifi','pip._vendor.certifi'):
  try:paths.add(pathlib.Path(importlib.import_module(name).where()).resolve())
  except ImportError:pass
 for p in paths:
  try:
   body=p.read_bytes()
   if len(body)>2*1024*1024 or b'PRIVATE KEY' in body:continue
   matches=PEM.findall(body)
   if any(bad(x) for x in matches):save(p,PEM.sub(lambda m:b'' if bad(m.group()) else m.group(),body))
  except (OSError,ValueError,AssertionError):raise
 checks={}
 for name,path in [('system',None)]+[(n,str(p)) for n,p in enumerate(paths) if p.is_file() and p.stat().st_size>30000]:
  try:ctx=ssl.create_default_context(cafile=path) if path else ssl.create_default_context()
  except ssl.SSLError:continue
  remaining=sum(spki(der) in BLOCKED for der in ctx.get_ca_certs(binary_form=True));assert remaining==0,'Blocked root still trusted'
  if name=='system':checks={'trusted_roots':len(ctx.get_ca_certs()),'blocked_roots':remaining}
 assert checks.get('trusted_roots',0)>80
 return {'changed':changed,'system':checks}
if __name__=='__main__':print(json.dumps(patch(os.environ.get('TRUST_BACKUP'))))
