#!/usr/bin/env python3
"""Data-first tournament compiler. Python 3.11+, standard library (YAML optional)."""
import argparse
import copy
from datetime import date, datetime
from fractions import Fraction
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

if __package__:
    from .board import render
else:
    from board import render

class ValidationError(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise ValidationError(message)

def timestamp(value):
    require(isinstance(value, str), 'timestamp must be an ISO-8601 string')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValidationError('invalid timestamp: ' + value) from exc
    require(result.tzinfo is not None, 'timestamp needs an explicit UTC offset: ' + value)
    return result

def fields(obj, allowed, where):
    require(isinstance(obj, dict), where + ': expected object')
    require(not (set(obj) - set(allowed.split())), where + ': unknown fields ' + str(sorted(set(obj) - set(allowed.split()))))

def integer(value, low=0):
    return type(value) is int and value >= low

def safe_url(value):
    require(isinstance(value, str), 'source URL must be a string')
    u = urlsplit(value)
    require(u.scheme in ('http', 'https') and bool(u.netloc) and u.username is None and u.password is None,
            'source URL must be absolute HTTP(S) without credentials')
    return value

def unique(items, kind):
    require(isinstance(items, list), kind + ' must be a list')
    result = {}
    for item in items:
        require(isinstance(item, dict), kind + ' entries must be objects')
        ident = item.get('id')
        require(isinstance(ident, str) and ident and ident not in result,
                kind + ': missing or duplicate id: ' + str(ident))
        result[ident] = item
    return result

def game_winner(game, rule, partial=False):
    require(isinstance(game, list) and len(game) == 2 and all(integer(p) for p in game),
            'game must contain two nonnegative integer points')
    a, b = game
    target, margin, cap = rule['points'], rule['win_by'], rule.get('cap')
    hi, lo = max(a, b), min(a, b)
    if cap is not None:
        require(hi <= cap, 'game exceeds point cap')
    ended = hi >= target and (hi - lo >= margin or (cap is not None and hi == cap and hi > lo))
    require(not (margin == 1 and lo >= target), 'points continued after a player won')
    if partial:
        require(cap is None or hi < cap, 'live game reached point cap')
        require(not ended, 'in_progress_game is already finished')
        return None
    require(ended and a != b, 'game is not a legal final score')
    # No points may be played after the first winning point.
    previous_hi = hi - 1
    require(not (previous_hi >= target and (previous_hi - lo >= margin or
                (cap is not None and previous_hi == cap and previous_hi > lo))),
            'points continued after the game was won')
    return 0 if a > b else 1

TERMINAL = {'completed', 'retired', 'walkover', 'bye', 'cancelled'}
COMPETITIVE = {'completed', 'retired', 'walkover'}
STATUSES = TERMINAL | {'scheduled', 'live'}

class Compiler:
    def __init__(self, data):
        self.data = copy.deepcopy(data)
        data = self.data
        fields(data, 'schema_version event entries sources rules draws groups matches', 'root')
        require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'unsupported schema_version')
        self.event = data['event']
        fields(self.event, 'name snapshot_at timezone venue_timezone back_link', 'event')
        require(isinstance(self.event.get('name'), str) and self.event['name'], 'event.name required')
        self.snapshot = timestamp(self.event['snapshot_at'])
        for field in ('timezone', 'venue_timezone'):
            try:
                ZoneInfo(self.event[field])
            except Exception as exc:
                raise ValidationError('invalid ' + field) from exc
        back_link = self.event.get('back_link', 'index.html')
        require(isinstance(back_link, str) and re.fullmatch(r'(?:[\w.-]+/)*[\w.-]+\.html', back_link, re.ASCII),
                'back_link must be a relative HTML path')
        self.entries = unique(data['entries'], 'entries')
        for e in self.entries.values():
            fields(e, 'id name team', 'entry')
            require(isinstance(e.get('name'), str) and e['name'], 'entry needs name')
            require(isinstance(e.get('team'), str), 'entry needs team code (empty allowed)')
        self.sources = unique(data.get('sources', []), 'sources')
        for s in self.sources.values():
            fields(s, 'id url label kind family', 'source')
            safe_url(s['url'])
            require(s.get('kind') in ('official', 'independent'), 'invalid source kind')
            require(isinstance(s.get('family'), str) and s['family'], 'source family required')
        self.rules = data['rules']
        require(isinstance(self.rules, dict) and self.rules, 'rules required')
        for r in self.rules.values():
            fields(r, 'best_of points win_by cap', 'rule')
            require(integer(r.get('best_of'), 1) and r['best_of'] % 2 == 1, 'best_of must be positive odd')
            require(integer(r.get('points'), 1) and integer(r.get('win_by'), 1), 'invalid point rule')
            require(r.get('cap') is None or integer(r['cap'], r['points']), 'invalid cap')
        self.draws = unique(data.get('draws', [{'id': 'main', 'name': '赛事'}]), 'draws')
        for d in self.draws.values():
            fields(d, 'id name', 'draw')
            require(isinstance(d.get('name'), str), 'draw name required')
        self.groups = unique(data.get('groups', []), 'groups')
        self.matches = unique(data['matches'], 'matches')
        self.cache, self.group_cache, self.visiting = {}, {}, set()
        self.audit = []
        self.validate_groups()

    def evidence(self, verification, where):
        require(isinstance(verification, dict), where + ': terminal result needs verification')
        fields(verification, 'source_ids verified_at', where + ' verification')
        ids = verification.get('source_ids', [])
        require(isinstance(ids, list) and len(ids) == len(set(ids)) and ids, where + ': sources required')
        require(all(s in self.sources for s in ids), where + ': unknown source')
        t = timestamp(verification['verified_at'])
        require(t <= self.snapshot, where + ': verification is after snapshot')
        sources = [self.sources[s] for s in ids]
        require(any(s['kind'] == 'official' for s in sources) or
                len({s['family'] for s in sources}) >= 2,
                where + ': needs official source or two independent families')
        return ids

    def validate_groups(self):
        grouped = set()
        for g in self.groups.values():
            fields(g, 'id name draw entries ranking adjudication', 'group')
            require(g.get('draw', 'main') in self.draws, 'unknown group draw')
            ids = g.get('entries', [])
            require(len(ids) >= 2 and len(set(ids)) == len(ids) and all(x in self.entries for x in ids),
                    g['id'] + ': invalid group entries')
            require(g.get('ranking') in (['wins', 'game_ratio', 'point_ratio'], ['wins']),
                    'supported ranking chains: wins or wins/game_ratio/point_ratio')
            # Nonstandard / discipline-specific ties require an explicit official adjudication.
            pairs = set()
            for m in self.matches.values():
                if m.get('group') != g['id']:
                    continue
                require(m.get('draw', 'main') == g.get('draw', 'main'), 'group and match draw mismatch')
                grouped.add(m['id'])
                slots = m.get('slots', [])
                require(len(slots) == 2 and all(isinstance(x, dict) and set(x) == {'entry'} and x['entry'] in ids for x in slots),
                        'group fixtures need two direct entries from that group')
                pair = frozenset(x['entry'] for x in slots)
                require(len(pair) == 2 and pair not in pairs, 'group contains duplicate/self pairing')
                pairs.add(pair)
            require(len(pairs) == len(ids) * (len(ids) - 1) // 2,
                    g['id'] + ': single round-robin requires every pairing exactly once')
        for m in self.matches.values():
            require(m.get('group') is None or m['id'] in grouped, 'unknown group reference')

    def slot(self, s):
        require(isinstance(s, dict) and len(s) == 1, 'slot must have exactly one selector')
        kind, value = next(iter(s.items()))
        if kind == 'entry':
            require(value in self.entries, 'unknown entry: ' + str(value))
            return value
        if kind == 'winner':
            require(value in self.matches, 'unknown feeder: ' + str(value))
            require(not self.matches[value].get('group'), 'use group_rank instead of group match winner')
            return self.match(value)['winner']
        if kind == 'group_rank':
            require(isinstance(value, list) and len(value) == 2 and value[0] in self.groups,
                    'group_rank must be [group_id, one-based rank]')
            require(integer(value[1], 1) and value[1] <= len(self.groups[value[0]]['entries']), 'invalid group rank')
            table = self.group(value[0])
            return table['order'][value[1] - 1] if table['final'] else None
        if kind == 'tbd':
            require(isinstance(value, str) and value, 'TBD label required')
            return None
        if kind == 'bye':
            require(value is True, 'bye selector must be true')
            return None
        raise ValidationError('unknown slot selector: ' + kind)

    def match(self, ident):
        if ident in self.cache:
            return self.cache[ident]
        require(ident not in self.visiting, 'cyclic advancement: ' + ident)
        self.visiting.add(ident)
        m = self.matches[ident]
        fields(m, 'id group draw round slots rule status scheduled_at schedule_verification completed_at completed_date result_for games in_progress_game winner reason blocker verification', ident)
        require(m.get('draw', 'main') in self.draws, ident + ': unknown draw')
        for slot in m.get('slots', []):
            if isinstance(slot, dict) and 'winner' in slot and slot['winner'] in self.matches:
                require(self.matches[slot['winner']].get('draw', 'main') == m.get('draw', 'main'), 'cross-draw winner reference')
            if isinstance(slot, dict) and 'group_rank' in slot and isinstance(slot['group_rank'], list) and slot['group_rank'] and slot['group_rank'][0] in self.groups:
                require(self.groups[slot['group_rank'][0]].get('draw', 'main') == m.get('draw', 'main'), 'cross-draw group reference')
        status = m.get('status')
        require(status in STATUSES, ident + ': invalid status')
        require(m.get('rule') in self.rules, ident + ': unknown rule')
        require(isinstance(m.get('round'), str), ident + ': round required')
        require(isinstance(m.get('slots'), list) and len(m['slots']) == 2, ident + ': exactly two slots required')
        players = [self.slot(s) for s in m['slots']]
        require(not (players[0] is not None and players[0] == players[1]), ident + ': self match')
        scheduled = timestamp(m['scheduled_at']) if m.get('scheduled_at') else None
        schedule_source_ids = []
        if 'schedule_verification' in m:
            require(scheduled is not None, ident + ': schedule evidence needs a scheduled time')
            schedule_source_ids = self.evidence(m['schedule_verification'], ident + ' schedule')
        if scheduled and scheduled < self.snapshot and status not in TERMINAL:
            require(isinstance(m.get('blocker'), str) and m['blocker'].strip(), ident + ': overdue match needs blocker')
            self.audit.append({'match': ident, 'issue': 'overdue_unresolved', 'reason': m['blocker']})
        if m.get('blocker'):
            require(isinstance(m['blocker'], str), 'blocker must be text')
        verification_ids = []
        if status in TERMINAL or m.get('verification') is not None:
            verification_ids = self.evidence(m.get('verification'), ident)
        if m.get('completed_at'):
            completed_at = timestamp(m['completed_at'])
            require(status in TERMINAL and completed_at <= self.snapshot, ident + ': invalid completion timestamp')
            require(completed_at <= timestamp(m['verification']['verified_at']), ident + ': verified before completion')
        if 'completed_date' in m:
            value = m['completed_date']
            require(status in TERMINAL and 'completed_at' not in m and isinstance(value, str) and
                    re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), ident + ': expected a date-only terminal result')
            verified = timestamp(m['verification']['verified_at']).astimezone(ZoneInfo(self.event['timezone']))
            require(date.fromisoformat(value) <= verified.date(), ident + ': verified before completion date')
        games = m.get('games', [])
        require(isinstance(games, list), ident + ': games must be array')
        rule = self.rules[m['rule']]
        target = rule['best_of'] // 2 + 1
        score = [0, 0]
        for game in games:
            require(max(score) < target, ident + ': game after match clinched')
            score[game_winner(game, rule)] += 1
        declared = m.get('winner')
        require('score' not in m and 'players' not in m, ident + ': score/players are derived, do not input them')
        winner = None
        if status in COMPETITIVE | {'live'}:
            require(all(players), ident + ': participants unresolved')
            require(m.get('result_for') == players, ident + ': result_for must bind the exact resolved participants in order')
        else:
            require('result_for' not in m, ident + ': no result_for allowed before play or for bye/cancelled')
        if status == 'completed':
            require(max(score) == target, ident + ': incomplete match score')
            winner = players[0 if score[0] > score[1] else 1]
            require(declared is None or declared == winner, ident + ': declared winner contradicts score')
            require('in_progress_game' not in m, ident + ': completed match has live game')
        elif status in ('retired', 'walkover'):
            require(declared in players and declared is not None, ident + ': explicit winner required')
            require(isinstance(m.get('reason'), str) and m['reason'].strip(), ident + ': reason required')
            require(max(score) < target, ident + ': use completed for a fully won match')
            if status == 'walkover':
                require(not games and 'in_progress_game' not in m, ident + ': walkover cannot contain played games')
            winner = declared
        elif status == 'bye':
            require(sum(s == {'bye': True} for s in m['slots']) == 1 and sum(x is not None for x in players) == 1,
                    ident + ': bye needs one entry and one explicit bye slot')
            require(not games and 'in_progress_game' not in m, ident + ': bye cannot have score')
            winner = next(p for p in players if p)
            require(declared is None or declared == winner, ident + ': bye winner mismatch')
        else:
            require(declared is None, ident + ': unfinished/cancelled match cannot advance a winner')
            require(max(score) < target, ident + ': terminal score needs completed status')
            if status in ('scheduled', 'cancelled'):
                require(not games and 'in_progress_game' not in m, ident + ': scheduled/cancelled match cannot have scores')
        if 'in_progress_game' in m:
            require(status in ('live', 'retired'), ident + ': live game invalid for status')
            game_winner(m['in_progress_game'], rule, partial=True)
        if any('bye' in s for s in m['slots']):
            require(status == 'bye', ident + ': explicit bye must use bye status')
        result = {**m, 'players': players, 'winner': winner,
                  'score': score if status in ('completed', 'live', 'retired') else None,
                  'games': games, 'verified_source_ids': verification_ids, 'schedule_source_ids': schedule_source_ids}
        self.cache[ident] = result
        self.visiting.remove(ident)
        return result

    def group(self, ident):
        if ident in self.group_cache:
            return self.group_cache[ident]
        g = self.groups[ident]
        rows = {e: {'entry': e, 'played': 0, 'wins': 0, 'games_for': 0, 'games_against': 0,
                    'points_for': 0, 'points_against': 0} for e in g['entries']}
        matches = [self.match(m['id']) for m in self.matches.values() if m.get('group') == ident]
        all_terminal = all(m['status'] in TERMINAL for m in matches)
        final = all(m['status'] in COMPETITIVE for m in matches)
        exceptional = any(m['status'] in ('retired', 'walkover', 'cancelled') for m in matches)
        for m in matches:
            if m['status'] not in COMPETITIVE:
                continue
            for i, e in enumerate(m['players']):
                row = rows[e]
                row['played'] += 1
                row['wins'] += int(m['winner'] == e)
                row['games_for'] += sum(game_winner(x, self.rules[m['rule']]) == i for x in m['games'])
                row['games_against'] += sum(game_winner(x, self.rules[m['rule']]) != i for x in m['games'])
                row['points_for'] += sum(x[i] for x in m['games'])
                row['points_against'] += sum(x[1-i] for x in m['games'])
        def ratio(a, b):
            return (1, Fraction(0)) if a > 0 and b == 0 else (0, Fraction(a, b or 1))
        def key(e):
            row = rows[e]
            values = {'wins': row['wins'], 'game_ratio': ratio(row['games_for'], row['games_against']),
                      'point_ratio': ratio(row['points_for'], row['points_against'])}
            return tuple(values[k] for k in g['ranking'])
        order = sorted(g['entries'], key=key, reverse=True)
        tied = len({key(e) for e in order}) < len(order)
        decision = g.get('adjudication')
        if decision:
            fields(decision, 'order reason verification', ident + ' adjudication')
            require(all_terminal, ident + ': cannot finalize group before every match is terminal')
            decision_sources = self.evidence(decision.get('verification'), ident + ' ranking')
            require(any(self.sources[x]['kind'] == 'official' for x in decision_sources), 'ranking adjudication requires an official source')
            require(isinstance(decision.get('reason'), str) and decision['reason'].strip(), 'ranking decision needs reason')
            require(isinstance(decision.get('order'), list) and len(decision['order']) == len(order) and
                    set(decision['order']) == set(order), 'ranking decision must include every entry exactly once')
            order = decision['order']
            final = True
        elif tied or exceptional:
            final = False
        result = {'id': ident, 'name': g.get('name', ident), 'order': order, 'rows': [rows[e] for e in order],
                  'final': final, 'reason': ('已核定' if final else '未决：比赛未结束、同分或特殊赛果需裁定'),
                  'adjudication': decision}
        self.group_cache[ident] = result
        return result

    def compile(self):
        for ident in self.matches:
            self.match(ident)
        for ident in self.groups:
            self.group(ident)
        # A winner/group place cannot be duplicated into two later knockout matches.
        consumed = set()
        direct = set()
        for m in self.matches.values():
            if m.get('group'):
                continue
            for s in m['slots']:
                if 'entry' in s:
                    token = (m.get('draw', 'main'), s['entry'])
                    require(token not in direct, 'entry seeded twice in knockout draw: ' + str(token))
                    direct.add(token)
                if 'winner' in s or 'group_rank' in s:
                    token = json.dumps(s, sort_keys=True)
                    require(token not in consumed, 'advancement slot consumed more than once: ' + token)
                    consumed.add(token)
        return {'schema_version': 1, 'event': self.event, 'entries': list(self.entries.values()),
                'sources': list(self.sources.values()), 'rules': self.rules, 'draws': list(self.draws.values()),
                'groups': list(self.group_cache.values()),
                'matches': [self.cache[k] for k in self.matches], 'audit': self.audit}

