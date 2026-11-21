"""相邻钻孔对层：三项物性分布相似度 + 单调（不交叉）动态规划。

现场锚点先固定；锚点之间的层用动态规划补全，允许任一侧尖灭。
缺芯、无实测点或相似度不唯一的对层只给出待核实结果，不冒充确定结论。
"""
import math

FEATURES = ['density', 'susceptibility', 'velocity']
STD_WEIGHT = 0.5
GAP_PENALTY = 1.15
NO_DATA_COST = 0.85
AMBIGUITY_MARGIN = 0.30
MAX_MATCH_DISTANCE = 1.35
PINCH_AMBIGUITY = 0.75

PARAMETERS = {
    'features': FEATURES,
    'std_weight': STD_WEIGHT,
    'gap_penalty': GAP_PENALTY,
    'no_data_cost': NO_DATA_COST,
    'ambiguity_margin': AMBIGUITY_MARGIN,
    'max_match_distance': MAX_MATCH_DISTANCE,
    'pinch_ambiguity': PINCH_AMBIGUITY,
}


def layer_statistics(strata, readings, missing):
    """每一已确认层段的三项物性分布摘要；只统计落在层内的真实测点。"""
    out = []
    for index, st in enumerate(strata, start=1):
        pts = [r for r in readings if st['start_m'] - 1e-9 <= r['depth_m'] < st['end_m'] - 1e-9]
        gaps = [m for m in missing if m['start_m'] < st['end_m'] - 1e-9 and m['end_m'] > st['start_m'] + 1e-9]
        row = {
            'stratum_id': st['id'],
            'index': index,
            'interpretation_id': st['interpretation_id'],
            'start_m': st['start_m'],
            'end_m': st['end_m'],
            'lithology': st['lithology'],
            'contact_note': st.get('contact_note', ''),
            'n': len(pts),
            'reading_ids': [r['id'] for r in pts],
            'missing': [{'start_m': m['start_m'], 'end_m': m['end_m'], 'reason': m.get('reason', '')} for m in gaps],
            'has_gap': bool(gaps),
        }
        for f in FEATURES:
            if not pts:
                row[f] = None
                continue
            vals = [float(r[f]) for r in pts]
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            row[f] = {
                'mean': round(mean, 6),
                'std': round(math.sqrt(var), 6),
                'min': round(min(vals), 6),
                'max': round(max(vals), 6),
            }
        out.append(row)
    return out


def _pooled_std(values, weights):
    total = sum(weights)
    if total <= 0:
        return 0.0
    mean = sum(v * w for v, w in zip(values, weights)) / total
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total
    return math.sqrt(var)


def scales(left, right):
    """按“层内噪声”归一：均值差与离散度差都以层内标准差为单位。

    层数很少时也能稳定估计；若某物性层内几乎无离散，退到该物性层间总变幅的 5% 作下限。
    """
    layers = [s for s in left + right if s['n']]
    out = {}
    for f in FEATURES:
        means = [s[f]['mean'] for s in layers]
        weights = [s['n'] for s in layers]
        spread = (max(means) - min(means)) if means else 0.0
        # 层内标准差取各层 std 的加权平均；均值差与离散度差共用同一尺度。
        within = _pooled_std([s[f]['std'] for s in layers], weights) if layers else 0.0
        h = max(within, spread * 0.05, 1e-9)
        out[f] = (h, h)
    return out


def distance(a, b, scale):
    if not a['n'] or not b['n']:
        return None
    total = 0.0
    for f in FEATURES:
        dm = (a[f]['mean'] - b[f]['mean']) / scale[f][0]
        ds = (a[f]['std'] - b[f]['std']) / scale[f][1]
        total += dm * dm + (STD_WEIGHT * ds) ** 2
    return math.sqrt(total)


def _cost(d):
    return NO_DATA_COST if d is None else d


def validate_anchors(left, right, anchors):
    """锚点须严格递增；返回矛盾说明（为空表示一致）。"""
    errors = []
    seen_left, seen_right = set(), set()
    for i, j in anchors:
        if i in seen_left or j in seen_right:
            errors.append('同一层被重复指定为锚点')
        seen_left.add(i)
        seen_right.add(j)
        if not (0 <= i < len(left) and 0 <= j < len(right)):
            errors.append('锚点引用了不在本对钻孔中的层段')
    ordered = sorted(anchors)
    for (i1, j1), (i2, j2) in zip(ordered, ordered[1:]):
        if not (i1 < i2 and j1 < j2):
            errors.append(f'锚点次序矛盾：左孔第{i1 + 1}层与右孔第{j2 + 1}层的先后关系交叉')
    return errors


def _segment(left, right, i0, j0, i1, j1, scale):
    """Needleman-Wunsch：层间匹配或单侧尖灭；区间为左闭右开。"""
    n, m = i1 - i0, j1 - j0
    inf = float('inf')
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for a in range(n + 1):
        for b in range(m + 1):
            if a == 0 and b == 0:
                continue
            best, how = inf, None
            if a and b:
                d = _cost(distance(left[i0 + a - 1], right[j0 + b - 1], scale))
                if dp[a - 1][b - 1] + d < best - 1e-12:
                    best, how = dp[a - 1][b - 1] + d, ('match', a - 1, b - 1)
            if a and dp[a - 1][b] + GAP_PENALTY < best - 1e-12:
                best, how = dp[a - 1][b] + GAP_PENALTY, ('left_only', a - 1, None)
            if b and dp[a][b - 1] + GAP_PENALTY < best - 1e-12:
                best, how = dp[a][b - 1] + GAP_PENALTY, ('right_only', None, b - 1)
            dp[a][b], back[a][b] = best, how
    out, a, b = [], n, m
    while a or b:
        kind, da, db = back[a][b]
        out.append((kind, i0 + da if da is not None else None, j0 + db if db is not None else None))
        a -= 1 if da is not None else 0
        b -= 1 if db is not None else 0
    return list(reversed(out))


