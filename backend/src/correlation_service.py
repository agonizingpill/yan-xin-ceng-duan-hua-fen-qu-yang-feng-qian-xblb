import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from .models import Borehole, Interpretation, MissingInterval, Reading, Stratum, CorrelationProfile
from .common import get, pack, audit, now
from . import correlation_model as cm


class AnchorConflict(Exception):
    """锚点互相矛盾；剖面退回草案并留下原因。"""


class PublishBlocked(Exception):
    """发布时源层已撤回或更换；剖面留待复核，已发布快照不动。"""


def _confirmed(s, borehole_id):
    return s.scalar(select(Interpretation).where(
        Interpretation.borehole_id == borehole_id,
        Interpretation.state == 'confirmed'))


def _strata(s, interpretation_id):
    return [pack(x) for x in s.scalars(select(Stratum).where(
        Stratum.interpretation_id == interpretation_id).order_by(Stratum.start_m))]


def _readings(s, borehole_id):
    return [pack(x) for x in s.scalars(select(Reading).where(
        Reading.borehole_id == borehole_id).order_by(Reading.depth_m))]


def _missing(s, borehole_id):
    return [pack(x) for x in s.scalars(select(MissingInterval).where(
        MissingInterval.borehole_id == borehole_id))]


def side_inputs(s, borehole_id, interpretation_id):
    strata = _strata(s, interpretation_id)
    stats = cm.layer_statistics(strata, _readings(s, borehole_id), _missing(s, borehole_id))
    return stats


def _index_by_stratum(left_stats, right_stats, anchors):
    left_index = {v['stratum_id']: k for k, v in enumerate(left_stats)}
    right_index = {v['stratum_id']: k for k, v in enumerate(right_stats)}
    out, notes = [], {}
    for a in anchors or []:
        lsid, rsid = a.get('left_stratum_id'), a.get('right_stratum_id')
        if lsid not in left_index or rsid not in right_index:
            raise HTTPException(409, '锚点引用了不属于本孔已确认解释的层段')
        i, j = left_index[lsid], right_index[rsid]
        if any(i == x[0] or j == x[1] for x in out):
            raise HTTPException(409, '同一层被重复指定为锚点')
        out.append((i, j))
        notes[(i, j)] = (a.get('note') or '').strip()
    errors = cm.validate_anchors(left_stats, right_stats, out)
    if errors:
        raise HTTPException(409, '；'.join(errors))
    return out, notes


