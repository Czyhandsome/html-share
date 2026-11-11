"""Compile team ties without changing the individual bracket contract."""

import argparse
from datetime import date
from itertools import product
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .bracketkit import Compiler, ValidationError, fields, game_winner, integer, load, require, timestamp, unique
from .teams import team_codes, validate_entry_teams


MATCH_WINS = {'completed', 'retired', 'walkover'}
MATCH_STARTED = MATCH_WINS | {'live'}
FINAL_TIES = {'completed', 'walkover', 'bye'}
POSITIONS = set(range(1, 6))


def text(value):
    return isinstance(value, str) and bool(value.strip())


def reference(value, items, where):
    require(isinstance(value, str) and value in items, f'{where}: unknown reference {value!r}')
    return items[value]


def distinct_ids(values):
    return isinstance(values, list) and all(text(value) for value in values) and len(values) == len(set(values))


class TeamCompiler:
    def __init__(self, data):
        fields(data, 'schema_version event draws teams sources rules stages groups qualifications ties', 'team bracket')
        self.shared = Compiler({
            'schema_version': data.get('schema_version'),
            'event': data['event'],
            'entries': [],
            'sources': data.get('sources', []),
            'rules': data['rules'],
            'draws': data['draws'],
            'matches': [],
        })
        for source in self.shared.sources.values():
            require(text(source.get('label')), f'{source["id"]}: source label required')
        self.teams = unique(data['teams'], 'teams')
        self.stages = unique(data['stages'], 'stages')
        self.groups = unique(data.get('groups', []), 'groups')
        self.qualifications = unique(data.get('qualifications', []), 'qualifications')
        self.ties = unique(data['ties'], 'ties')
        require(self.shared.draws and self.teams and self.stages and self.ties, 'draws, teams, stages and ties are required')
        self.stage_index = {ident: index for index, ident in enumerate(self.stages)}
        self.rosters = {}
        self.results = {}
        self.visiting = set()
        self.validate_structure()

    def evidence(self, verification, where, *, official=False):
        ids = self.shared.evidence(verification, where)
        if official:
            require(any(self.shared.sources[ident]['kind'] == 'official' for ident in ids),
                    f'{where}: an official source is required')

    def validate_structure(self):
        validate_entry_teams(list(self.teams.values()))
        for ident, team in self.teams.items():
            fields(team, 'id draw team name players', ident)
            reference(team.get('draw'), self.shared.draws, f'{ident} draw')
            require(len(team_codes(team['team'])) == 1, f'{ident}: a team needs one association code')
            require('name' not in team or text(team['name']), f'{ident}: invalid team name')
            roster = unique(team['players'], f'{ident} roster')
            for player in roster.values():
                fields(player, 'id name', f'{ident} roster')
                require(text(player.get('name')), f'{ident}: player name required')
            self.rosters[ident] = roster
        for ident, stage in self.stages.items():
            fields(stage, 'id draw name kind mode order', ident)
            reference(stage.get('draw'), self.shared.draws, f'{ident} draw')
            require(text(stage.get('name')), f'{ident}: stage name required')
            require(stage.get('kind') in ('group', 'knockout'), f'{ident}: invalid stage kind')
            require(stage.get('mode') in ('play_all', 'first_to_three'), f'{ident}: invalid tie mode')
            order = stage.get('order')
            require(isinstance(order, list) and len(order) == 5, f'{ident}: five match positions required')
            for position in order:
                fields(position, 'name kind rule', f'{ident} match position')
                require(text(position.get('name')), f'{ident}: match position name required')
                require(position.get('kind') in ('singles', 'doubles'), f'{ident}: invalid match discipline')
                reference(position.get('rule'), self.shared.rules, f'{ident} match rule')
        memberships = set()
        for ident, group in self.groups.items():
            fields(group, 'id stage name teams standings', ident)
            stage = reference(group.get('stage'), self.stages, f'{ident} stage')
            require(stage['kind'] == 'group' and text(group.get('name')), f'{ident}: invalid group stage or name')
            members = group['teams']
            require(distinct_ids(members) and len(members) >= 2, f'{ident}: invalid group teams')
            for member in members:
                self.team_in_draw(member, stage['draw'], ident)
                key = (stage['id'], member)
                require(key not in memberships, f'{ident}: team already in a group of this stage: {member}')
                memberships.add(key)
            if 'standings' in group:
                standings = group['standings']
                fields(standings, 'order verification', f'{ident} standings')
                order = standings.get('order')
                require(distinct_ids(order) and set(order) == set(members), f'{ident}: standings must list all group teams')
                self.evidence(standings.get('verification'), f'{ident} standings', official=True)
        for ident, qualification in self.qualifications.items():
            fields(qualification, 'id stage team label verification', ident)
            stage = reference(qualification.get('stage'), self.stages, f'{ident} qualification stage')
            self.team_in_draw(qualification.get('team'), stage['draw'], ident)
            require(text(qualification.get('label')), f'{ident}: qualification label required')
            self.evidence(qualification.get('verification'), f'{ident} qualification', official=True)
        group_pairs = set()
        for ident, tie in self.ties.items():
            fields(tie, 'id stage round group slots matches order scheduled_at schedule_verification '
                        'official_result bye_verification completed_date blocker', ident)
            stage = reference(tie.get('stage'), self.stages, f'{ident} stage')
            require(text(tie.get('round')), f'{ident}: round name required')
            slots = tie.get('slots')
            require(isinstance(slots, list) and len(slots) == 2 and all(isinstance(s, dict) and len(s) == 1 for s in slots),
                    f'{ident}: exactly two single-selector slots required')
            require(slots[0] != slots[1] or all('tbd' in slot for slot in slots), f'{ident}: duplicate slot')
            if stage['kind'] == 'group':
                group = reference(tie.get('group'), self.groups, f'{ident} group')
                require(group['stage'] == stage['id'], f'{ident}: group and tie stage mismatch')
                require(all(set(slot) == {'team'} and slot['team'] in group['teams'] for slot in slots),
                        f'{ident}: group ties need two direct teams from the group')
                pair = (group['id'], frozenset(slot['team'] for slot in slots))
                require(pair not in group_pairs, f'{ident}: duplicate group pairing')
                group_pairs.add(pair)
            else:
                require('group' not in tie, f'{ident}: knockout tie cannot belong to a group')

    def team_in_draw(self, ident, draw, where):
        team = reference(ident, self.teams, f'{where} team')
        require(team['draw'] == draw, f'{where}: cross-draw team reference')
        return ident

    def earlier_stage(self, source, target, where, *, same=False):
        require(source['draw'] == target['draw'], f'{where}: cross-draw advancement')
        require(self.stage_index[source['id']] < self.stage_index[target['id']] or (same and source == target),
                f'{where}: advancement must come from an earlier stage')

    def resolve_slot(self, slot, stage, where):
        kind, value = next(iter(slot.items()))
        if kind == 'team':
            return self.team_in_draw(value, stage['draw'], where)
        if kind == 'winner':
            feeder = reference(value, self.ties, f'{where} feeder')
            source = self.stages[feeder['stage']]
            require(source['kind'] == 'knockout', f'{where}: use group_rank for group advancement')
            self.earlier_stage(source, stage, where, same=True)
            return self.tie(value)['winner']
        if kind == 'group_rank':
            require(isinstance(value, list) and len(value) == 2, f'{where}: group_rank needs [group_id, rank]')
            group = reference(value[0], self.groups, f'{where} group')
            self.earlier_stage(self.stages[group['stage']], stage, where)
            rank = value[1]
            require(integer(rank, 1) and rank <= len(group['teams']), f'{where}: invalid group rank')
            return group['standings']['order'][rank - 1] if 'standings' in group else None
        if kind == 'qualified':
            qualification = reference(value, self.qualifications, f'{where} qualification')
            require(qualification['stage'] == stage['id'], f'{where}: qualification is for a different stage')
            return qualification['team']
        if kind == 'bye':
            require(value is True, f'{where}: bye selector must be true')
        elif kind == 'tbd':
            require(text(value), f'{where}: pending slot needs a label')
        else:
            raise ValidationError(f'{where}: unknown slot selector {kind}')
        return None

    def match(self, raw, position, discipline, teams, where):
        fields(raw, 'position lineup status games in_progress_game winner verification reason', where)
        status = raw.get('status', 'scheduled')
        require(status in MATCH_STARTED | {'scheduled'}, f'{where}: invalid match status')
        lineup = raw.get('lineup')
        if 'lineup' in raw or status in MATCH_STARTED:
            require(all(teams) and isinstance(lineup, list) and len(lineup) == 2, f'{where}: match requires lineup for both teams')
            size = 1 if discipline['kind'] == 'singles' else 2
            for members, team in zip(lineup, teams):
                require(distinct_ids(members) and len(members) == size and all(p in self.rosters[team] for p in members),
                        f'{where}: lineup does not match team roster or discipline')
        if status in MATCH_WINS or 'verification' in raw:
            self.evidence(raw.get('verification'), where)
        games = raw.get('games', [])
        require(isinstance(games, list), f'{where}: games must be a list')
        rule = self.shared.rules[discipline['rule']]
        target = rule['best_of'] // 2 + 1
        score = [0, 0]
        for game in games:
            require(max(score) < target, f'{where}: game after individual match clinched')
            try:
                score[game_winner(game, rule)] += 1
            except ValidationError as exc:
                raise ValidationError(f'{where}: {exc}') from exc
        declared = raw.get('winner')
        require('winner' not in raw or (integer(declared) and declared < 2), f'{where}: winner must be side 0 or 1')
        winner = None
        if status == 'completed':
            require(max(score) == target, f'{where}: incomplete individual match score')
            winner = score.index(target)
            require(declared is None or winner == declared, f'{where}: declared winner contradicts individual score')
        else:
            require(max(score) < target, f'{where}: terminal score requires completed match')
            if status in ('retired', 'walkover'):
                require(declared is not None and text(raw.get('reason')), f'{where}: exceptional result requires winner and reason')
                winner = declared
            else:
                require(declared is None, f'{where}: unfinished match cannot declare winner')
            if status in ('scheduled', 'walkover'):
                require(not games, f'{where}: scheduled match or walkover cannot have played games')
        if 'in_progress_game' in raw:
            require(status in ('live', 'retired'), f'{where}: unfinished game requires live or retired status')
            try:
                game_winner(raw['in_progress_game'], rule, partial=True)
            except ValidationError as exc:
                raise ValidationError(f'{where}: {exc}') from exc
        return {**raw, **discipline, 'position': position, 'status': status, 'winner': winner, 'games': games,
                'score': score if status in ('completed', 'live', 'retired') else None}

    def tie_matches(self, tie, stage, teams):
        ident = tie['id']
        order = tie.get('order', list(range(1, 6)))
        require(isinstance(order, list) and len(order) == 5 and all(integer(n, 1) for n in order)
                and set(order) == POSITIONS, f'{ident}: order must be a permutation of positions 1–5')
        raw_matches = tie.get('matches', [])
        require(isinstance(raw_matches, list), f'{ident}: matches must be a list')
        rows = {}
        for raw in raw_matches:
            require(isinstance(raw, dict), f'{ident}: match must be an object')
            position = raw.get('position')
            require(integer(position, 1) and position in POSITIONS and position not in rows,
                    f'{ident}: invalid or duplicate match position')
            rows[position] = raw
        return [self.match(rows.get(i, {}), i, stage['order'][entry - 1], teams, f'{ident} match {i}')
                for i, entry in enumerate(order, 1)]

    def official_score(self, result, teams, stage, matches, where):
        fields(result, 'status result_for score winner verification reason', f'{where} official result')
        require(all(teams) and result.get('result_for') == teams, f'{where}: official result_for must bind both teams in order')
        self.evidence(result.get('verification'), f'{where} official result', official=True)
        status = result.get('status', 'completed')
        require(status in ('completed', 'walkover'), f'{where}: invalid official result status')
        score = result.get('score')
        if 'score' in result:
            require(isinstance(score, list) and len(score) == 2 and all(integer(x) and x <= 5 for x in score)
                    and score[0] != score[1], f'{where}: invalid official tie score')
        if status == 'walkover':
            winner = result.get('winner')
            require(integer(winner) and winner < 2 and text(result.get('reason')),
                    f'{where}: team walkover requires winner and reason')
            require(all(m['status'] == 'scheduled' for m in matches), f'{where}: team walkover cannot have played matches')
            require(score is None or (sum(score) <= 5 and score[winner] >= 3 and score[1 - winner] == 0),
                    f'{where}: official walkover score contradicts winner')
            return score, winner, status, 0
        require('winner' not in result and score is not None, f'{where}: completed official result requires a score')
        winner = int(score[1] > score[0])
        play_all = stage['mode'] == 'play_all'
        played = sum(score)
        require(played == 5 if play_all else score[winner] == 3 and score[1 - winner] < 3,
                f'{where}: official score contradicts stage rules')
        require(all(m['status'] != 'live' for m in matches), f'{where}: official terminal tie cannot contain a live match')
        require(all(m['status'] == 'scheduled' for m in matches[played:]), f'{where}: match recorded after tie clinched')
        # Check whether at least one ordering of the missing results fits the published score and clinch.
        possibilities = [(m['winner'],) if m['winner'] is not None else (0, 1) for m in matches[:played]]
        require(any(sequence.count(0) == score[0] and (play_all or sequence[-1] == winner)
                    for sequence in product(*possibilities)), f'{where}: individual results contradict official tie score or clinch order')
        return score, winner, status, played

    def resolve_score(self, tie, stage, teams, matches):
        ident = tie['id']
        is_bye = any('bye' in slot for slot in tie['slots'])
        if is_bye:
            require('official_result' not in tie and not tie.get('matches'), f'{ident}: bye cannot have matches or a score')
            self.evidence(tie.get('bye_verification'), f'{ident} bye', official=True)
            if all(team is None for team in teams):
                return None, None, 'scheduled', None
            return None, next(i for i, team in enumerate(teams) if team is not None), 'bye', 0
        require('bye_verification' not in tie, f'{ident}: bye verification needs a bye slot')
        if 'official_result' in tie:
            return self.official_score(tie['official_result'], teams, stage, matches, ident)
        score = [0, 0]
        prefix = True
        for match in matches:
            winner = match['winner']
            if winner is None:
                prefix = False
                continue
            score[winner] += 1
            if stage['mode'] == 'first_to_three':
                require(score[winner] <= 3, f'{ident}: match recorded after tie clinched')
                if score[winner] == 3:
                    require(all(m['status'] == 'scheduled' for m in matches[match['position']:]),
                            f'{ident}: match recorded after tie clinched')
                    if prefix:
                        return score, winner, 'completed', match['position']
        if sum(score) == 5:
            return score, int(score[1] > score[0]), 'completed', 5
        live = any(m['status'] in MATCH_STARTED for m in matches)
        return (score if live else None), None, ('live' if live else 'scheduled'), None

    def tie(self, ident):
        if ident in self.results:
            return self.results[ident]
        require(ident not in self.visiting, f'{ident}: cyclic advancement')
        self.visiting.add(ident)
        raw = self.ties[ident]
        stage = self.stages[raw['stage']]
        teams = [self.resolve_slot(slot, stage, ident) for slot in raw['slots']]
        require(teams[0] is None or teams[0] != teams[1], f'{ident}: team cannot face itself')
        scheduled = timestamp(raw['scheduled_at']) if 'scheduled_at' in raw else None
        if 'schedule_verification' in raw:
            require(scheduled is not None, f'{ident}: schedule verification requires scheduled_at')
            self.evidence(raw['schedule_verification'], f'{ident} schedule')
        matches = self.tie_matches(raw, stage, teams)
        score, winner, status, played = self.resolve_score(raw, stage, teams, matches)
        if 'blocker' in raw or (scheduled and scheduled < self.shared.snapshot and status not in FINAL_TIES):
            require(text(raw.get('blocker')), f'{ident}: overdue unresolved tie needs blocker')
        if 'completed_date' in raw:
            self.validate_completion_date(raw, status, matches)
        summary_only = False
        if played is not None:
            for match in matches:
                if match['position'] > played:
                    match['status'] = 'not_played'
                elif match['winner'] is None:
                    match['status'] = 'unverified'
                    summary_only = True
        result = {**raw, 'teams': teams, 'score': score, 'winner': teams[winner] if winner is not None else None,
                  'status': status, 'summary_only': summary_only, 'matches': matches}
        self.results[ident] = result
        self.visiting.remove(ident)
        return result

    def validate_completion_date(self, raw, status, matches):
        ident, value = raw['id'], raw['completed_date']
        require(status in FINAL_TIES and isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value),
                f'{ident}: invalid completion date')
        try:
            completed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(f'{ident}: invalid completion date') from exc
        zone = ZoneInfo(self.shared.event['timezone'])
        require(completed <= self.shared.snapshot.astimezone(zone).date(), f'{ident}: completion date is after snapshot')
        if status != 'bye':
            verified = ([raw['official_result']['verification']] if 'official_result' in raw else
                        [match['verification'] for match in matches if match['winner'] is not None])
            latest = max(timestamp(item['verified_at']) for item in verified)
            require(completed <= latest.astimezone(zone).date(), f'{ident}: verified before completion date')

    def validate_advancement(self, ties):
        consumed = set()
        entrants = set()
        for tie in ties:
            stage_id = tie['stage']
            if self.stages[stage_id]['kind'] != 'knockout':
                continue
            for slot, team in zip(tie['slots'], tie['teams']):
                kind, value = next(iter(slot.items()))
                if kind in ('winner', 'group_rank', 'qualified'):
                    key = (kind, tuple(value) if kind == 'group_rank' else value)
                    require(key not in consumed, f'{tie["id"]}: duplicate advancement source {value!r}')
                    consumed.add(key)
                if kind == 'winner' and self.ties[value]['stage'] == stage_id:
                    continue
                if team is not None:
                    key = (stage_id, team)
                    require(key not in entrants, f'{tie["id"]}: team entered twice in knockout stage: {team}')
                    entrants.add(key)

    def compile(self):
        ties = [self.tie(ident) for ident in self.ties]
        self.validate_advancement(ties)
        return {'event': self.shared.event, 'draws': list(self.shared.draws.values()),
                'sources': list(self.shared.sources.values()), 'teams': list(self.teams.values()),
                'stages': list(self.stages.values()), 'groups': list(self.groups.values()),
                'qualifications': list(self.qualifications.values()), 'ties': ties}


def compile_team_record(record):
    fields(record, 'kind schema_version id output event_dates notices data', 'team record')
    require(record.get('kind') == 'team-bracket-v1', 'expected team-bracket-v1 record')
    require(type(record.get('schema_version', 1)) is int and record.get('schema_version', 1) == 1,
            'unsupported team record schema_version')
    require(text(record.get('id')) and text(record.get('output')), 'team record needs id and output')
    notices = record.get('notices', [])
    require(isinstance(notices, list) and all(text(notice) for notice in notices), 'notices must be nonempty strings')
    try:
        return {**TeamCompiler(record['data']).compile(), 'notices': notices}
    except (KeyError, TypeError) as exc:
        raise ValidationError(f'invalid team bracket data: {exc}') from exc


def main():
    from .team_board import render_team

    parser = argparse.ArgumentParser(description='Render a team bracket to standalone HTML.')
    parser.add_argument('record', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        model = compile_team_record(load(args.record))
        args.output.write_text(render_team(model), encoding='utf-8')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{args.record}: {exc}\n')
    print(f'Rendered {len(model["ties"])} team ties to {args.output}')


if __name__ == '__main__':
    main()
