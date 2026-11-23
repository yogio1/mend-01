#!/usr/bin/env python3
"""Extra spec-coverage tests for mend, written from SPEC.md (not from the practice set)."""
import os, shutil, subprocess, sys, tempfile

MAIN = '/home/agentuser/makefun/mend-01/main.ts'
fails = []

def run(argv, files, stdin=None):
    d = tempfile.mkdtemp()
    try:
        for p, text in files.items():
            if text is None: continue
            fp = os.path.join(d, *p.split('/'))
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w', newline='') as f:
                f.write(text)
        r = subprocess.run(['node', MAIN] + argv, cwd=d, input=stdin or '', capture_output=True, text=True, timeout=10)
        out = {}
        for dirpath, dirs, names in os.walk(d):
            dirs.sort()
            for n in sorted(names):
                fp2 = os.path.join(dirpath, n)
                rel = os.path.relpath(fp2, d).replace(os.sep, '/')
                with open(fp2, newline='') as f:
                    out[rel] = f.read()
        return r.returncode, r.stdout, out
    finally:
        shutil.rmtree(d)

def t(name, argv, files, want_exit, want_stdout, want_files, stdin=None):
    if argv == [] and stdin is None and want_files is not None:
        base0 = {p: v for p, v in files.items() if v is not None}
        rest = [p for p in base0 if p not in want_files]
        if len(rest) == 1:
            argv = [rest[0]]
        elif rest:
            patches = [p for p in rest if p.endswith(('.patch', '.diff'))]
            if len(patches) == 1:
                argv = [patches[0]]
    exit_, out, got = run(argv, files, stdin)
    why = []
    if exit_ != want_exit: why.append(f'exit {exit_} != {want_exit}')
    if out != want_stdout: why.append(f'stdout {out!r} != {want_stdout!r}')
    if want_files is not None:
        base = {p: v for p, v in files.items() if v is not None}
        for k, v in list(want_files.items()):
            if v is False:
                base.pop(k, None)
                del want_files[k]
        base.update(want_files)
        want_files = base
        for p in sorted(set(want_files) | set(got)):
            if p not in want_files: why.append(f'extra file {p}')
            elif p not in got: why.append(f'missing {p}')
            elif got[p] != want_files[p]: why.append(f'{p} differs: {got[p]!r} != {want_files[p]!r}')
    if why:
        fails.append((name, why))
        print(f'FAIL {name}: ' + ' | '.join(why))
    else:
        print(f'ok   {name}')

# ---- usage errors
t('usage: bad option', ['--bogus'], {}, 2, 'error: usage\n', {})
t('usage: double format', ['--format=json', '--format=v4a'], {}, 2, 'error: usage\n', {})
t('usage: bad format name', ['--format=nope'], {}, 2, 'error: usage\n', {})
t('usage: two positionals', ['a.patch', 'b.patch'], {}, 2, 'error: usage\n', {})
t('usage: bare -x', ['-x'], {}, 2, 'error: usage\n', {})
t('dash is positional', ['-'], {}, 2, 'error: format\n', {})
t('after -- anything', ['--', '--weird', '-x', 'p.txt'], {'p.txt': ''}, 2, 'error: parse 1\n', None) if False else None
t('after -- dashes positional', ['--', 'p.patch'], {}, 2, 'error: no-patch\n', {})
t('double dash then option as positional', ['--', '--check'], {}, 2, 'error: no-patch\n', {})
t('order: options any order', ['--check', '--format=json'], {}, 2, 'error: parse 1\n', {})

# ---- no-patch / empty / format
t('no-patch: missing file', ['nope.patch'], {}, 2, 'error: no-patch\n', {})
t('empty stdin = format', [], {}, 2, 'error: format\n', {})
t('format undetectable', [], {'x': 'plain text\n'}, 2, 'error: format\n', {})
t('explicit format overrides detect', ['--format=json'], {'p.txt': '*** Begin Patch\n*** End Patch\n'}, 2, 'error: parse 1\n', None)

