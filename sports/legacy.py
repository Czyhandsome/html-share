"""Lossless-layout adapters for native Swiss and explicitly historical pages.

No JavaScript is evaluated by the builder. JSON values become script-safe literals;
HTML text nodes are escaped separately. Templates keep original CSS/interaction code.
"""
from pathlib import Path
import html
import json
import re

KINDS = {'worlds-swiss', 'prediction-archive', 'doubles-archive'}
TOKEN = re.compile(r'\{\{(js|string|text):([A-Za-z0-9_]+)\}\}')


def _path(root, name, directory):
    if not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Unsafe path')
    base = (root / directory).resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(base) or candidate == base:
        raise ValueError(f'Path must stay in {directory}')
    return candidate


def _js(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def _series(slots, scores, games, best):
    if len(slots) != 2 or len(scores) != 2 or any(type(n) is not int or n < 0 for n in scores):
        raise ValueError('Invalid series slots/scores')
    if best not in (1, 3, 5, 7) or max(scores) > (best + 1) // 2 or scores[0] == scores[1]:
        raise ValueError('Invalid series score/best-of')
    if games is not None and (len(games) != sum(scores) or
            any(g not in slots for g in games) or [games.count(s) for s in slots] != scores):
        raise ValueError('Game winners disagree with series score')


def validate_record(record, root):
    if record.get('schema_version') != 1 or record.get('kind') not in KINDS:
        raise ValueError('Unsupported legacy schema/kind')
    _path(root, record['output'], 'docs')
    _path(root, record['template'], 'sports/templates')
    if not record['output'].endswith('.html'):
        raise ValueError('Legacy output must be HTML')
    data = record['data']
    if not isinstance(record['content'], dict) or any(not isinstance(t, str) for t in record['content'].values()):
        raise ValueError('Content must contain text strings')
    if record['kind'] != 'worlds-swiss':
        if record['maintenance']['mode'] != 'historical-archive':
            raise ValueError('July records must remain explicitly historical archives')
        if record['kind'] == 'prediction-archive':
            if not {'blocks', 'qf', 'sf', 'finals', 'champ'} <= data.keys():
                raise ValueError('Incomplete prediction')
        else:
            for event in data['DATA'].values():
                for m in event['matches']:
                    if m['status'] not in ('done', 'pending') or m['winner'] not in (None, 0, 1):
                        raise ValueError('Invalid archived status/winner')
        return
    teams = data['teams']
    resolved = {}
    for m in data['ko']:
        if m['id'] in resolved:
            raise ValueError('Duplicate knockout ID')
        slots = [s if s in teams else resolved.get(s) for s in m['slots']]
        if len(slots) != 2 or not all(slots):
            raise ValueError('Unknown team or unresolved knockout feeder')
        scores = m.get('scores')
        if scores is not None:
            _series(slots, scores, m.get('gameWinners'), m['best'])
        resolved[m['id']] = slots[scores.index(max(scores))] if scores and max(scores) == (m['best']+1)//2 else None
    history_ids = set()
    for stage in ('swiss', 'playin'):
        for day, round_number, matches in data[stage+'Days']:
            for i, (hour, a, b, x, y) in enumerate(matches):
                if a not in teams or b not in teams or a == b:
                    raise ValueError('Unknown/duplicate history team')
                match_id = stage+str(day)+'-'+str(i)
                history_ids.add(match_id)
                _series([a, b], [x, y], data['historyGameWinners'].get(match_id), 2*max(x,y)-1 if stage == 'swiss' else 5)
    if set(data['historyGameWinners']) - history_ids:
        raise ValueError('Unknown history game-winner record')


def render_record(record, root: Path) -> str:
    """Validate and render only. Caller owns writing the approved docs output."""
    root = Path(root)
    validate_record(record, root)
    template = _path(root, record['template'], 'sports/templates').read_text(encoding='utf-8')
    def replace(match):
        mode, key = match.groups()
        value = record['data' if mode == 'js' else 'content'][key]
        return html.escape(value, quote=False) if mode == 'text' else _js(value)
    return TOKEN.sub(replace, template)
