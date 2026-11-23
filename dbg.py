#!/usr/bin/env python3
import json, os, shutil, subprocess, sys, tempfile
KIT = '/home/agentuser/makefun/kit-mend/hidden-spec-cli-01-run-20261122-kit/practice'

cid = sys.argv[1]
trial = sys.argv[2] if len(sys.argv) > 2 else 'trial-0'
checks = json.load(open(f'{KIT}/{trial}/input/env/checks.json'))['checks']
exp = {c['id']: c for c in json.load(open(f'{KIT}/{trial}/reference/expected.json'))['checks']}[cid]
c = {x['id']: x for x in checks}[cid]
print('ARGV', c['argv'])
for f, t in c['files'].items():
    if f.endswith(('.patch', '.diff', '.md')) and len(t) < 3000:
        print(f'--- FILE {f}:')
        for i, l in enumerate(t.split('\n')):
            print(f'{i+1:3}| {l!r}')
if c.get('stdin'):
    print('--- STDIN:')
    for i, l in enumerate(c['stdin'].split('\n')):
        print(f'{i+1:3}| {l!r}')
print('EXPECT exit', exp['exit'])
print('EXPECT stdout', repr(exp['stdout']))
d = tempfile.mkdtemp()
for f, t in c['files'].items():
    fp = os.path.join(d, *f.split('/'))
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, 'w', newline='').write(t)
r = subprocess.run(['node', '/home/agentuser/makefun/mend-01/main.ts'] + c['argv'], cwd=d, input=c['stdin'] or '', capture_output=True, text=True)
print('GOT exit', r.returncode, 'stdout', repr(r.stdout), 'stderr', r.stderr[-800:])
for f, want in exp['files'].items():
    if want is None:
        print(f'EXPECT delete {f}')
        continue
    fp = os.path.join(d, *f.split('/'))
    got = open(fp, newline='').read() if os.path.exists(fp) else None
    if got != want:
        print(f'--- DIFF {f}')
        import difflib
        if got is None:
            print('  MISSING')
        else:
            for line in difflib.unified_diff(got.split('\n'), want.split('\n'), 'got', 'want', lineterm='', n=2):
                print('  ' + line)
