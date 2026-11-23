// main.ts is mend, the CLI SPEC.md specifies. Node 22, the standard library alone; run it as
// `node main.ts [options] [PATCH]`.
//
// In a trial the grader runs `node /bot/main.ts` with MAKEFUN_ENV_URL set, and then this file hands over to runner.ts
// (the last lines below): keep that hand-over and runner.ts as they are, and write the CLI.

import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync, writeSync } from 'node:fs';
import { dirname } from 'node:path';

const FORMATS = ['auto', 'unified', 'search-replace', 'v4a', 'json'];

class Exit2 {
  readonly line: string;
  constructor(line: string) {
    this.line = line;
  }
}
class Fail {
  readonly code: string;
  readonly path: string;
  constructor(code: string, path: string) {
    this.code = code;
    this.path = path;
  }
}

const blank = (s: string): boolean => s.trim() === '';
const rtrimWT = (s: string): string => s.replace(/[ \t]+$/, '');
const trimWT = (s: string): string => rtrimWT(s.replace(/^[ \t]+/, ''));
const leadWT = (s: string): string => (/^[ \t]*/.exec(s) as RegExpExecArray)[0];

function patchLines(text: string): string[] {
  if (text === '') return [];
  const lines = text.split('\n');
  if (text.endsWith('\n')) lines.pop();
  return lines.map((l) => (l.endsWith('\r') ? l.slice(0, -1) : l));
}

function safe(p: string): boolean {
  return p !== '' && !p.startsWith('/') && !p.includes('\\') && p.split('/').every((s) => s !== '' && s !== '.' && s !== '..');
}

/** A file's text as its line break, its lines and whether it ends with a line break (SPEC.md section 3). */
interface FileText {
  br: string;
  lines: string[];
  finalBreak: boolean;
}
function fileText(t: string): FileText {
  if (t === '') return { br: '\n', lines: [], finalBreak: false };
  const nl = t.indexOf('\n');
  const br: string = nl > 0 && t[nl - 1] === '\r' ? '\r\n' : '\n';
  const lines = t.split(br);
  const finalBreak = t.endsWith(br);
  if (finalBreak) lines.pop();
  return { br, lines, finalBreak };
}
function fileJoin(f: FileText): string {
  return f.lines.length === 0 ? '' : f.lines.join(f.br) + (f.finalBreak ? f.br : '');
}

/** The tree as the edits leave it: changed paths in `now` (null: deleted), the rest read from disk. */
class Tree {
  private readonly orig = new Map<string, string | null>();
  readonly now = new Map<string, string | null>();
  /** Move edits that succeeded: new path -> old path. */
  readonly moves = new Map<string, string>();
  original(p: string): string | null {
    if (!this.orig.has(p)) {
      let v: string | null = null;
      try {
        if (statSync(p).isFile()) v = readFileSync(p, 'utf8');
      } catch {
        v = null;
      }
      this.orig.set(p, v);
    }
    return this.orig.get(p)!;
  }
  get(p: string): string | null {
    return this.now.has(p) ? this.now.get(p)! : this.original(p);
  }
}

type Edit = (tree: Tree) => void;

// ---------------------------------------------------------------- section 5: matching lines

function lineEq(a: string, b: string, tier: number): boolean {
  if (tier === 0) return a === b;
  if (tier === 1) return rtrimWT(a) === rtrimWT(b);
  return trimWT(a) === trimWT(b);
}

/** Every 0-based position where O matches the lines at `tier`; occurrences may overlap. */
function occurrences(lines: string[], O: string[], tier: number): number[] {
  const out: number[] = [];
  for (let i = 0; i + O.length <= lines.length; i += 1) {
    let ok = true;
    for (let j = 0; j < O.length; j += 1) {
      if (!lineEq(lines[i + j], O[j], tier)) {
        ok = false;
        break;
      }
    }
    if (ok) out.push(i);
  }
  return out;
}

/** The first tier (0, or with --strict only 0) at which O occurs, with all its occurrences. */
function findAtTier(lines: string[], O: string[], strict: boolean): { tier: number; occs: number[] } | null {
  for (const tier of strict ? [0] : [0, 1, 2]) {
    const occs = occurrences(lines, O, tier);
    if (occs.length > 0) return { tier, occs };
  }
  return null;
}

