# -*- coding: utf-8 -*-
# voice_merge.py — merge J31why Evo voice IDs (#<id>v) into JP decompiled
# scenario scripts, aligned by structure (diff) + message segmentation.
#
# Reads:
#   %LOCALAPPDATA%\Temp\j31_sn\*.py     (J31why CN scripts with voice IDs)
#   %LOCALAPPDATA%\Temp\jp_sn_raw\*.py  (JP original decompiled scripts)
# Writes:
#   %LOCALAPPDATA%\Temp\merged_sn\*.py  (JP scripts + injected voice IDs)
#   %LOCALAPPDATA%\Temp\voice_merge_report.txt

import re, os, sys, glob, difflib, collections

TMP = os.path.expandvars(r'%LOCALAPPDATA%\Temp')
J31_DIR = os.path.join(TMP, 'j31_sn')
JP_DIR = os.path.join(TMP, 'jp_sn_raw')
OUT_DIR = os.path.join(TMP, 'merged_sn')
REPORT = os.path.join(TMP, 'voice_merge_report.txt')

BS = chr(92)
lit_re = re.compile(r'(["\'])((?:(?!\1).|\\.)*)\1')
standalone_re = re.compile(r'^(\s*)(["\'])((?:(?!\2).|\\.)*)\2(\s*,?\s*(#.*)?)$')
scp_re = re.compile(r'^\s*scpstr\(.*\)\s*,?\s*$')
func_re = re.compile(r'Function_\d+_[0-9A-Fa-f]+|lambda_[0-9A-Fa-f]+')
voice_re = re.compile(r'^#(\d+)v')
marker_re = re.compile(r'^#(\d+[A-Za-z])')
code_re = re.compile(r'#\d+[A-Za-z]')
esc_re = re.compile(re.escape(BS) + r'x([0-9A-Fa-f]{2})')

# run item: ('lit', body, lineno, col) or ('scp', normline, lineno, None)


def esc_codes(body):
    return {int(m.group(1), 16) for m in esc_re.finditer(body)}


def tokenize(path, keep_pos):
    """Return (tokens, lines). Tokens: ['CODE', key] or ['STRRUN', items]."""
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.read().splitlines()
    toks = []

    def add_item(item):
        if toks and toks[-1][0] == 'STRRUN':
            toks[-1][1].append(item)
        else:
            toks.append(['STRRUN', [item]])

    for ln, line in enumerate(lines):
        m = standalone_re.match(line)
        if m:
            add_item(('lit', m.group(3), ln, m.start(3) if keep_pos else None))
            continue
        if scp_re.match(line):
            norm = func_re.sub('F', lit_re.sub('S', line))
            if '#' in norm:
                norm = norm[:norm.index('#')]
            add_item(('scp', norm.rstrip(), ln, None))
            continue
        l = func_re.sub('F', lit_re.sub('S', line))
        if '#' in l:
            l = l[:l.index('#')]
        toks.append(('CODE', l.rstrip()))
    return toks, lines


def segments(items):
    """Split run items into message segments [start_idx, end_idx] (item indices).
    Boundary: a 'lit' item containing \\x02 or \\x03 ends a message.
    A 'lit' item with no escape codes at all is a name -> its own segment.
    'scp' items are neutral content (never a boundary, never a name)."""
    segs = []
    start = 0
    for i, (kind, body, _, _) in enumerate(items):
        if kind != 'lit':
            continue
        codes = esc_codes(body)
        if not codes:
            if i > start:
                segs.append([start, i - 1])
            segs.append([i, i])
            start = i + 1
            continue
        if 0x02 in codes or 0x03 in codes:
            segs.append([start, i])
            start = i + 1
    if start < len(items):
        segs.append([start, len(items) - 1])
    return segs


def seg_lits(items, seg):
    return [body for kind, body, _, _ in items[seg[0]:seg[1] + 1] if kind == 'lit']


def is_voice_only_seg(items, seg):
    """Segment whose literal content is only a voice directive + control codes,
    and which has no scp (display) content."""
    lits = seg_lits(items, seg)
    if not lits:
        return False
    if any(kind == 'scp' for kind, *_ in items[seg[0]:seg[1] + 1]):
        return False
    txt = ''.join(lits)
    m = voice_re.match(txt)
    if not m:
        return False
    rest = txt[m.end():]
    rest = code_re.sub('', esc_re.sub('', rest))
    return rest.strip() == ''


