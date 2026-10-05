# -*- coding: utf-8 -*-
# split_driver.py — split the 4 remaining over-64KB scenario files.
# Each family: split F into F + its natural next slot, remap Call refs, update
# the family main's include list. Writes outputs to %TMP%\split_out\.
#
# Reference: HANDOFF.md §14 for the mechanism (Call(scpIdx,funcIdx), group
# include list, FileIndex=(0x21<<16)|dir_index).

import re, os, sys, collections, subprocess, importlib.util

TMP = os.path.expandvars(r'%LOCALAPPDATA%\Temp')
sys.path.insert(0, r'C:\Users\Elysion\Sora3Tools')
import split_scenario as SS

MERGED = os.path.join(TMP, 'merged_sn')
OUT = os.path.join(TMP, 'split_out')
os.makedirs(OUT, exist_ok=True)

def load_py(path):
    return open(path, encoding='utf-8', errors='replace').read()

def func_sizes(path):
    """estimated per-function byte size from text length (rough)."""
    header, funcs, bodies = SS.parse(path)
    sizes = []
    for name in funcs:
        sizes.append(sum(len(l) for l in bodies[name]))
    hdr_size = sum(len(l) for l in header)
    return header, funcs, bodies, sizes, hdr_size

def pick_cut(funcs, bodies, sizes, hdr_size, compiled_total, limit=60000):
    """largest K that's a clean cut AND main part fits under limit (compiled).
    Sizes are text-length estimates; calibrate with the file's own
    compiled_total/text_total ratio."""
    g = SS.call_graph(funcs, bodies)
    text_total = hdr_size + sum(sizes)
    ratio = compiled_total / text_total if text_total else 0.26
    def est(txt): return txt * ratio
    best = None
    for K in range(len(funcs)):
        clean = all(c <= K for i, cs in g.items() if i <= K for c in cs)
        if not clean:
            continue
        main_sz = est(hdr_size + sum(sizes[:K+1]))
        new_sz = est(hdr_size + sum(sizes[K+1:]))
        if main_sz < limit and new_sz < limit:
            best = K
    return best

def process(fname, newname, self_scp, new_scp, mainfile, family_members, cut=None):
    """Split MERGED\<fname>.py -> <fname> + <newname>. Remap Call refs in
    family_members (list of basenames in jp_sn_raw/merged_sn)."""
    path = os.path.join(MERGED, fname + '.py')
    header, funcs, bodies, sizes, hdr_size = func_sizes(path)
    if cut is None:
        csz = os.path.getsize(os.path.join(TMP, 'compiled_merged', fname + '._SN')) if os.path.exists(os.path.join(TMP, 'compiled_merged', fname + '._SN')) else 60000
        cut = pick_cut(funcs, bodies, sizes, hdr_size, csz)
    print(f'{fname}: {len(funcs)} funcs, cut at {cut} '
          f'(main est {hdr_size+sum(sizes[:cut+1])}, new est {hdr_size+sum(sizes[cut+1:])})')
    # include list for the new file = the family's group list + new file at new_scp
    main_hdr_txt = load_py(os.path.join(MERGED if os.path.exists(os.path.join(MERGED, mainfile+'.py')) else os.path.join(TMP,'jp_sn_raw'), mainfile + '.py'))
    m = re.search(r"        IncludedScenario    = \[(.*?)\],", main_hdr_txt, re.S)
    inc = [x.strip().strip("'\"") for x in m.group(1).split(',') if x.strip()]
    while len(inc) < 8:
        inc.append('')
    inc = inc[:8]
    inc[new_scp] = f'ED6_DT21/{newname} ._SN'
    # also the split file keeps its own slot in the list (self reference harmless)
    # build outputs
    new_src, mapping = SS.build_newfile(header, funcs, bodies, cut, fname, newname, inc, self_scp, new_scp)
    main_src = SS.build_mainfile(header, funcs, bodies, cut, mapping, inc, self_scp, new_scp)
    mp = os.path.join(OUT, fname + '_split.py')
    np_ = os.path.join(OUT, newname + '_split.py')
    open(mp, 'w', encoding='utf-8', newline='\n').write(main_src)
    open(np_, 'w', encoding='utf-8', newline='\n').write(new_src)
    print('  wrote', os.path.basename(mp), os.path.basename(np_), 'mapping:', mapping)

    # apply Call remap + (for the main file) include-list update, in ONE pass per member
    moved = set(mapping.keys())
    def callsub(mo):
        if int(mo.group(1)) == self_scp and int(mo.group(2)) in moved:
            return f'Call({new_scp}, {mapping[int(mo.group(2))]})'
        return mo.group(0)
    for mem in family_members:
        if mem == fname:
            continue  # split source handled by build_mainfile/build_newfile
        for base in [MERGED, os.path.join(TMP, 'jp_sn_raw')]:
            p = os.path.join(base, mem + '.py')
            if not os.path.exists(p):
                continue
            txt = load_py(p)
            new_txt = SS.CALL_RE.sub(callsub, txt)
            if mem == mainfile:
                m2 = re.search(r"        IncludedScenario    = \[(.*?)\],", new_txt, re.S)
                if m2:
                    cur = [x.strip().strip("'\"") for x in m2.group(1).split(',')]
                    while len(cur) < 8:
                        cur.append('')
                    cur = cur[:8]
                    cur[new_scp] = f'ED6_DT21/{newname} ._SN'
                    newinc = "        IncludedScenario    = [\n" + ''.join(f"            '{x}',\n" for x in cur) + "        ],"
                    new_txt = new_txt[:m2.start()] + newinc + new_txt[m2.end():]
            if new_txt != txt:
                out_p = os.path.join(OUT, mem + '_final.py')
                open(out_p, 'w', encoding='utf-8', newline='\n').write(new_txt)
                print(f'  updated {mem} -> {out_p}')
            break

if __name__ == '__main__':
    # (fname, newname, self_scp, new_scp, mainfile, family_members, cut)
    jobs = [
        ('U7002_5', 'U7002_6', 5, 7, 'U7002', ['U7002', 'U7002_4', 'U7002_5'], None),
        ('U7003_5', 'U7003_6', 5, 7, 'U7003', ['U7003', 'U7003_4', 'U7003_5'], None),
        ('M7408',   'M7408_1', 0, 1, 'M7408', ['M7408'], None),
        ('T4206',   'T4206_1', 0, 7, 'T4206', ['T4206'], None),
    ]
    for j in jobs:
        process(*j)