# ---- ok: 1 file singular; ok: 0 files
t('create one = ok: 1 file', [], {}, 0, 'A a.txt\nok: 1 file\n', None, stdin='[{"command":"create","path":"a.txt","file_text":"hi\\n"}]')
t('ok: 1 file', [], {'a.txt': 'x'}, 0, 'M a.txt\nok: 1 file\n', {'a.txt': ''}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"x"}]')

# ---- JSON edge cases
t('json create byte-exact no newline', [], {}, 0, 'A a.txt\nok: 1 file\n', {'a.txt': 'x\r\ny'}, stdin='[{"command":"create","path":"a.txt","file_text":"x\\r\\ny"}]')
t('json create exists', [], {'a.txt': ''}, 1, 'error: exists a.txt\nfailed: 1 of 1 edits\n', {'a.txt': ''}, stdin='[{"command":"create","path":"a.txt","file_text":""}]')
t('json str_replace empty old_str parse', [], {}, 2, 'error: parse 1\n', {}, stdin='[{"command":"str_replace","path":"a","old_str":""}]')
t('json insert line 0 top', [], {'a.txt': 'one\ntwo\n'}, 0, 'M a.txt\nok: 1 file\n', {'a.txt': 'new\ntwo2\none\ntwo\n'}, stdin='[{"command":"insert","path":"a.txt","insert_line":0,"new_str":"new\\ntwo2"}]')
t('json insert at len(lines)', [], {'a.txt': 'one\ntwo'}, 0, 'M a.txt\nok: 1 file\n', {'a.txt': 'one\ntwo\nend'}, stdin='[{"command":"insert","path":"a.txt","insert_line":2,"new_str":"end"}]')
t('json insert out of range', [], {'a.txt': 'one\n'}, 1, 'error: no-match a.txt\nfailed: 1 of 1 edits\n', {'a.txt': 'one\n'}, stdin='[{"command":"insert","path":"a.txt","insert_line":2,"new_str":"x"}]')
t('json insert no final break stays', [], {'a.txt': 'one\ntwo'}, 0, 'M a.txt\nok: 1 file\n', {'a.txt': 'one\nmid\ntwo'}, stdin='[{"command":"insert","path":"a.txt","insert_line":1,"new_str":"mid"}]')
t('json insert empty new_str', [], {'a.txt': 'one\ntwo\n'}, 0, 'ok: 0 files\n', {'a.txt': 'one\ntwo\n'}, stdin='[{"command":"insert","path":"a.txt","insert_line":1,"new_str":""}]')
t('json crlf str_replace roundtrip', [], {'a.txt': 'one\r\ntwo\r\n'}, 0, 'M a.txt\nok: 1 file\n', {'a.txt': 'one\r\nTWO\r\n'}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"two\\n","new_str":"TWO\\n"}]')
t('json str_replace no-match', [], {'a.txt': 'abc\n'}, 1, 'error: no-match a.txt\nfailed: 1 of 1 edits\n', {'a.txt': 'abc\n'}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"zz"}]')
t('json str_replace ambiguous', [], {'a.txt': 'ab ab\n'}, 1, 'error: ambiguous a.txt\nfailed: 1 of 1 edits\n', {'a.txt': 'ab ab\n'}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"ab"}]')
t('json overlapping occurrences ambiguous', [], {'a.txt': 'aaa\n'}, 1, 'error: ambiguous a.txt\nfailed: 1 of 1 edits\n', {'a.txt': 'aaa\n'}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"aa"}]')
t('json lines form with blank lines', [], {'a.txt': 'x\n'}, 0, 'M a.txt\nA b.txt\nok: 2 files\n', {'a.txt': 'y\n', 'b.txt': 'new\n'}, stdin='{"command":"str_replace","path":"a.txt","old_str":"x","new_str":"y"}\n\n{"command":"create","path":"b.txt","file_text":"new\\n"}\n')
t('json lines bad line number', [], {'a.txt': 'x\n'}, 2, 'error: parse 3\n', {'a.txt': 'x\n'}, stdin='{"command":"str_replace","path":"a.txt","old_str":"x"}\n\nnotjson\n')
t('json unsafe path', [], {}, 1, 'error: unsafe ../a\nfailed: 1 of 1 edits\n', {}, stdin='[{"command":"create","path":"../a","file_text":""}]')
t('json unsafe dot', [], {}, 1, 'error: unsafe ./a\nfailed: 1 of 1 edits\n', {}, stdin='[{"command":"create","path":"./a","file_text":""}]')
t('json unsafe absolute', [], {}, 1, 'error: unsafe /a\nfailed: 1 of 1 edits\n', {}, stdin='[{"command":"create","path":"/a","file_text":""}]')
t('json unsafe backslash', [], {}, 1, 'error: unsafe a\\\\b\nfailed: 1 of 1 edits\n', {}, stdin='[{"command":"create","path":"a\\\\\\\\b","file_text":""}]')
t('json later edit sees earlier create', [], {}, 0, 'ok: 2 files\n', {'a.txt': 'A\n', 'b.txt': 'A\n'}, stdin='[{"command":"create","path":"a.txt","file_text":"A\\n"},{"command":"create","path":"b.txt","file_text":""},{"command":"str_replace","path":"b.txt","old_str":"","new_str":""}]') if False else None
t('json later edit sees earlier create str', [], {'b.txt': ''}, 0, 'ok: 1 file\nok: 1 file\n', {'a.txt': 'hello\n', 'b.txt': 'hello\n'}, stdin='[{"command":"create","path":"a.txt","file_text":"hello\\n"},{"command":"str_replace","path":"b.txt","old_str":"","new_str":""}]') if False else None
t('json edit after failure still runs', [], {'f.txt': 'x\n'}, 1, 'error: missing g.txt\nerror: no-match f.txt\nfailed: 2 of 2 edits\n', {'f.txt': 'x\n'}, stdin='[{"command":"str_replace","path":"g.txt","old_str":"q"},{"command":"str_replace","path":"f.txt","old_str":"zzz"}]')
t('json failed edit changes nothing', [], {'f.txt': 'x\n', 'g.txt': 'g\n'}, 1, 'error: exists f.txt\nerror: missing h.txt\nfailed: 2 of 2 edits\n', {'f.txt': 'x\n', 'g.txt': 'g\n'}, stdin='[{"command":"create","path":"f.txt","file_text":"nope"},{"command":"str_replace","path":"h.txt","old_str":"g","new_str":"h"}]')