/** A body entry of a unified hunk or a V4A chunk. */
interface Entry {
  k: ' ' | '-' | '+' | '\\';
  text: string;
}

/** O and N from a hunk's or chunk's body: O is context and - lines, N context and + lines, in body order. */
function buildON(entries: Entry[]): { O: string[]; N: { text: string; oIdx: number }[] } {
  const O: string[] = [];
  const N: { text: string; oIdx: number }[] = [];
  for (const e of entries) {
    if (e.k === ' ') {
      N.push({ text: e.text, oIdx: O.length });
      O.push(e.text);
    } else if (e.k === '-') {
      O.push(e.text);
    } else if (e.k === '+') {
      N.push({ text: e.text, oIdx: -1 });
    }
  }
  return { O, N };
}

/** Whether a `\` line follows the body's last context or `+` line (SPEC.md section 6). */
function noNewlineMarker(entries: Entry[]): boolean {
  let last = -1;
  for (let i = 0; i < entries.length; i += 1) if (entries[i].k === ' ' || entries[i].k === '+') last = i;
  return last >= 0 && last + 1 < entries.length && entries[last + 1].k === '\\';
}

/** The lines N becomes at `tier`: context lines as the file's own, others re-indented at tier 2. */
function segment(lines: string[], pos: number, O: string[], N: { text: string; oIdx: number }[], tier: number): string[] {
  const P = O.length > 0 ? leadWT(O[0]) : '';
  const F = O.length > 0 ? leadWT(lines[pos]) : '';
  const out: string[] = [];
  for (const n of N) {
    if (n.oIdx >= 0) {
      out.push(lines[pos + n.oIdx]);
    } else if (tier === 2 && O.length > 0 && n.text.trim() !== '' && n.text.startsWith(P)) {
      out.push(F + n.text.slice(P.length));
    } else {
      out.push(n.text);
    }
  }
  return out;
}

// ---------------------------------------------------------------- section 6: unified diffs

interface UHunk {
  a: number;
  entries: Entry[];
}
interface USec {
  ddOld?: string | null;
  ddNew?: string | null;
  hadDD: boolean;
  renameFrom?: string;
  renameTo?: string;
  creation: boolean;
  deletion: boolean;
  diffOld?: string;
  diffNew?: string;
  hunks: UHunk[];
}

/** The path of a `--- ` or `+++ ` line: after the four characters, to the first tab, spaces removed. */
function ddPath(line: string): string | null {
  const rest = line.slice(4);
  const tab = rest.indexOf('\t');
  const raw = (tab >= 0 ? rest.slice(0, tab) : rest).trim();
  if (raw === '/dev/null') return null;
  return raw.startsWith('a/') || raw.startsWith('b/') ? raw.slice(2) : raw;
}

/** The two paths of a `diff --git a/<X> b/<Y>` line, or null when it is not of that form. */
function diffGitPaths(line: string): [string, string] | null {
  const rest = line.slice('diff --git '.length);
  if (!rest.startsWith('a/')) return null;
  const bi = rest.indexOf(' b/');
  if (bi < 0) return null;
  const x = rest.slice(2, bi);
  let y = rest.slice(bi + 3);
  if (y.startsWith('b/')) y = y.slice(2);
  if (x === '' || y === '') return null;
  return [x, y];
}

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@(?:[ ].*)?$/;

