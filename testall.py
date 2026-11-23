#!/usr/bin/env python3
"""Run main.ts over all checks of a trial and compare with expected.json."""
import json, os, shutil, subprocess, sys, tempfile, time

ROOT = '/home/agentuser/makefun/mend-01'
KIT = '/home/agentuser/makefun/kit-mend/hidden-spec-cli-01-run-20261122-kit/practice'

def load(trial):
    checks = json.load(open(f'{KIT}/{trial}/input/env/checks.json'))['checks']
    exp = {c['id']: c for c in json.load(open(f'{KIT}/{trial}/reference/expected.json'))['checks']}
    return checks, exp

def run_check(c):
    d = tempfile.mkdtemp(prefix='mend-')
    try:
        for p, text in c['files'].items():
            fp = os.path.join(d, *p.split('/'))
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w', newline='') as f:
                f.write(text)
        env = dict(os.environ)
        env.pop('MAKEFUN_ENV_URL', None)
        r = subprocess.run(['node', os.path.join(ROOT, 'main.ts')] + c['argv'],
                           cwd=d, env=env, input=(c['stdin'] or ''), capture_output=True,
                           text=True, timeout=10)
        files = {}
        for dirpath, dirs, names in os.walk(d):
            dirs.sort()
            for n in sorted(names):
                fp = os.path.join(dirpath, n)
                rel = os.path.relpath(fp, d).replace(os.sep, '/')
                with open(fp, newline='') as f:
                    files[rel] = f.read()
        return r.returncode, r.stdout, files
    finally:
        shutil.rmtree(d)

def firstdiff(a, b):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return min(len(a), len(b))

def main(trial='trial-0'):
    checks, exp = load(trial)
    passed = 0
    fails = []
    for c in checks:
        e = exp[c['id']]
        try:
            exit_, out, files = run_check(c)
        except subprocess.TimeoutExpired:
            exit_, out, files = 124, '', {}
        why = []
        if exit_ != e['exit']:
            why.append(f'exit {exit_} != {e["exit"]}')
        if out != e['stdout']:
            i = firstdiff(out, e['stdout'])
            why.append(f'stdout differs @{i}: got {out[max(0,i-30):i+50]!r} want {e["stdout"][max(0,i-30):i+50]!r}')
        want = dict(e['files'])

        for p in sorted(set(want) | set(files)):
            if p not in want: why.append(f'extra file {p}')
            elif p not in files: why.append(f'missing file {p}')
            elif files[p] != want[p]:
                i = firstdiff(files[p], want[p])
                why.append(f'file {p} differs @{i}: got {files[p][max(0,i-30):i+50]!r} want {want[p][max(0,i-30):i+50]!r}')
        if why:
            fails.append((c['id'], why))
        else:
            passed += 1
    for cid, why in fails:
        print(f'FAIL {cid}: ' + ' | '.join(why))
    print(f'{passed}/{len(checks)} passed on {trial}')
    return 0 if not fails else 1

if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'trial-0'))