def align(left, right, anchors, scale):
    """锚点固定，其余层分段补全；返回 (kind, left_idx, right_idx, origin)。"""
    out = []
    li = ri = 0
    for ai, aj in sorted(anchors):
        out += [(k, i, j, 'inferred') for k, i, j in _segment(left, right, li, ri, ai, aj, scale)]
        out.append(('match', ai, aj, 'anchor'))
        li, ri = ai + 1, aj + 1
    out += [(k, i, j, 'inferred') for k, i, j in
            _segment(left, right, li, ri, len(left), len(right), scale)]
    return out


def _nearest(layer, others, scale, exclude=()):
    ds = [distance(layer, o, scale) for k, o in enumerate(others) if k not in exclude]
    ds = sorted(d for d in ds if d is not None)
    return ds


def evaluate(left, right, aligned, scale, anchor_notes):
    fixed = {i: j for kind, i, j, origin in aligned if origin == 'anchor' and kind == 'match'}
    fixed_right = {j: i for i, j in fixed.items()}
    links = []
    for kind, i, j, origin in aligned:
        basis = {'parameters': PARAMETERS}
        reasons = []
        status = 'verified'
        if kind == 'match':
            a, b = left[i], right[j]
            d = distance(a, b, scale)
            blocked = {k for k, owner in fixed_right.items() if owner != i}
            alts = _nearest(a, right, scale, blocked | {j})
            alt = alts[0] if alts else None
            margin = round(alt - d, 6) if (alt is not None and d is not None) else None
            basis.update(distance=None if d is None else round(d, 6),
                         alternate_distance=None if alt is None else round(alt, 6),
                         margin=margin, left=a, right=b)
            if a['has_gap'] or b['has_gap']:
                reasons.append('层内缺芯，缺少连续物性，须现场核实')
            if not a['n'] or not b['n']:
                reasons.append('层内无实测物性点，无法计算分布')
            if origin == 'anchor':
                basis['anchor_note'] = anchor_notes.get((i, j), '')
            else:
                if d is not None and d > MAX_MATCH_DISTANCE:
                    reasons.append('三项物性差异过大，对层依据不足')
                if margin is not None and margin < AMBIGUITY_MARGIN:
                    reasons.append('邻孔存在多个物性相近层，对层不唯一')
        elif kind == 'left_only':
            a = left[i]
            blocked = set(fixed_right)
            alts = _nearest(a, right, scale, blocked)
            nearest = alts[0] if alts else None
            basis.update(left=a, right=None, nearest_distance=None if nearest is None else round(nearest, 6))
            if a['has_gap']:
                reasons.append('层内缺芯，尖灭判断须现场核实')
            if not a['n']:
                reasons.append('层内无实测物性点，无法判断尖灭')
            if origin != 'anchor' and nearest is not None and nearest < PINCH_AMBIGUITY:
                reasons.append('邻孔存在物性相近层，尖灭判断不唯一')
        else:
            b = right[j]
            blocked = set(fixed)
            alts = _nearest(b, left, scale, blocked)
            nearest = alts[0] if alts else None
            basis.update(left=None, right=b, nearest_distance=None if nearest is None else round(nearest, 6))
            if b['has_gap']:
                reasons.append('层内缺芯，尖灭判断须现场核实')
            if not b['n']:
                reasons.append('层内无实测物性点，无法判断尖灭')
            if origin != 'anchor' and nearest is not None and nearest < PINCH_AMBIGUITY:
                reasons.append('邻孔存在物性相近层，尖灭判断不唯一')
        if reasons:
            status = 'pending'
        basis['reasons'] = reasons
        if kind == 'match':
            links.append({'kind': 'match', 'origin': origin, 'status': status,
                          'left_stratum_id': left[i]['stratum_id'],
                          'right_stratum_id': right[j]['stratum_id'],
                          'reason': '；'.join(reasons), 'basis': basis})
        elif kind == 'left_only':
            links.append({'kind': 'left_only', 'origin': origin, 'status': status,
                          'left_stratum_id': left[i]['stratum_id'], 'right_stratum_id': None,
                          'reason': '；'.join(reasons), 'basis': basis})
        else:
            links.append({'kind': 'right_only', 'origin': origin, 'status': status,
                          'left_stratum_id': None, 'right_stratum_id': right[j]['stratum_id'],
                          'reason': '；'.join(reasons), 'basis': basis})
    return links


def correlate(left, right, anchors, anchor_notes=None):
    """left/right 为 layer_statistics 的结果；anchors 为左/右层位序号对。"""
    anchor_notes = anchor_notes or {}
    errors = validate_anchors(left, right, anchors)
    if errors:
        raise ValueError('；'.join(errors))
    scale = scales(left, right)
    aligned = align(left, right, anchors, scale)
    return evaluate(left, right, aligned, scale, anchor_notes)