function parseUnified(lines: string[]): USec[] {
  const sections: USec[] = [];
  let cur: USec | null = null;
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith('diff --git ')) {
      const paths = diffGitPaths(l);
      if (paths === null) throw new Exit2(`error: parse ${i + 1}`);
      cur = { hadDD: false, creation: false, deletion: false, diffOld: paths[0], diffNew: paths[1], hunks: [] };
      sections.push(cur);
      i += 1;
      continue;
    }
    if (l.startsWith('--- ') && i + 1 < lines.length && lines[i + 1].startsWith('+++ ')) {
      const oldP = ddPath(l);
      const newP = ddPath(lines[i + 1]);
      if (cur === null || cur.hunks.length > 0 || cur.hadDD) {
        cur = { hadDD: true, ddOld: oldP, ddNew: newP, creation: false, deletion: false, hunks: [] };
        sections.push(cur);
      } else {
        cur.ddOld = oldP;
        cur.ddNew = newP;
        cur.hadDD = true;
      }
      i += 2;
      continue;
    }
    if (l.startsWith('@@')) {
      if (cur === null) throw new Exit2(`error: parse ${i + 1}`);
      const m = HUNK_RE.exec(l);
      if (m === null) throw new Exit2(`error: parse ${i + 1}`);
      const entries: Entry[] = [];
      i += 1;
      while (i < lines.length) {
        const b = lines[i];
        if (b.startsWith('diff --git ')) break;
        if (b.startsWith('--- ') && i + 1 < lines.length && lines[i + 1].startsWith('+++ ')) break;
        if (b === '') {
          entries.push({ k: ' ', text: '' });
          i += 1;
          continue;
        }
        const c = b[0];
        if (c === ' ' || c === '-' || c === '+' || c === '\\') {
          entries.push({ k: c as Entry['k'], text: b.slice(1) });
          i += 1;
          continue;
        }
        break;
      }
      while (entries.length > 0 && entries[entries.length - 1].k === ' ' && entries[entries.length - 1].text === '') entries.pop();
      cur.hunks.push({ a: parseInt(m[1], 10), entries });
      continue;
    }
    if (cur !== null && cur.hunks.length === 0) {
      if (l.startsWith('--- ')) throw new Exit2(`error: parse ${i + 2}`);
      if (l.startsWith('rename from ')) cur.renameFrom = l.slice(12).trim();
      else if (l.startsWith('rename to ')) cur.renameTo = l.slice(10).trim();
      else if (l.startsWith('new file mode')) cur.creation = true;
      else if (l.startsWith('deleted file mode')) cur.deletion = true;
    }
    i += 1;
  }
  return sections;
}

/** The hunks of one section applied in order, each to the result of the ones before it. */
function applyHunks(ft: FileText, hunks: UHunk[], strict: boolean, errPath: string): void {
  let d = 0;
  for (const h of hunks) {
    const { O, N } = buildON(h.entries);
    if (O.length > 0) {
      const m = findAtTier(ft.lines, O, strict);
      if (m === null) throw new Fail('no-match', errPath);
      const target = h.a - 1 + d;
      let pos = m.occs[0];
      let best = Math.abs(pos - target);
      for (const o of m.occs) {
        const dist = Math.abs(o - target);
        if (dist < best) {
          best = dist;
          pos = o;
        }
      }
      const seg = segment(ft.lines, pos, O, N, m.tier);
      const atEnd = pos + O.length === ft.lines.length;
      ft.lines.splice(pos, O.length, ...seg);
      if (atEnd) ft.finalBreak = !noNewlineMarker(h.entries);
      d += N.length - O.length;
    } else {
      const at = Math.max(0, Math.min(h.a + d, ft.lines.length));
      const atEnd = at === ft.lines.length;
      ft.lines.splice(at, 0, ...N.map((n) => n.text));
      if (atEnd) ft.finalBreak = !noNewlineMarker(h.entries);
      d += N.length;
    }
  }
}

function checkSafe(p: string): void {
  if (!safe(p)) throw new Fail('unsafe', p);
}