def first_lit_idx(items, seg):
    for i in range(seg[0], seg[1] + 1):
        if items[i][0] == 'lit':
            return i
    return None


def run_signature(items):
    """Marker at each segment start (voice prefix stripped), 'NM' if none."""
    sig = []
    for seg in segments(items):
        fl = first_lit_idx(items, seg)
        if fl is None:
            sig.append('SCP')
            continue
        body = items[fl][1]
        vm = voice_re.match(body)
        if vm:
            body = body[vm.end():]
        mm = marker_re.match(body)
        sig.append(mm.group(1) if mm else 'NM')
    return tuple(sig)


tok_re = re.compile(r'[Ａ-Ｚａ-ｚ０-９]{2,}|[A-Za-z0-9]{2,}|[Ａ-Ｚａ-ｚA-Za-z]')


def seg_strong_tokens(items, seg, strip_voice=False):
    """Language-independent tokens in a segment: alnum runs (len>=2) and
    single letters, full-width or half-width. Escapes stripped."""
    parts = []
    for kind, body, _, _ in items[seg[0]:seg[1] + 1]:
        if kind == 'lit':
            parts.append(body)
        else:
            parts.append(' ' * len(body))  # scp: ignore content
    txt = ''.join(parts)
    if strip_voice:
        txt = voice_re.sub('', txt)
    txt = esc_re.sub('', txt)
    return set(tok_re.findall(txt))