def _digest(left_stats, right_stats, anchors):
    raw = json.dumps({'left': left_stats, 'right': right_stats,
                      'anchors': sorted(anchors), 'params': cm.PARAMETERS},
                     sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def compute(s, profile, persist=True):
    li = get(s, Interpretation, profile.left_interpretation_id)
    ri = get(s, Interpretation, profile.right_interpretation_id)
    left_stats = side_inputs(s, profile.left_borehole_id, li.id)
    right_stats = side_inputs(s, profile.right_borehole_id, ri.id)
    anchors, notes = _index_by_stratum(left_stats, right_stats, profile.anchors)
    # 先固定现场认定的对层，再推算其余层：没有锚点就不给出任何对层结论。
    links = cm.correlate(left_stats, right_stats, anchors, notes) if anchors else []
    result = {
        'source_digest': _digest(left_stats, right_stats, anchors),
        'parameters': cm.PARAMETERS,
        'anchored': bool(anchors),
        'left': {'borehole_id': profile.left_borehole_id,
                 'code': get(s, Borehole, profile.left_borehole_id).code,
                 'interpretation_id': li.id, 'interpretation_state': li.state,
                 'statistics': left_stats},
        'right': {'borehole_id': profile.right_borehole_id,
                  'code': get(s, Borehole, profile.right_borehole_id).code,
                  'interpretation_id': ri.id, 'interpretation_state': ri.state,
                  'statistics': right_stats},
        'anchors': [{'left_stratum_id': left_stats[i]['stratum_id'],
                     'right_stratum_id': right_stats[j]['stratum_id'],
                     'note': notes.get((i, j), '')} for i, j in anchors],
        'links': links,
        'pending': [v for v in links if v['status'] == 'pending'],
    }
    if persist:
        profile.result = result
        profile.error = ''
    return result


def create(s, p, u):
    if p.left_borehole_id == p.right_borehole_id:
        raise HTTPException(409, '相邻钻孔才能对比，左右孔不能是同一孔')
    left = get(s, Borehole, p.left_borehole_id)
    right = get(s, Borehole, p.right_borehole_id)
    li, ri = _confirmed(s, left.id), _confirmed(s, right.id)
    if not li or not ri:
        raise HTTPException(409, '两孔都须先有主管确认的层段解释，才能对比剖面')
    live_draft = s.scalar(select(CorrelationProfile.id).where(
        ((CorrelationProfile.left_borehole_id == left.id) & (CorrelationProfile.right_borehole_id == right.id))
        | ((CorrelationProfile.left_borehole_id == right.id) & (CorrelationProfile.right_borehole_id == left.id)),
        CorrelationProfile.state == 'draft'))
    if live_draft:
        raise HTTPException(409, '该孔对已有待发布草稿，请继续原剖面；源层已撤回的草稿已作废，可另建新草案')
    x = CorrelationProfile(left_borehole_id=left.id, right_borehole_id=right.id,
                           left_interpretation_id=li.id, right_interpretation_id=ri.id,
                           state='draft', note=p.note, anchors=[], created_by=u['email'])
    s.add(x)
    s.flush()
    compute(s, x)
    audit(s, u, '新建对比剖面 %s ↔ %s' % (left.code, right.code))
    return pack(x)


def update_anchors(s, id, p, u):
    x = get(s, CorrelationProfile, id, True)
    if x.state != 'draft':
        raise HTTPException(409, '仅草案剖面可调整锚点；已发布或待复核剖面须另建新版本')
    for hid in sorted({x.left_borehole_id, x.right_borehole_id}):
        get(s, Borehole, hid)
    li = get(s, Interpretation, x.left_interpretation_id)
    ri = get(s, Interpretation, x.right_interpretation_id)
    if li.state != 'confirmed' or ri.state != 'confirmed':
        x.state = 'pending_review'
        x.error = '源层解释已撤回，剖面留待复核，须重新绑定已确认解释'
        audit(s, u, '源层已撤回，剖面留待复核 %s' % x.id)
        raise AnchorConflict(x.error)
    anchors = [a.model_dump() for a in p.anchors]
    left_stats = side_inputs(s, x.left_borehole_id, li.id)
    right_stats = side_inputs(s, x.right_borehole_id, ri.id)
    try:
        _index_by_stratum(left_stats, right_stats, anchors)
    except HTTPException as e:
        # 锚点矛盾：不写入任何锚点，剖面退回草案，原因随草案保留供复核。
        x.state = 'draft'
        x.error = '锚点互相矛盾，剖面已退回草案：' + str(e.detail)
        audit(s, u, '锚点矛盾，剖面退回草案 %s' % x.id)
        raise AnchorConflict(x.error)
    if p.note is not None:
        x.note = p.note
    x.anchors = anchors
    x.state = 'draft'
    x.error = ''
    compute(s, x)
    audit(s, u, '更新对层锚点 %s' % x.id)
    return pack(x)


def publish(s, id, p, u):
    ref = get(s, CorrelationProfile, id)
    # 固定加锁顺序：孔 → 解释 → 剖面，与“撤回解释”同序，避免发布与撤回互相死锁。
    for hid in sorted({ref.left_borehole_id, ref.right_borehole_id}):
        get(s, Borehole, hid, True)
    preview = get(s, CorrelationProfile, id)
    interp_ids = sorted({preview.left_interpretation_id, preview.right_interpretation_id})
    interps = {i: get(s, Interpretation, i, True) for i in interp_ids}
    x = get(s, CorrelationProfile, id, True)
    if x.state == 'published':
        raise HTTPException(409, '该剖面已发布，不能重复发布')
    if x.state == 'pending_review':
        raise HTTPException(409, '剖面留待复核，请先按当前已确认解释重新绑定再发布')
    if x.state != 'draft':
        raise HTTPException(409, '仅草案剖面可发布')
    if {x.left_interpretation_id, x.right_interpretation_id} != set(interp_ids):
        raise HTTPException(409, '剖面源层绑定已变化，请重新载入后再发布')
    li, ri = interps[x.left_interpretation_id], interps[x.right_interpretation_id]
    current_left = _confirmed(s, x.left_borehole_id)
    current_right = _confirmed(s, x.right_borehole_id)
    stale = (li.state != 'confirmed' or ri.state != 'confirmed'
             or not current_left or current_left.id != li.id
             or not current_right or current_right.id != ri.id)
    if stale:
        x.state = 'pending_review'
        x.error = '发布时源层解释已撤回或已更换，剖面留待复核'
        audit(s, u, '剖面发布受阻，留待复核 %s' % x.id)
        raise PublishBlocked(x.error)
    if not x.anchors:
        raise HTTPException(409, '发布前须先固定至少一组现场认定对层')
    result = compute(s, x, persist=False)
    version = _next_version(s, x)
    x.result = result
    x.snapshot = {
        'version': version,
        'profile_id': x.id,
        'published_by': u['email'],
        'published_at': now(),
        'note': (p.note or x.note or ''),
        'left_borehole': pack(get(s, Borehole, x.left_borehole_id)),
        'right_borehole': pack(get(s, Borehole, x.right_borehole_id)),
        'left_interpretation': pack(li),
        'right_interpretation': pack(ri),
        'left_strata': _strata(s, li.id),
        'right_strata': _strata(s, ri.id),
        'result': result,
    }
    x.version = version
    x.state = 'published'
    x.published_by = u['email']
    x.published_at = now()
    x.error = ''
    audit(s, u, '发布对比剖面 %s' % version)
    return pack(x)


def rebind(s, id, u):
    """源层撤回后留待复核的草稿：重新绑定两孔当前已确认解释，锚点清空待重新认定。"""
    x = get(s, CorrelationProfile, id, True)
    if x.state != 'pending_review' or x.version is not None:
        raise HTTPException(409, '仅尚未发布的待复核草稿可重新绑定；已发布版本须另建新剖面')
    li, ri = _confirmed(s, x.left_borehole_id), _confirmed(s, x.right_borehole_id)
    if not li or not ri:
        raise HTTPException(409, '两孔都须先有主管确认的层段解释，才能重新绑定')
    x.left_interpretation_id, x.right_interpretation_id = li.id, ri.id
    x.anchors, x.state, x.error = [], 'draft', ''
    compute(s, x)
    audit(s, u, '剖面草稿重新绑定已确认源层 %s' % x.id)
    return pack(x)


def _next_version(s, x):
    # 同一对孔（不分左右方向）共用一个版本序列，避免留档里出现两个 CP-01。
    a, b = sorted((x.left_borehole_id, x.right_borehole_id))
    used = s.scalars(select(CorrelationProfile.version).where(
        ((CorrelationProfile.left_borehole_id == a) & (CorrelationProfile.right_borehole_id == b))
        | ((CorrelationProfile.left_borehole_id == b) & (CorrelationProfile.right_borehole_id == a)),
        CorrelationProfile.version.isnot(None))).all()
    return 'CP-%02d' % (len(used) + 1)


def mark_source_withdrawn(s, interpretation_id, u):
    """撤回解释时调用：该孔相关剖面一律转“留待复核”，已发布快照原样保留。

    撤回先办成，剖面只做状态留痕；发布与撤回并发时同样落到 pending_review。
    """
    rows = s.scalars(select(CorrelationProfile).where(
        CorrelationProfile.state.in_(['published', 'draft']),
        (CorrelationProfile.left_interpretation_id == interpretation_id)
        | (CorrelationProfile.right_interpretation_id == interpretation_id))
        .with_for_update()).all()
    for x in rows:
        x.state = 'pending_review'
        if x.version:
            x.error = '源层解释已撤回，剖面留待复核；已发布快照保留，可回看当时源层与对层依据'
            audit(s, u, '剖面留待复核 %s（源层撤回）' % x.version)
        else:
            x.error = '源层解释已撤回，剖面留待复核，须重新绑定已确认解释'
            audit(s, u, '剖面草稿转待复核 %s（源层撤回）' % x.id)
    return [pack(x) for x in rows]