function applyUnified(sec: USec, tree: Tree, strict: boolean): void {
  const oldP = sec.hadDD ? sec.ddOld : sec.renameFrom ?? sec.diffOld;
  const newP = sec.hadDD ? sec.ddNew : sec.renameTo ?? sec.diffNew;
  const named = (v: string | null | undefined): v is string => v !== undefined && v !== null;
  if (sec.creation || (!named(oldP) && named(newP))) {
    if (!named(newP)) return;
    checkSafe(newP);
    if (tree.get(newP) !== null) throw new Fail('exists', newP);
    const flat: Entry[] = [];
    for (const h of sec.hunks) for (const e of h.entries) flat.push(e);
    const plus = flat.filter((e) => e.k === '+').map((e) => e.text);
    let lastPlus = -1;
    for (let i = 0; i < flat.length; i += 1) if (flat[i].k === '+') lastPlus = i;
    const marker = lastPlus >= 0 && lastPlus + 1 < flat.length && flat[lastPlus + 1].k === '\\';
    tree.now.set(newP, plus.length === 0 ? '' : plus.join('\n') + (marker ? '' : '\n'));
    return;
  }
  if (sec.deletion || (!named(newP) && named(oldP))) {
    if (!named(oldP)) return;
    checkSafe(oldP);
    if (tree.get(oldP) === null) throw new Fail('missing', oldP);
    tree.now.set(oldP, null);
    return;
  }
  if (named(oldP) && named(newP) && oldP !== newP) {
    checkSafe(oldP);
    checkSafe(newP);
    if (tree.get(oldP) === null) throw new Fail('missing', oldP);
    if (tree.get(newP) !== null) throw new Fail('exists', newP);
    const ft = fileText(tree.get(oldP)!);
    applyHunks(ft, sec.hunks, strict, oldP);
    tree.now.set(newP, fileJoin(ft));
    tree.now.set(oldP, null);
    tree.moves.set(newP, oldP);
    return;
  }
  const path = named(oldP) ? oldP : (newP as string);
  checkSafe(path);
  if (tree.get(path) === null) throw new Fail('missing', path);
  const ft = fileText(tree.get(path)!);
  applyHunks(ft, sec.hunks, strict, path);
  tree.now.set(path, fileJoin(ft));
}

function unifiedEdits(lines: string[], strict: boolean): Edit[] {
  const secs = parseUnified(lines);
  return secs.map((sec) => (tree) => applyUnified(sec, tree, strict));
}

// ---------------------------------------------------------------- section 7: SEARCH/REPLACE blocks

interface SRBlock {
  path: string;
  old: string[];
  new: string[];
}

function parseSearchReplace(lines: string[]): SRBlock[] {
  const blocks: SRBlock[] = [];
  let i = 0;
  let lastReplace = -1;
  while (i < lines.length) {
    if (lines[i].trimEnd() !== '<<<<<<< SEARCH') {
      i += 1;
      continue;
    }
    const at = i;
    let path: string | null = null;
    for (let j = i - 1; j > lastReplace; j -= 1) {
      const l = lines[j];
      if (blank(l)) continue;
      if (l.trim().startsWith('```')) continue;
      path = l.trim();
      break;
    }
    if (path === null && blocks.length > 0) path = blocks[blocks.length - 1].path;
    if (path === null) throw new Exit2(`error: parse ${at + 1}`);
    let eq = -1;
    for (let j = i + 1; j < lines.length; j += 1) {
      if (lines[j].trimEnd() === '=======') {
        eq = j;
        break;
      }
      if (lines[j].trimEnd() === '<<<<<<< SEARCH') throw new Exit2(`error: parse ${at + 1}`);
    }
    if (eq < 0) throw new Exit2(`error: parse ${at + 1}`);
    let rep = -1;
    for (let j = eq + 1; j < lines.length; j += 1) {
      if (lines[j].trimEnd() === '>>>>>>> REPLACE') {
        rep = j;
        break;
      }
    }
    if (rep < 0) throw new Exit2(`error: parse ${at + 1}`);
    blocks.push({ path, old: lines.slice(i + 1, eq), new: lines.slice(eq + 1, rep) });
    lastReplace = rep;
    i = rep + 1;
  }
  if (blocks.length === 0) throw new Exit2('error: parse 1');
  return blocks;
}

function srEdits(lines: string[], strict: boolean): Edit[] {
  return parseSearchReplace(lines).map((b) => (tree) => {
    checkSafe(b.path);
    if (b.old.length === 0) {
      if (tree.get(b.path) !== null) throw new Fail('exists', b.path);
      tree.now.set(b.path, b.new.length === 0 ? '' : `${b.new.join('\n')}\n`);
      return;
    }
    const t = tree.get(b.path);
    if (t === null) throw new Fail('missing', b.path);
    const ft = fileText(t);
    const m = findAtTier(ft.lines, b.old, strict);
    if (m === null) throw new Fail('no-match', b.path);
    if (m.occs.length > 1) throw new Fail('ambiguous', b.path);
    const pos = m.occs[0];
    const seg = segment(ft.lines, pos, b.old, b.new.map((x) => ({ text: x, oIdx: -1 })), m.tier);
    ft.lines.splice(pos, b.old.length, ...seg);
    tree.now.set(b.path, fileJoin(ft));
  });
}

