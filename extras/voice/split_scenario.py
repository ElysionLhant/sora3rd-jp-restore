# -*- coding: utf-8 -*-
# split_scenario.py — split an oversized (>64KB) decompiled scenario .py into
# two files sharing the map via the IncludeScenario group mechanism.
#
# Usage: python split_scenario.py <merged_py> <main_out_name> <new_out_name> <cut_index>
#   e.g. python split_scenario.py U7000_1.py U7000_1 U7000_6 29
#
# Functions [0..cut] stay in <main_out>, functions [cut+1..] move to <new_out>.
# Call(scpIdx, funcIdx) references are remapped: internal (scpIdx==1) calls to
# moved functions become Call(7, newIdx). Family include lists get <new_out>
# appended at group slot 7 (SUB000 stays at 6).

import re, os, sys, collections

TMP = os.path.expandvars(r'%LOCALAPPDATA%\Temp')

FUNC_DEF_RE = re.compile(r'^    def (Function_\d+_[0-9A-Fa-f]+)\(\): pass\s*$')
LABEL_RE = re.compile(r'^( *)label\("(Function_\d+_[0-9A-Fa-f]+)"\)\s*$')
SCP_ENTRY_RE = re.compile(r'"(Function_\d+_[0-9A-Fa-f]+)",\s*# ([0-9A-Fa-f]+), (\d+)')
CALL_RE = re.compile(r'Call\((\d+), (\d+)\)')

def parse(path):
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines(keepends=True)
    # header = up to the line with "    ScpFunction("
    scp_i = next(i for i, l in enumerate(lines) if l.strip() == 'ScpFunction(')
    header = lines[:scp_i]
    # function table entries until the closing ')'
    tbl = []
    j = scp_i + 1
    while lines[j].strip() != ')':
        m = SCP_ENTRY_RE.search(lines[j])
        if m:
            tbl.append((m.group(1), int(m.group(3))))
        j += 1
    # function bodies: from each "def Function..." to its "# Function... end"
    bodies = collections.OrderedDict()  # name -> list of lines
    i = j + 1
    cur = None
    for k in range(i, len(lines)):
        dm = FUNC_DEF_RE.match(lines[k])
        if dm:
            cur = dm.group(1)
            bodies[cur] = [lines[k]]
            continue
        if cur:
            bodies[cur].append(lines[k])
    # assign index by table order
    funcs = [name for name, _ in tbl]
    return header, funcs, bodies

def call_graph(funcs, bodies, self_scp=1):
    g = collections.defaultdict(set)
    for idx, name in enumerate(funcs):
        for line in bodies[name]:
            for m in CALL_RE.finditer(line):
                if int(m.group(1)) == self_scp:
                    g[idx].add(int(m.group(2)))
    return g

def choose_cut(funcs, bodies):
    g = call_graph(funcs, bodies)
    best = None
    for K in range(0, len(funcs)):
        if all(c <= K for i, cs in g.items() if i <= K for c in cs):
            best = K
    return best

def remap_calls(text, mapping, moved, self_scp=1, new_scp=7):
    """Remap Call(scp,func) in a body of text.
    mapping: old internal func index -> new func index (for moved funcs).
    moved: set of old func indices that moved out.
    Calls to moved funcs (scp==self_scp) become Call(new_scp, mapping[func]).
    """
    def sub(m):
        scp, fn = int(m.group(1)), int(m.group(2))
        if scp == self_scp and fn in moved:
            return f'Call({new_scp}, {mapping[fn]})'
        return m.group(0)
    return CALL_RE.sub(sub, text)

