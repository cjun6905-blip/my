"""Prepare private local configuration without contacting Discord or starting services."""
import pathlib,shutil,sys
root=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve()
if not (root/'snapshot-manifest.json').exists():raise SystemExit('Choose a Bot source directory')
private=root/'.runtime';private.mkdir(exist_ok=True)
if not (private/'config').exists():shutil.copytree(root/'config',private/'config')
(private/'data').mkdir(exist_ok=True)
(root.parents[1]/'.runtime/fleet').mkdir(parents=True,exist_ok=True)
for name in ['.env','.imagegen.env','.imagegen-openai.env','.speech.env']:
    dest=root/name
    if not dest.exists():
        shutil.copyfile(root/(name+'.example'),dest)
        dest.chmod(0o600)
print('Private configuration prepared. Fill credentials and identity bindings before starting.')