// ---------------------------------------------------------------- section 8: V4A patches

interface V4Chunk {
  anchor: string | null;
  eof: boolean;
  entries: Entry[];
}
interface V4Sec {
  kind: 'add' | 'del' | 'upd';
  path: string;
  moveTo: string | null;
  chunks: V4Chunk[];
  addLines: string[];
  line: number;
}

function parseV4A(lines: string[]): V4Sec[] {
  const first = lines.findIndex((l) => !blank(l));
  if (first < 0) throw new Exit2('error: parse 1');
  if (lines[first].trim() !== '*** Begin Patch') throw new Exit2(`error: parse ${first + 1}`);
  let last = -1;
  for (let j = lines.length - 1; j >= 0; j -= 1) {
    if (!blank(lines[j])) {
      last = j;
      break;
    }
  }
  if (lines[last].trim() !== '*** End Patch') throw new Exit2(`error: parse ${lines.length + 1}`);

  const secs: V4Sec[] = [];
  let cur: V4Sec | null = null;
  let bodySeen = false;

  const openChunk = (): void => {
    if (cur!.chunks.length === 0 || cur!.chunks[cur!.chunks.length - 1].eof) {
      cur!.chunks.push({ anchor: null, eof: false, entries: [] });
    }
  };
  const stripTrailingEmpty = (): void => {
    if (cur === null) return;
    if (cur.kind === 'add') {
      while (cur.addLines.length > 0 && cur.addLines[cur.addLines.length - 1] === '') cur.addLines.pop();
    } else if (cur.kind === 'upd' && cur.chunks.length > 0) {
      const es = cur.chunks[cur.chunks.length - 1].entries;
      while (es.length > 0 && es[es.length - 1].k === ' ' && es[es.length - 1].text === '') es.pop();
    }
  };

  for (let i = first + 1; i < last; i += 1) {
    const l = lines[i];
    const n = i + 1;
    if (l.startsWith('*** Add File: ') || l.startsWith('*** Delete File: ') || l.startsWith('*** Update File: ')) {
      stripTrailingEmpty();
      const kind = l.startsWith('*** Add File: ') ? 'add' : l.startsWith('*** Delete File: ') ? 'del' : 'upd';
      cur = { kind, path: l.slice(kind === 'add' ? 14 : kind === 'del' ? 17 : 16).trim(), moveTo: null, chunks: [], addLines: [], line: n };
      bodySeen = false;
      secs.push(cur);
      continue;
    }
    if (l.trim() === '') {
      if (cur === null) continue;
      if (cur.kind === 'add') cur.addLines.push('');
      else if (cur.kind === 'upd') {
        openChunk();
        cur.chunks[cur.chunks.length - 1].entries.push({ k: ' ', text: '' });
        bodySeen = true;
      }
      continue;
    }
    if (cur === null) throw new Exit2(`error: parse ${n}`);
    if (cur.kind === 'upd') {
      if (l.startsWith('*** Move to: ')) {
        if (cur.moveTo !== null || bodySeen) throw new Exit2(`error: parse ${n}`);
        cur.moveTo = l.slice(13).trim();
        continue;
      }
      if (l.startsWith('@@')) {
        cur.chunks.push({ anchor: l.slice(2).trim() || null, eof: false, entries: [] });
        continue;
      }
      if (l === '*** End of File') {
        if (cur.chunks.length === 0 || cur.chunks[cur.chunks.length - 1].eof) throw new Exit2(`error: parse ${n}`);
        cur.chunks[cur.chunks.length - 1].eof = true;
        continue;
      }
      const c = l[0];
      if (c === ' ' || c === '-' || c === '+') {
        openChunk();
        cur.chunks[cur.chunks.length - 1].entries.push({ k: c as Entry['k'], text: l.slice(1) });
        bodySeen = true;
        continue;
      }
      throw new Exit2(`error: parse ${n}`);
    }
    if (cur.kind === 'add') {
      if (l.startsWith('+')) {
        cur.addLines.push(l.slice(1));
        bodySeen = true;
        continue;
      }
      throw new Exit2(`error: parse ${n}`);
    }
    throw new Exit2(`error: parse ${n}`);
  }
  stripTrailingEmpty();
  for (const sec of secs) {
    if (sec.kind === 'upd' && sec.chunks.length === 0 && sec.moveTo === null) throw new Exit2(`error: parse ${sec.line}`);
  }
  return secs;
}