def merge_file(j31_path, jp_path, report, injections, line_inserts, use_global_sig=False):
    """Align one J31 file against one JP file; record injections.
    injections: dict jp_path -> list of (lineno, col, voice_id, tag, ctx)."""
    name = os.path.basename(j31_path)
    t31, _ = tokenize(j31_path, keep_pos=False)
    tjp, jp_lines = tokenize(jp_path, keep_pos=True)
    key = lambda x: 'STRRUN' if x[0] == 'STRRUN' else x[1]
    sm = difflib.SequenceMatcher(a=[key(x) for x in tjp],
                                 b=[key(x) for x in t31], autojunk=False)
    stats = collections.Counter()

    # merge adjacent non-equal opcodes into single "changed" regions
    regions = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            regions.append(('equal', i1, i2, j1, j2))
        elif regions and regions[-1][0] == 'changed':
            _, pi1, _, pj1, _ = regions[-1]
            regions[-1] = ('changed', pi1, i2, pj1, j2)
        else:
            regions.append(('changed', i1, i2, j1, j2))

    # build run pairs: (jp_tok_idx, j31_tok_idx, in_replace_block)
    run_pairs = []
    for tag, i1, i2, j1, j2 in regions:
        if tag == 'equal':
            for k in range(j2 - j1):
                if t31[j1 + k][0] == 'STRRUN':
                    run_pairs.append((i1 + k, j1 + k, 'eq'))
            continue
        jp_runs = [i for i in range(i1, i2) if tjp[i][0] == 'STRRUN']
        j31_runs = [j for j in range(j1, j2) if t31[j][0] == 'STRRUN']

        def lost(jlist, why):
            n = sum(1 for j in jlist
                    for kind, b, _, _ in t31[j][1]
                    if kind == 'lit' and voice_re.match(b))
            if n:
                stats[f'drop_{why}'] += n
                report.append(f'{name}: {why} lost {n} voice lines '
                              f'(runs {len(jlist)} vs {len(jp_runs)})')
            return n

        if len(jp_runs) == len(j31_runs):
            for a, b in zip(jp_runs, j31_runs):
                run_pairs.append((a, b, 're'))
            continue
        # unequal region: pair runs by identical marker signature
        jp_by_sig = collections.defaultdict(collections.deque)
        for i in jp_runs:
            jp_by_sig[run_signature(tjp[i][1])].append(i)
        unmatched = []
        for j in j31_runs:
            sig = run_signature(t31[j][1])
            has_marker = any(s != 'NM' for s in sig)
            if has_marker and jp_by_sig.get(sig):
                i = jp_by_sig[sig].popleft()
                run_pairs.append((i, j, 're'))
                stats['region_sig_paired'] += 1
            else:
                unmatched.append(j)
        lost(unmatched, 'region_unmatched')

    # second pass: lost voice runs with marker-ful signatures get one more
    # chance — unique signature match anywhere in the JP file ('global_sig')
    if use_global_sig:
        paired_j31 = {j for _, j, _ in run_pairs}
        used_jp = {i for i, _, _ in run_pairs}
        jp_sig_index = collections.defaultdict(list)
        for i, tok in enumerate(tjp):
            if tok[0] == 'STRRUN':
                jp_sig_index[run_signature(tok[1])].append(i)
        for j, tok in enumerate(t31):
            if tok[0] != 'STRRUN' or j in paired_j31:
                continue
            if not any(kind == 'lit' and voice_re.match(b)
                       for kind, b, _, _ in tok[1]):
                continue
            sig = run_signature(tok[1])
            if not any(s != 'NM' for s in sig):
                continue
            cands = [i for i in jp_sig_index.get(sig, []) if i not in used_jp]
            if len(cands) == 1:
                run_pairs.append((cands[0], j, 'gs'))
                used_jp.add(cands[0])
                stats['global_sig_paired'] += 1

    for jp_tok_idx, j31_tok_idx, pair_kind in run_pairs:
        items31 = t31[j31_tok_idx][1]
        itemsjp = tjp[jp_tok_idx][1]
        vpos = [(i, voice_re.match(body).group(1))
                for i, (kind, body, _, _) in enumerate(items31)
                if kind == 'lit' and voice_re.match(body)]
        if not vpos:
            continue
        segs31 = segments(items31)
        segsjp = segments(itemsjp)

        # fold voice-only segments: carry their voice entries to next segment
        filtered31 = []   # [orig_seg, [(vid, body), ...]]
        pending = []
        for seg in segs31:
            if is_voice_only_seg(items31, seg):
                for b in seg_lits(items31, seg):
                    m = voice_re.match(b)
                    if m:
                        pending.append((m.group(1), b))
                stats['voice_only_seg'] += 1
                continue
            ids = pending
            pending = []
            for i in range(seg[0], seg[1] + 1):
                kind, body, _, _ = items31[i]
                if kind == 'lit':
                    m = voice_re.match(body)
                    if m:
                        ids.append((m.group(1), body))
            filtered31.append((seg, ids))
        if pending:
            if filtered31:
                filtered31[-1][1].extend(pending)
            else:
                stats['drop_trailing_voice_only'] += len(pending)

        if not any(ids for _, ids in filtered31):
            continue

        pair_mode = 'ordinal'
        if len(filtered31) != len(segsjp):
            pair_mode = 'mismatch'
            stats['segcount_mismatch_runs'] += 1

        # token-anchored monotonic alignment for mismatch runs:
        # alnum tokens (full/half width, len>=2, or single letters) bridge
        # CN/JP text; voice lines are assigned in order to later JP segments.
        token_assign = {}
        if pair_mode == 'mismatch':
            jp_toks = [seg_strong_tokens(itemsjp, s) for s in segsjp]
            ptr = 0
            for n, (seg31, ids) in enumerate(filtered31):
                if not ids:
                    continue
                ct = seg_strong_tokens(items31, seg31, strip_voice=True)
                if not ct:
                    continue
                best, bestov = None, 0
                for k in range(ptr, len(jp_toks)):
                    ov = len(ct & jp_toks[k])
                    if ov > bestov:
                        best, bestov = k, ov
                if best is not None and bestov >= 1:
                    token_assign[n] = best
                    ptr = best + 1

        used_jp = set()
        for n, (seg31, ids) in enumerate(filtered31):
            if not ids:
                continue
            tgt = None
            tag_conf = []
            if pair_mode == 'ordinal':
                tgt = n
            else:
                mmark = None
                fl = first_lit_idx(items31, seg31)
                if fl is not None:
                    vm = voice_re.match(items31[fl][1])
                    if vm:
                        mm = marker_re.match(items31[fl][1][vm.end():])
                        if mm:
                            mmark = mm.group(1)
                if mmark:
                    cands = []
                    for k, s in enumerate(segsjp):
                        if k in used_jp:
                            continue
                        jl = first_lit_idx(itemsjp, s)
                        if jl is None:
                            continue
                        mj = marker_re.match(itemsjp[jl][1])
                        if mj and mj.group(1) == mmark:
                            cands.append(k)
                    if len(cands) == 1:
                        tgt = cands[0]
                        tag_conf.append('marker_anchor')
                if tgt is None and n in token_assign and token_assign[n] not in used_jp:
                    tgt = token_assign[n]
                    tag_conf.append('token_anchor')
            if tgt is None or tgt in used_jp or tgt >= len(segsjp):
                stats['drop_no_target'] += len(ids)
                for vid, _ in ids:
                    report.append(f'{name}: drop #{vid}v (no target, run@tok{j31_tok_idx})')
                continue
            used_jp.add(tgt)
            segjp = segsjp[tgt]
            # compute fused-voice target literal + marker confidence lazily,
            # only when a non-bare (fused) voice exists in this segment
            fused_state = None

            def fused_target():
                nonlocal fused_state
                if fused_state is not None:
                    return fused_state
                tgt_lit = first_lit_idx(itemsjp, segjp)
                tag_c = []
                if tgt_lit is not None and esc_codes(itemsjp[tgt_lit][1]) == set():
                    nxt = first_lit_idx(itemsjp, [tgt_lit + 1, segjp[1]])
                    if nxt is not None:
                        tgt_lit = nxt
                        tag_c.append('skip_name')
                    else:
                        tgt_lit = None
                tag_m = 'both_nomarker'
                if tgt_lit is not None:
                    fl = first_lit_idx(items31, seg31)
                    rest = ''
                    if fl is not None:
                        vm = voice_re.match(items31[fl][1])
                        if vm:
                            rest = items31[fl][1][vm.end():]
                    mm = marker_re.match(rest)
                    mj = marker_re.match(itemsjp[tgt_lit][1])
                    if mm and mj:
                        tag_m = 'marker_ok' if mm.group(1) == mj.group(1) else 'marker_diff'
                    elif mm and not mj:
                        tag_m = 'cn_marker_only'
                    elif mj and not mm:
                        tag_m = 'jp_marker_only'
                tag_c.append(tag_m)
                if pair_kind != 'eq':
                    tag_c.append('global_sig' if pair_kind == 'gs' else 'replace_block')
                fused_state = (tgt_lit, tag_c, tag_m)
                return fused_state

            fused_done = False
            for vid, ebody in ids:
                vbody = ebody[voice_re.match(ebody).end():]
                if esc_re.sub('', vbody).strip() == '':
                    # bare voice directive (standalone literal in CN) —
                    # replicate J31why's structure instead of fusing
                    jp_first = first_lit_idx(itemsjp, segjp)
                    jp_body = itemsjp[jp_first][1] if jp_first is not None else None
                    if jp_body is not None and vbody == jp_body:
                        _, _, ln, col = itemsjp[jp_first]
                        injections[jp_path].append((ln, col, vid, 9, 'bare_match', name))
                        stats['injected'] += 1
                        stats['conf_bare_match'] += 1
                    else:
                        ln = itemsjp[segjp[0]][2]
                        line_inserts[jp_path].append((ln, ebody, name))
                        stats['injected'] += 1
                        stats['conf_standalone_insert'] += 1
                    continue
                # fused voice (voice prefix inside a real text literal)
                if fused_done:
                    stats['drop_extra_voice_in_seg'] += 1
                    report.append(f'{name}: drop extra #{vid}v in seg (run@tok{j31_tok_idx})')
                    continue
                tgt_lit, tag_conf, tag_m = fused_target()
                if tgt_lit is None:
                    stats['drop_name_only_target'] += 1
                    report.append(f'{name}: drop #{vid}v (target is bare name, '
                                  f'run@tok{j31_tok_idx})')
                    continue
                # token-anchored guesses with conflicting face markers are
                # almost certainly different lines — refuse them
                if 'token_anchor' in tag_conf and tag_m == 'marker_diff':
                    stats['drop_token_marker_conflict'] += 1
                    report.append(f'{name}: drop #{vid}v (token anchor but marker '
                                  f'conflict, run@tok{j31_tok_idx})')
                    continue
                fused_done = True
                stats['injected'] += 1
                SCORES = {'marker_ok': 10, 'marker_anchor': 8, 'jp_marker_only': 6,
                          'cn_marker_only': 5, 'marker_diff': 4, 'both_nomarker': 3,
                          'ordinal_fallback': -2, 'token_anchor': 7, 'replace_block': -2, 'global_sig': 6, 'skip_name': 0}
                score = sum(SCORES.get(t, 0) for t in tag_conf)
                for t in tag_conf:
                    stats['conf_' + t] += 1
                _, _, ln, col = itemsjp[tgt_lit]
                injections[jp_path].append((ln, col, vid, score, '+'.join(tag_conf), name))
    return stats