def build_newfile(header, funcs, bodies, cut, main_name, new_name, inc_list, self_scp=1, new_scp=7):
    moved_names = funcs[cut + 1:]
    # function table for new file: reindex 0..M
    out = []
    out.append('from ED63RDScenarioHelper import *\n')
    out.append('\n')
    out.append('def main():\n')
    out.append('    SetCodePage("ms932")\n')
    out.append('\n')
    # CreateScenaFile block: copy from main header but change FileName + IncludedScenario
    hdr = ''.join(header)
    # replace FileName
    hdr = re.sub(r"FileName\s*=\s*'[^']*'", f"FileName            = '{new_name}._SN'", hdr, count=1)
    # replace IncludedScenario block
    inc_new = ("        IncludedScenario    = [\n"
               + ''.join(f"            '{x}',\n" for x in inc_list)
               + "        ],")
    hdr = re.sub(r"        IncludedScenario    = \[.*?\],", inc_new, hdr, count=1, flags=re.S)
    out.append(hdr[hdr.index('    CreateScenaFile'):])
    out.append('\n\n')
    # function table
    out.append('    ScpFunction(\n')
    mapping = {}
    for ni, name in enumerate(moved_names):
        old_idx = cut + 1 + ni
        mapping[old_idx] = ni
        out.append(f'        "{name}",' + ' ' * (24 - len(name)) + f'# {ni:02X}, {ni}\n')
    out.append('    )\n\n\n')
    # bodies with remapped internal calls
    moved_old = set(mapping.keys())
    for ni, name in enumerate(moved_names):
        body = ''.join(bodies[name])
        body = remap_calls(body, mapping, moved_old, self_scp, new_scp)
        # also self-references within new file: Call(1, N) for N in moved -> Call(7, mapping[N])
        out.append(body)
        out.append('\n')
    return ''.join(out), mapping

def build_mainfile(header, funcs, bodies, cut, mapping, inc_list, self_scp=1, new_scp=7):
    keep = funcs[:cut + 1]
    out = []
    hdr = ''.join(header)
    hdr = re.sub(r"        IncludedScenario    = \[.*?\]",
                 "        IncludedScenario    = [\n" + ''.join(f"            '{x}',\n" for x in inc_list) + "        ]",
                 hdr, count=1, flags=re.S)
    out.append(hdr)
    out.append('    ScpFunction(\n')
    for ni, name in enumerate(keep):
        out.append(f'        "{name}",' + ' ' * (24 - len(name)) + f'# {ni:02X}, {ni}\n')
    out.append('    )\n\n\n')
    moved_old = set(mapping.keys())
    for name in keep:
        body = ''.join(bodies[name])
        body = remap_calls(body, mapping, moved_old, self_scp, new_scp)
        out.append(body)
        out.append('\n')
    out.append('    SaveToFile()\n\nTry(main)\n')
    return ''.join(out)

def main():
    path, main_name, new_name, cut = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    header, funcs, bodies = parse(path)
    print(f'parsed {len(funcs)} functions, header {len(header)} lines')
    if cut < 0:
        cut = choose_cut(funcs, bodies)
        print('auto cut ->', cut)
    # include list for both files: family's list + new file at slot 7
    # main's original include list (names) from header
    hdr_txt = ''.join(header)
    m = re.search(r"        IncludedScenario    = \[(.*?)\],", hdr_txt, re.S)
    inc = [x.strip().strip("'\"") for x in m.group(1).split(',') if x.strip()]
    # ensure 7 slots then new file at slot 7
    while len(inc) < 7:
        inc.append('')
    inc = inc[:7] + [f'ED6_DT21/{new_name} ._SN']
    new_src, mapping = build_newfile(header, funcs, bodies, cut, main_name, new_name, inc)
    main_src = build_mainfile(header, funcs, bodies, cut, mapping, inc)
    outdir = os.path.dirname(path)
    mp = os.path.join(outdir, main_name + '_split.py')
    np_ = os.path.join(outdir, new_name + '_split.py')
    open(mp, 'w', encoding='utf-8', newline='\n').write(main_src)
    open(np_, 'w', encoding='utf-8', newline='\n').write(new_src)
    print('wrote', mp, np_)
    print('mapping (moved old->new):', mapping)

if __name__ == '__main__':
    main()