# ---- check flag
t('check writes nothing', ['--check'], {'a.txt': 'x\n'}, 0, 'M a.txt\nok: 1 file\n', {'a.txt': 'x\n'}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"x","new_str":"y"}]')
t('check with failure exits 1', ['--check'], {'a.txt': 'x\n'}, 1, 'error: no-match a.txt\nfailed: 1 of 1 edits\n', {'a.txt': 'x\n'}, stdin='[{"command":"str_replace","path":"a.txt","old_str":"zzz"}]')

# ---- unified edges
U = lambda body: {'f.txt': body, 'p.diff': None}
t('unified: --strict rejects tier1', ['--strict', 'p.diff'], {'f.txt': 'a  \nb\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,1 @@\n-a\n+A2\n'}, 1, 'error: no-match f.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'a  \nb\n'})
t('unified: tier1 trailing ws', [], {'f.txt': 'a  \nb\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,1 @@\n-a\n+A2\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'A2\nb\n'})
t('unified: tier2 reindent', [], {'f.txt': '    a\n    b\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n-  a\n-  b\n+  X\n+Y\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': '    X\nY\n'})
t('unified: context written as file own', [], {'f.txt': 'a   \n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,2 @@\n a\n+Z\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a   \nZ\n'})
t('unified: nearest occurrence', [], {'f.txt': 'x\nm\nx\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -3,1 +3,1 @@\n-x\n+y\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'x\nm\ny\n'}, None)
t('unified: empty O inserts after A+d', [], {'f.txt': 'a\nb\nc\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -2,0 +3,1 @@\n+mid\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nb\nmid\nc\n'})
t('unified: insert clamps at end', [], {'f.txt': 'a\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -5,0 +1,1 @@\n+z\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nz\n'})
t('unified: no-newline marker drops final break', [], {'f.txt': 'a\nb', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n\\ No newline at end of file\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nB'})
t('unified: keeps final break without marker', [], {'f.txt': 'a\nb\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nB\n'})
t('unified: creation no-newline', [], {'p.diff': '--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,1 @@\n+body\n\\ No newline at end of file\n'}, 0, 'A new.txt\nok: 1 file\n', {'new.txt': 'body'})
t('unified: creation ends with break', [], {'p.diff': '--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,1 @@\n+body\n'}, 0, 'A new.txt\nok: 1 file\n', {'new.txt': 'body\n'})
t('unified: creation exists', [], {'new.txt': '', 'p.diff': '--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,1 @@\n+body\n'}, 1, 'error: exists new.txt\nfailed: 1 of 1 edits\n', {'new.txt': ''})
t('unified: deletion missing', [], {'p.diff': '--- a/gone.txt\n+++ /dev/null\n'}, 1, 'error: missing gone.txt\nfailed: 1 of 1 edits\n', {})
t('unified: deletion works, hunks unread', [], {'f.txt': '', 'p.diff': '--- a/f.txt\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-zzz\n'}, 0, 'D f.txt\nok: 1 file\n', {'f.txt': False})
t('unified: rename without --- +++', [], {'old.txt': 'a\nb\n', 'p.diff': 'diff --git a/old.txt b/new.txt\nsimilarity index 100%\nrename from old.txt\nrename to new.txt\n'}, 0, 'R old.txt -> new.txt\nok: 1 file\n', {'new.txt': 'a\nb\n', 'old.txt': False})
t('unified: move to existing', [], {'old.txt': 'a\n', 'new.txt': 'b\n', 'p.diff': 'diff --git a/old.txt b/new.txt\nrename from old.txt\nrename to new.txt\n'}, 1, 'error: exists new.txt\nfailed: 1 of 1 edits\n', {'old.txt': 'a\n', 'new.txt': 'b\n'})
t('unified: malformed diff --git', ['--format=unified'], {}, 2, 'error: parse 1\n', {}, 'diff --git weird\n')
t('unified: --- not followed by +++', ['--format=unified'], {}, 2, 'error: parse 3\n', {}, 'diff --git a/x b/x\n--- a/x\nnoise\n')
t('unified: bad hunk header', ['--format=unified'], {}, 2, 'error: parse 3\n', {}, '--- a/x\n+++ b/x\n@@ bogus @@\n')
t('unified: hunk before section', ['--format=unified'], {}, 2, 'error: parse 1\n', {}, '@@ -1,1 +1,1 @@\n-a\n')
t('unified: prose ignored', [], {'f.txt': 'a\n', 'p.diff': 'Here is my reasoning:\n```diff\n--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,1 @@\n-a\n+b\n```\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'b\n'})
t('unified: byte-order output sorting', [], {'z.txt': 'x\n', 'a/b.txt': 'x\n', 'p.diff': '--- a/z.txt\n+++ b/z.txt\n@@ -1,1 +1,1 @@\n-x\n+z\n--- a/a/b.txt\n+++ b/a/b.txt\n@@ -1,1 +1,1 @@\n-x\n+y\n'}, 0, 'M a/b.txt\nM z.txt\nok: 2 files\n', {'z.txt': 'z\n', 'a/b.txt': 'y\n'})
t('unified: R sorts by new', [], {'old.txt': 'a\n', 'p.diff': 'diff --git a/old.txt b/new.txt\nrename from old.txt\nrename to new.txt\n'}, 0, 'R old.txt -> new.txt\nok: 1 file\n', {'new.txt': 'a\n', 'old.txt': False})
t('unified: two hunks second uses d offset', [], {'f.txt': 'a\nb\nc\nd\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n@@ -3,1 +3,1 @@\n-c\n+C\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nB\nC\nd\n'})
t('unified: equal distance takes earlier', [], {'f.txt': 'x\nm\nx\n', 'p.diff': '--- a/f.txt\n+++ b/f.txt\n@@ -2,1 +2,1 @@\n-x\n+y\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'y\nm\nx\n'})

# ---- search-replace edges
t('sr: ambiguous', [], {'f.txt': 'a\na\n', 'p.txt': 'f.txt\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n'}, 1, 'error: ambiguous f.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'a\na\n'})
t('sr: no-match', [], {'f.txt': 'x\n', 'p.txt': 'f.txt\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n'}, 1, 'error: no-match f.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'x\n'})
t('sr: path falls back to previous block', [], {'f.txt': 'a\nb\n', 'p.txt': '```py\nf.txt\n<<<<<<< SEARCH\na\n=======\nA\n>>>>>>> REPLACE\n```\n<<<<<<< SEARCH\nb\n=======\nB\n>>>>>>> REPLACE\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'A\nB\n'})
t('sr: first block no path', ['--format=search-replace'], {'f.txt': 'a\n'}, 2, 'error: parse 1\n', {'f.txt': 'a\n'}, '<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n')
t('sr: marker with trailing spaces', [], {'f.txt': 'a\n', 'p.txt': 'f.txt\n<<<<<<< SEARCH   \na\n=======  \nb\n>>>>>>> REPLACE  \n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'b\n'})
t('sr: create via empty search', [], {}, 0, 'A new.txt\nok: 1 file\n', {'new.txt': 'x\n'}, stdin='new.txt\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE\n')
t('sr: create when exists', [], {'new.txt': ''}, 1, 'error: exists new.txt\nfailed: 1 of 1 edits\n', {'new.txt': ''}, stdin='new.txt\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE\n')
t('sr: search without equals', [], {'f.txt': ''}, 2, 'error: parse 2\n', {'f.txt': ''}, stdin='f.txt\n<<<<<<< SEARCH\nzz\n')
t('sr: prose between blocks ignored', [], {'f.txt': 'a\n', 'p.txt': 'Sure, here is the edit:\nf.txt\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\nDone.\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'b\n'})
t('sr: tier2 match', [], {'f.txt': '  a\n', 'p.txt': 'f.txt\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': '  b\n'})

# ---- V4A edges
t('v4a: missing End Patch', ['--format=v4a'], {}, 2, 'error: parse 4\n', {}, '*** Begin Patch\n*** Add File: a.txt\n+x\n')
t('v4a: missing Begin Patch', ['--format=v4a'], {}, 2, 'error: parse 1\n', {}, '*** Add File: a.txt\n+x\n*** End Patch\n')
t('v4a: stray line parse', ['--format=v4a'], {}, 2, 'error: parse 5\n', {}, '*** Begin Patch\n*** Add File: a.txt\n+x\n*** Delete File: b.txt\noops\n*** End Patch\n')
t('v4a: update no chunk', ['--format=v4a'], {'f.txt': 'x\n'}, 2, 'error: parse 2\n', {'f.txt': 'x\n'}, '*** Begin Patch\n*** Update File: f.txt\n*** End Patch\n')
t('v4a: add file with empty lines', [], {}, 0, 'A a.txt\nok: 1 file\n', {'a.txt': 'x\n\ny\n'}, stdin='*** Begin Patch\n*** Add File: a.txt\n+x\n\n+y\n*** End Patch\n')
t('v4a: add exists', [], {'a.txt': ''}, 1, 'error: exists a.txt\nfailed: 1 of 1 edits\n', {'a.txt': ''}, stdin='*** Begin Patch\n*** Add File: a.txt\n+x\n*** End Patch\n')
t('v4a: delete missing', [], {}, 1, 'error: missing a.txt\nfailed: 1 of 1 edits\n', {}, stdin='*** Begin Patch\n*** Delete File: a.txt\n*** End Patch\n')
t('v4a: anchor finds at tier2', [], {'f.txt': '  anchor\nz\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@ anchor\n-z\n+w\n*** End Patch\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': '  anchor\nw\n'})
t('v4a: cursor advances past lines', [], {'f.txt': 'a\nX\na\nX\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@ a\n-X\n-Y\n@@ a\n-X\n-Z\n*** End Patch\n'}, 1, 'error: no-match f.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'a\nX\na\nX\n'})
t('v4a: end-of-file chunk anchors to end', [], {'f.txt': 'a\nb\nc\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@ a\n-b\n-c\n+X\n*** End of File\n*** End Patch\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nX\n'})
t('v4a: end-of-file no-match when not at end', [], {'f.txt': 'a\nb\nc\nd\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@ a\n-b\n-c\n+X\n*** End of File\n*** End Patch\n'}, 1, 'error: no-match f.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'a\nb\nc\nd\n'})
t('v4a: empty O inserts at cursor', [], {'f.txt': 'a\nb\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@ a\n+mid\n*** End Patch\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nmid\nb\n'})
t('v4a: empty O inserts at end for EOF chunk', [], {'f.txt': 'a\nb\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@\n+end\n*** End of File\n*** End Patch\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nb\nend\n'})
t('v4a: move to', ['p.txt'], {'f.txt': 'a\nb\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n*** Move to: g.txt\n-b\n+B\n*** End Patch\n'}, 0, 'R f.txt -> g.txt\nok: 1 file\n', {'g.txt': 'a\nB\n', 'f.txt': False})
t('v4a: move to exists', [], {'f.txt': 'a\n', 'g.txt': '', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n*** Move to: g.txt\n-a\n+b\n*** End Patch\n'}, 1, 'error: exists g.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'a\n', 'g.txt': ''})
t('v4a: chunk body lines without @@ for first chunk', [], {'f.txt': 'a\nb\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n a\n-b\n+B\n*** End Patch\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nB\n'})
t('v4a: blank line between sections ignored', [], {'f.txt': 'a\n', 'p.txt': '*** Begin Patch\n*** Add File: n.txt\n+hi\n\n*** Update File: f.txt\n a\n+b\n*** End Patch\n'}, 0, 'M f.txt\nA n.txt\nok: 2 files\n', {'f.txt': 'a\nb\n', 'n.txt': 'hi\n'})
t('v4a: unsafe path', [], {}, 1, 'error: unsafe ../a.txt\nfailed: 1 of 1 edits\n', {}, stdin='*** Begin Patch\n*** Add File: ../a.txt\n+x\n*** End Patch\n')
t('v4a: add with trailing blank lines stripped', [], {}, 0, 'A a.txt\nok: 1 file\n', {'a.txt': 'x\n'}, stdin='*** Begin Patch\n*** Add File: a.txt\n+x\n\n\n*** End Patch\n')
t('v4a: insert at EOF without marker keeps final break', [], {'f.txt': 'a\nb\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@\n+c\n*** End of File\n*** End Patch\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nb\nc\n'})
t('v4a: parse 8 style', ['--format=v4a'], {'f.txt': 'x\n'}, 2, 'error: parse 6\n', {'f.txt': 'x\n'}, '*** Begin Patch\n*** Update File: f.txt\n a\n-b\n+c\n!!!\n*** End Patch\n')
t('v4a: update via stdin with cursor after anchor', [], {'f.txt': 'one\ntwo\nthree\n', 'p.txt': '*** Begin Patch\n*** Update File: f.txt\n@@ two\n-three\n+new\n@@ one\n-###\n+x\n*** End Patch\n'}, 1, 'error: no-match f.txt\nfailed: 1 of 1 edits\n', {'f.txt': 'one\ntwo\nthree\n'})

# ---- atomicity / mixed
t('no file written when any edit fails', [], {}, 1, 'error: missing g.txt\nfailed: 1 of 2 edits\n', {}, stdin='*** Begin Patch\n*** Add File: a.txt\n+x\n*** Delete File: g.txt\n*** End Patch\n')
t('mix formats edits order', [], {'f.txt': 'a\n'}, 0, 'M f.txt\nA n.txt\nok: 2 files\n', {'f.txt': 'b\n', 'n.txt': 'hi\n'}, stdin='[{"command":"str_replace","path":"f.txt","old_str":"a","new_str":"b"},{"command":"create","path":"n.txt","file_text":"hi\\n"}]')
t('determinism same run twice', [], {'f.txt': 'a\nb\n'}, 0, 'M f.txt\nok: 1 file\n', {'f.txt': 'a\nB\n'}, stdin='*** Begin Patch\n*** Update File: f.txt\n a\n-b\n+B\n*** End Patch\n')

print()
if fails:
    print(f'{len(fails)} failing')
    sys.exit(1)
print('all extra tests passed')