function applyV4A(sec: V4Sec, tree: Tree, strict: boolean): void {
  checkSafe(sec.path);
  if (sec.moveTo !== null) checkSafe(sec.moveTo);
  if (sec.kind === 'add') {
    if (tree.get(sec.path) !== null) throw new Fail('exists', sec.path);
    tree.now.set(sec.path, sec.addLines.length === 0 ? '' : `${sec.addLines.join('\n')}\n`);
    return;
  }
  if (sec.kind === 'del') {
    if (tree.get(sec.path) === null) throw new Fail('missing', sec.path);
    tree.now.set(sec.path, null);
    return;
  }
  const t = tree.get(sec.path);
  if (t === null) throw new Fail('missing', sec.path);
  if (sec.moveTo !== null && tree.get(sec.moveTo) !== null) throw new Fail('exists', sec.moveTo);
  const ft = fileText(t);
  let cursor = 0;
  for (const chunk of sec.chunks) {
    if (chunk.anchor !== null) {
      let found = -1;
      for (const tier of strict ? [0] : [0, 1, 2]) {
        for (let i = cursor; i < ft.lines.length; i += 1) {
          if (lineEq(ft.lines[i], chunk.anchor, tier)) {
            found = i;
            break;
          }
        }
        if (found >= 0) break;
      }
      if (found < 0) throw new Fail('no-match', sec.path);
      cursor = found + 1;
    }
    const { O, N } = buildON(chunk.entries);
    if (O.length > 0) {
      let pos = -1;
      let usedTier = 0;
      for (const tier of strict ? [0] : [0, 1, 2]) {
        for (let i = cursor; i + O.length <= ft.lines.length; i += 1) {
          if (chunk.eof && i + O.length !== ft.lines.length) continue;
          let ok = true;
          for (let j = 0; j < O.length; j += 1) {
            if (!lineEq(ft.lines[i + j], O[j], tier)) {
              ok = false;
              break;
            }
          }
          if (ok) {
            pos = i;
            usedTier = tier;
            break;
          }
        }
        if (pos >= 0) break;
      }
      if (pos < 0) throw new Fail('no-match', sec.path);
      const seg = segment(ft.lines, pos, O, N, usedTier);
      ft.lines.splice(pos, O.length, ...seg);
      cursor = pos + N.length;
    } else {
      const at = chunk.eof ? ft.lines.length : Math.min(cursor, ft.lines.length);
      ft.lines.splice(at, 0, ...N.map((n) => n.text));
      cursor = at + N.length;
    }
  }
  const out = fileJoin(ft);
  if (sec.moveTo !== null) {
    tree.now.set(sec.moveTo, out);
    tree.now.set(sec.path, null);
    tree.moves.set(sec.moveTo, sec.path);
  } else {
    tree.now.set(sec.path, out);
  }
}

function v4aEdits(lines: string[], strict: boolean): Edit[] {
  return parseV4A(lines).map((sec) => (tree) => applyV4A(sec, tree, strict));
}

// ---------------------------------------------------------------- section 9: JSON edits