def compile_data(data):
    try:
        return Compiler(data).compile()
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValidationError('missing/invalid DSL field: ' + str(exc)) from exc

def load(path):
    text = Path(path).read_text(encoding='utf-8')
    def no_duplicates(pairs):
        d = {}
        for k, v in pairs:
            require(k not in d, 'duplicate object key: ' + k)
            d[k] = v
        return d
    if Path(path).suffix.lower() in ('.yaml', '.yml'):
        try:
            import yaml
        except ImportError as exc:
            raise ValidationError('YAML input needs PyYAML; JSON uses only the standard library') from exc
        class UniqueSafeLoader(yaml.SafeLoader):
            pass
        def mapping(loader, node):
            loader.flatten_mapping(node)
            return no_duplicates([(loader.construct_object(k), loader.construct_object(v)) for k, v in node.value])
        UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        return yaml.load(text, Loader=UniqueSafeLoader)
    def nonfinite(value):
        raise ValidationError('nonfinite JSON number: ' + value)
    return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=nonfinite)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('-o', '--output', help='self-contained HTML output')
    p.add_argument('--normalized', help='write derived audit/model JSON')
    args = p.parse_args()
    try:
        data = compile_data(load(args.input))
        if args.output:
            Path(args.output).write_text(render(data), encoding='utf-8')
        if args.normalized:
            Path(args.normalized).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'OK: {len(data["matches"])} matches; {len(data["audit"])} unresolved overdue entries')
    except (ValidationError, ValueError) as exc:
        p.exit(2, 'Validation failed: ' + str(exc) + '\n')

if __name__ == '__main__':
    main()