def fambase(fn):
    """'u7002_6.py' -> 'u7002', 'c0301.py' -> 'c0301' (lowercase)."""
    return re.sub(r'_\d+\.py$', '.py', fn.lower())[:-3]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    tsv = os.path.join(TMP, 'voice_applied.tsv')
    if os.path.exists(tsv):
        os.remove(tsv)
    only = sys.argv[1].lower() if len(sys.argv) > 1 else None
    jp_files = {f.lower(): f for f in os.listdir(JP_DIR) if f.endswith('.py')}
    j31_all = sorted(glob.glob(os.path.join(J31_DIR, '*.py')))
    if only:
        j31_all = [p for p in j31_all if os.path.basename(p).lower() == only]

    # group into families (base name without _N suffix)
    j31_fams = collections.defaultdict(list)
    jp_fams = collections.defaultdict(list)
    for p in j31_all:
        j31_fams[fambase(os.path.basename(p))].append(p)
    for fl, f in jp_files.items():
        jp_fams[fambase(fl)].append(f)

    # build (j31, jp) pair jobs; family mode when either side has _N members.
    # NOTE: EN and JP pack scenario content at different boundaries even
    # within same-count families (JP packs more into early files), so
    # cross-file pairing is legitimate and required for complete coverage.
    jobs = []  # (j31_path, jp_path, family_mode)
    seen_pairs = set()
    for base, members in sorted(j31_fams.items()):
        jp_members = jp_fams.get(base, [])
        if not jp_members:
            continue
        family_mode = len(members) > 1 or len(jp_members) > 1
        for p in members:
            for f in jp_members:
                pair = (p, os.path.join(JP_DIR, f), family_mode)
                if pair[:2] not in seen_pairs:
                    seen_pairs.add(pair[:2])
                    jobs.append(pair)

    injections = collections.defaultdict(list)  # jp_path -> [(ln,col,vid,score,tag,src)]
    line_inserts = collections.defaultdict(list)  # jp_path -> [(ln, body, src)]
    report = []
    total = collections.Counter()
    pair_scores = {}  # (j31,jp) -> marker_ok count
    missing = [b for b in j31_fams if b not in jp_fams]
    for b in missing:
        for p in j31_fams[b]:
            report.append(f'{os.path.basename(p)}: NO JP counterpart')
            total['no_jp_counterpart'] += 1

    # pass A: score every pair without global_sig
    pair_results = {}
    for j31_path, jp_path, family_mode in jobs:
        per_pair = collections.defaultdict(list)
        per_ins = collections.defaultdict(list)
        rep = []
        st = merge_file(j31_path, jp_path, rep, per_pair, per_ins)
        quality = st.get('conf_marker_ok', 0) + st.get('conf_both_nomarker', 0)
        pair_scores[(j31_path, jp_path)] = quality
        pair_results[(j31_path, jp_path)] = (st, per_pair, per_ins, rep)

    # best pair per j31 file (exact-name match wins ties)
    best_pair = {}
    for j31_path, jp_path, family_mode in jobs:
        q = pair_scores[(j31_path, jp_path)]
        exact = os.path.basename(j31_path).lower() == os.path.basename(jp_path).lower()
        cur = best_pair.get(j31_path)
        if cur is None or (q, exact) > cur[0]:
            best_pair[j31_path] = ((q, exact), jp_path)

    # pass B: best pairs rerun with global_sig enabled; others keep pass A
    for j31_path, jp_path, family_mode in jobs:
        is_best = best_pair[j31_path][1] == jp_path
        if is_best:
            per_pair = collections.defaultdict(list)
            per_ins = collections.defaultdict(list)
            rep = []
            st = merge_file(j31_path, jp_path, rep, per_pair, per_ins, use_global_sig=True)
            quality = st.get('conf_marker_ok', 0) + st.get('conf_both_nomarker', 0)
            pair_scores[(j31_path, jp_path)] = quality
            pair_results[(j31_path, jp_path)] = (st, per_pair, per_ins, rep)
        st, per_pair, per_ins, rep = pair_results[(j31_path, jp_path)]
        total.update(st)
        report.extend(rep)
        quality = pair_scores[(j31_path, jp_path)]
        if family_mode and quality < 10:
            total['family_pair_skipped'] += 1
            continue
        for jp_p, lst in per_pair.items():
            injections[jp_p].extend(lst)
        for jp_p, lst in per_ins.items():
            line_inserts[jp_p].extend(lst)

    # dedupe: by (jp_path, ln, col) keep highest score; global vid dedupe
    applied = 0
    collisions = 0
    vid_seen = set()
    all_paths = list(dict.fromkeys(list(injections.keys()) + list(line_inserts.keys())))
    for jp_path in all_paths:
        inj = injections.get(jp_path, [])
        inj.sort(key=lambda x: -x[3])
        taken = set()
        kept = []
        kept_full = []
        for ln, col, vid, score, tag, src in inj:
            if (ln, col) in taken:
                collisions += 1
                report.append(f'{os.path.basename(jp_path)}: collision line {ln}, '
                              f'drop #{vid}v ({tag}) from {src}')
                continue
            if vid in vid_seen:
                collisions += 1
                report.append(f'{os.path.basename(jp_path)}: dup vid #{vid}v '
                              f'from {src} (already placed)')
                continue
            taken.add((ln, col))
            vid_seen.add(vid)
            kept.append((ln, col, vid))
            kept_full.append((ln, col, vid, tag, src))
        with open(jp_path, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines(keepends=True)
        kept.sort(key=lambda x: (x[0], -x[1]))
        with open(os.path.join(TMP, 'voice_applied.tsv'), 'a', encoding='utf-8') as tf:
            for ln, col, vid, tag, src in kept_full:
                tf.write(os.path.basename(jp_path) + chr(9) + str(ln) + chr(9) + vid + chr(9) + tag + chr(9) + src + chr(10))
        for ln, col, vid in kept:
            lines[ln] = lines[ln][:col] + f'#{vid}v' + lines[ln][col:]
            applied += 1
        # standalone voice-literal inserts (after col edits; bottom-up,
        # grouped by target line preserving CN order)
        ins_list = line_inserts.get(jp_path, [])
        seen_ins = set()
        grouped = collections.defaultdict(list)
        for ln, body, src in ins_list:
            if (ln, body) in seen_ins:
                continue
            seen_ins.add((ln, body))
            grouped[ln].append(body)
        for ln in sorted(grouped, reverse=True):
            indent = lines[ln][:len(lines[ln]) - len(lines[ln].lstrip())]
            block = ''.join(indent + '"' + b + '",' + chr(10) for b in grouped[ln])
            lines.insert(ln, block)
            applied += len(grouped[ln])
            stats_line = f'{os.path.basename(jp_path)}: inserted {len(grouped[ln])} standalone voice line(s) before line {ln}'
            report.append(stats_line)
        out = os.path.join(OUT_DIR, os.path.basename(jp_path))
        with open(out, 'w', encoding='utf-8', newline='\n') as f:
            f.writelines(lines)

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write(f'pair jobs: {len(jobs)}\n')
        f.write(f'JP files with injections: {len(injections)}\n')
        f.write(f'injections applied: {applied}, collisions+dups dropped: {collisions}\n')
        for k, v in total.most_common():
            f.write(f'{k}: {v}\n')
        f.write('\n--- pair marker_ok scores (family) ---\n')
        for (j, p), s in sorted(pair_scores.items(), key=lambda x: -x[1]):
            f.write(f'{os.path.basename(j)} x {os.path.basename(p)}: {s}\n')
        f.write('\n'.join(report))
    print(f'jobs={len(jobs)} jp_with_inj={len(injections)} applied={applied} collisions={collisions}')
    for k, v in total.most_common():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