/** One JSON edit object (SPEC.md section 9), or null when it is not one. */
function jsonEdit(v: unknown): Edit | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  const p = o.path;
  if (typeof p !== 'string') return null;
  const exists = (tree: Tree): string => {
    if (!safe(p)) throw new Fail('unsafe', p);
    const t = tree.get(p);
    if (t === null) throw new Fail('missing', p);
    return t;
  };
  if (o.command === 'create' && typeof o.file_text === 'string') {
    const text = o.file_text;
    return (tree) => {
      if (!safe(p)) throw new Fail('unsafe', p);
      if (tree.get(p) !== null) throw new Fail('exists', p);
      tree.now.set(p, text);
    };
  }
  if (o.command === 'str_replace' && typeof o.old_str === 'string' && o.old_str !== '' && (o.new_str === undefined || typeof o.new_str === 'string')) {
    const oldStr = o.old_str;
    const newStr = (o.new_str as string | undefined) ?? '';
    return (tree) => {
      const before = exists(tree);
      const nl = before.indexOf('\n');
      const crlf = nl > 0 && before[nl - 1] === '\r';
      const lf = (s: string): string => (crlf ? s.replaceAll('\r\n', '\n') : s);
      const t = lf(before);
      const old = lf(oldStr);
      let count = 0;
      for (let k = t.indexOf(old); k >= 0; k = t.indexOf(old, k + 1)) count += 1;
      if (count === 0) throw new Fail('no-match', p);
      if (count > 1) throw new Fail('ambiguous', p);
      const at = t.indexOf(old);
      const out = t.slice(0, at) + lf(newStr) + t.slice(at + old.length);
      tree.now.set(p, crlf ? out.replaceAll('\n', '\r\n') : out);
    };
  }
  if (o.command === 'insert' && typeof o.insert_line === 'number' && Number.isInteger(o.insert_line) && typeof o.new_str === 'string') {
    const line = o.insert_line;
    const add = patchLines(o.new_str);
    return (tree) => {
      const before = exists(tree);
      const nl = before.indexOf('\n');
      const br = nl > 0 && before[nl - 1] === '\r' ? '\r\n' : '\n';
      const lines = before === '' ? [] : before.split(br);
      const final = before !== '' && before.endsWith(br);
      if (final) lines.pop();
      if (line < 0 || line > lines.length) throw new Fail('no-match', p);
      lines.splice(line, 0, ...add);
      tree.now.set(p, lines.length === 0 ? '' : lines.join(br) + (final ? br : ''));
    };
  }
  return null;
}

function jsonEdits(text: string, lines: string[]): Edit[] {
  const first = lines.findIndex((l) => !blank(l));
  if (first < 0) throw new Exit2('error: parse 1');
  const edits: Edit[] = [];
  if (lines[first].trimStart().startsWith('[')) {
    let v: unknown;
    try {
      v = JSON.parse(text);
    } catch {
      throw new Exit2(`error: parse ${first + 1}`);
    }
    if (!Array.isArray(v)) throw new Exit2(`error: parse ${first + 1}`);
    for (const x of v) {
      const e = jsonEdit(x);
      if (e === null) throw new Exit2(`error: parse ${first + 1}`);
      edits.push(e);
    }
    return edits;
  }
  lines.forEach((l, i) => {
    if (blank(l)) return;
    let e: Edit | null = null;
    try {
      e = jsonEdit(JSON.parse(l));
    } catch {
      e = null;
    }
    if (e === null) throw new Exit2(`error: parse ${i + 1}`);
    edits.push(e);
  });
  return edits;
}

// ---------------------------------------------------------------- sections 1, 2, 4 and 10

function detect(lines: string[]): string | null {
  const first = lines.findIndex((l) => !blank(l));
  if (first < 0) return null;
  if (lines[first].trim() === '*** Begin Patch') return 'v4a';
  const c = lines[first].trimStart()[0];
  if (c === '[' || c === '{') return 'json';
  if (lines.some((l) => l.trimEnd() === '<<<<<<< SEARCH')) return 'search-replace';
  if (lines.some((l, i) => l.startsWith('diff --git ') || (l.startsWith('--- ') && (lines[i + 1] ?? '').startsWith('+++ ')))) return 'unified';
  return null;
}

function run(args: string[]): { code: number; out: string[] } {
  let format: string | null = null;
  let check = false;
  let strict = false;
  const pos: string[] = [];
  let ended = false;
  for (const a of args) {
    if (!ended && a === '--') ended = true;
    else if (!ended && a.startsWith('-') && a !== '-') {
      if (a.startsWith('--format=') && format === null && FORMATS.includes(a.slice(9))) format = a.slice(9);
      else if (a === '--check' && !check) check = true;
      else if (a === '--strict' && !strict) strict = true;
      else return { code: 2, out: ['error: usage'] };
    } else pos.push(a);
  }
  if (pos.length > 1) return { code: 2, out: ['error: usage'] };
  const file = pos.length === 0 || pos[0] === '-' ? null : pos[0];
  let text = '';
  try {
    text = readFileSync(file ?? 0, 'utf8');
  } catch {
    if (file !== null) return { code: 2, out: ['error: no-patch'] };
  }
  const lines = patchLines(text);
  const kind = format === null || format === 'auto' ? detect(lines) : format;
  if (kind === null) return { code: 2, out: ['error: format'] };
  let edits: Edit[];
  try {
    edits =
      kind === 'json'
        ? jsonEdits(text, lines)
        : kind === 'unified'
          ? unifiedEdits(lines, strict)
          : kind === 'search-replace'
            ? srEdits(lines, strict)
            : v4aEdits(lines, strict);
    if (edits.length === 0) throw new Exit2('error: parse 1');
  } catch (e) {
    if (e instanceof Exit2) return { code: 2, out: [e.line] };
    throw e;
  }
  const tree = new Tree();
  const fails: Fail[] = [];
  for (const edit of edits) {
    const before = new Map(tree.now);
    try {
      edit(tree);
    } catch (e) {
      if (!(e instanceof Fail)) throw e;
      tree.now.clear();
      for (const [k, v] of before) tree.now.set(k, v);
      fails.push(e);
    }
  }
  if (fails.length > 0)
    return { code: 1, out: [...fails.map((f) => `error: ${f.code} ${f.path}`), `failed: ${fails.length} of ${edits.length} edits`] };
  const rows: { key: string; line: string }[] = [];
  for (const p of tree.now.keys()) {
    const was = tree.original(p);
    const now = tree.now.get(p)!;
    if (was === now) continue;
    rows.push({ key: p, line: `${was === null ? 'A' : now === null ? 'D' : 'M'} ${p}` });
  }
  for (const [newP, oldP] of tree.moves) {
    if (tree.original(oldP) !== null && tree.now.get(oldP) === null && tree.original(newP) === null && tree.now.get(newP) !== null) {
      const d = rows.findIndex((r) => r.key === oldP && r.line === `D ${oldP}`);
      const a = rows.findIndex((r) => r.key === newP && r.line === `A ${newP}`);
      if (d >= 0 && a >= 0) {
        rows.splice(Math.max(d, a), 1);
        rows.splice(Math.min(d, a), 1);
        rows.push({ key: newP, line: `R ${oldP} -> ${newP}` });
      }
    }
  }
  rows.sort((x, y) => Buffer.compare(Buffer.from(x.key, 'utf8'), Buffer.from(y.key, 'utf8')));
  const out = check ? [] : [];
  void out;
  if (!check) {
    for (const [p, now] of [...tree.now.entries()].sort((x, y) => Buffer.compare(Buffer.from(x[0], 'utf8'), Buffer.from(y[0], 'utf8')))) {
      if (now === null) rmSync(p, { force: true });
      else {
        mkdirSync(dirname(p), { recursive: true });
        writeFileSync(p, now);
      }
    }
  }
  return { code: 0, out: [...rows.map((r) => r.line), `ok: ${rows.length} ${rows.length === 1 ? 'file' : 'files'}`] };
}

const trialEnv = process.env.MAKEFUN_ENV_URL;
if (trialEnv !== undefined && trialEnv !== '') {
  // A trial: the kit's runner reads the checks from the env and runs this file on each one, without this variable.
  const { runTrial } = await import('./runner.ts');
  await runTrial(trialEnv);
} else {
  const r = run(process.argv.slice(2));
  writeSync(1, r.out.map((l) => `${l}\n`).join(''));
  process.exitCode = r.code;
}
