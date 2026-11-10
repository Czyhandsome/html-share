"""Engine contract/regression tests. Run: python -m unittest discover -s tests -v."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from bracketkit import ValidationError, compile_data, game_winner, load, render, safe_url

VERIFICATION = {'source_ids': ['official'], 'verified_at': '2026-01-01T12:00:00Z'}

def match(ident='m1', a='a', b='b', **overrides):
    m = {'id': ident, 'round': 'Final', 'rule': 'tt', 'slots': [{'entry': a}, {'entry': b}],
         'status': 'completed', 'result_for': [a, b], 'games': [[11, 4], [11, 7]], 'verification': copy.deepcopy(VERIFICATION)}
    m.update(overrides)
    if m['status'] not in ('completed', 'retired', 'walkover', 'live'): m.pop('result_for', None)
    return m

def fixture():
    return {'schema_version': 1,
            'event': {'name': 'Test', 'snapshot_at': '2026-01-02T12:00:00Z',
                      'timezone': 'Asia/Shanghai', 'venue_timezone': 'Europe/London'},
            'entries': [{'id': x, 'name': x.upper(), 'team': 'CHN' if x == 'a' else 'JPN'} for x in 'abc'],
            'rules': {'tt': {'best_of': 3, 'points': 11, 'win_by': 2}},
            'sources': [{'id': 'official', 'url': 'https://example.com/results', 'kind': 'official', 'family': 'official'}],
            'matches': [match()]}

def group_fixture():
    d = fixture()
    d['groups'] = [{'id': 'g', 'entries': list('abc'), 'ranking': ['wins', 'game_ratio', 'point_ratio']}]
    d['matches'] = [match('ab', 'a', 'b', group='g'), match('ac', 'a', 'c', group='g'), match('bc', 'b', 'c', group='g')]
    return d

class ScoreTests(unittest.TestCase):
    rule = {'best_of': 3, 'points': 11, 'win_by': 2}
    def test_legal_games(self):
        for score, winner in [([11, 0], 0), ([12, 10], 0), ([23, 25], 1)]:
            self.assertEqual(game_winner(score, self.rule), winner)
    def test_illegal_games(self):
        for score in [[11, 10], [12, 4], [11, 11], [-1, 11], [True, 11], [11.0, 2], [11], '11-2']:
            with self.subTest(score=score), self.assertRaises(ValidationError):
                game_winner(score, self.rule)
    def test_cap(self):
        r = dict(self.rule, points=21, cap=30)
        self.assertEqual(game_winner([30, 29], r), 0)
        for score in [[31, 29], [30, 27], [30, 30]]:
            with self.subTest(score=score), self.assertRaises(ValidationError):
                game_winner(score, r)
    def test_live_game(self):
        self.assertIsNone(game_winner([10, 10], self.rule, partial=True))
        with self.assertRaises(ValidationError):
            game_winner([11, 9], self.rule, partial=True)
    def test_cap_tied_live_is_unreachable(self):
        with self.assertRaises(ValidationError):
            game_winner([30, 30], dict(self.rule, points=21, cap=30), partial=True)
    def test_sudden_death_final_cannot_pass_target(self):
        with self.assertRaises(ValidationError):
            game_winner([12, 11], dict(self.rule, win_by=1))
    def test_sudden_death_live_cannot_reach_target(self):
        with self.assertRaises(ValidationError):
            game_winner([11, 11], dict(self.rule, win_by=1), partial=True)

class EngineTests(unittest.TestCase):
    def test_derives_winner_score_without_mutation(self):
        d = fixture(); original = copy.deepcopy(d)
        m = compile_data(d)['matches'][0]
        self.assertEqual((m['winner'], m['score'], m['players']), ('a', [2, 0], ['a', 'b']))
        self.assertEqual(d, original)
    def test_rejects_score_contradictions(self):
        for change in [{'winner': 'b'}, {'score': [2, 0]}, {'players': ['a', 'b']},
                       {'games': [[11, 4]]}, {'games': [[11, 4]] * 3}, {'in_progress_game': [0, 0]}]:
            d = fixture(); d['matches'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError): compile_data(d)
    def test_advancement(self):
        d = fixture(); d['matches'].append(match('m2', b='c', slots=[{'winner': 'm1'}, {'entry': 'c'}]))
        self.assertEqual(compile_data(d)['matches'][1]['players'], ['a', 'c'])
    def test_upstream_revision_invalidates_downstream_result_binding(self):
        d = fixture(); d['matches'].append(match('m2', b='c', slots=[{'winner': 'm1'}, {'entry': 'c'}]))
        compile_data(d)
        d['matches'][0]['games'] = [[4, 11], [7, 11]]
        with self.assertRaisesRegex(ValidationError, 'result_for'): compile_data(d)
    def test_binding_required_for_all_played_statuses(self):
        for status in ['completed', 'live', 'retired', 'walkover']:
            d = fixture(); m = d['matches'][0]; m['status'] = status; del m['result_for']
            if status != 'completed': m['games'] = []
            if status in ('retired', 'walkover'): m.update(winner='a', reason='absent')
            with self.subTest(status=status), self.assertRaisesRegex(ValidationError, 'result_for'): compile_data(d)
    def test_binding_reversed_rejected(self):
        d = fixture(); d['matches'][0]['result_for'] = ['b', 'a']
        with self.assertRaisesRegex(ValidationError, 'result_for'): compile_data(d)
    def test_binding_forbidden_on_unplayed_statuses(self):
        for status in ['scheduled', 'cancelled', 'bye']:
            d = fixture(); m = d['matches'][0]; m.update(status=status, games=[])
            if status == 'bye': m['slots'][1] = {'bye': True}
            with self.subTest(status=status), self.assertRaisesRegex(ValidationError, 'result_for'): compile_data(d)
    def test_direct_seed_cannot_appear_twice_in_same_draw(self):
        d = fixture(); d['matches'].append(match('other', 'a', 'c'))
        with self.assertRaisesRegex(ValidationError, 'seeded twice'): compile_data(d)
    def test_same_entry_allowed_in_separate_draws(self):
        d = fixture(); d['draws'] = [{'id': 'main', 'name': 'Singles'}, {'id': 'other', 'name': 'Doubles'}]
        d['matches'].append(match('other', 'a', 'c', draw='other'))
        self.assertEqual(len(compile_data(d)['matches']), 2)
    def test_cross_draw_winner_reference_rejected(self):
        d = fixture(); d['draws'] = [{'id': 'main', 'name': 'Singles'}, {'id': 'other', 'name': 'Doubles'}]
        d['matches'].append(match('m2', b='c', draw='other', slots=[{'winner': 'm1'}, {'entry': 'c'}]))
        with self.assertRaisesRegex(ValidationError, 'cross-draw'): compile_data(d)
    def test_unknown_draw_rejected(self):
        d = fixture(); d['matches'][0]['draw'] = 'missing'
        with self.assertRaisesRegex(ValidationError, 'unknown draw'): compile_data(d)
    def test_cycle(self):
        d = fixture(); d['matches'][0]['slots'][0] = {'winner': 'm2'}
        d['matches'].append(match('m2', b='c', slots=[{'winner': 'm1'}, {'entry': 'c'}]))
        with self.assertRaisesRegex(ValidationError, 'cyclic'): compile_data(d)
    def test_duplicate_advancement(self):
        d = fixture()
        d['matches'] += [match(x, b='c', slots=[{'winner': 'm1'}, {'entry': 'c'}]) for x in ['m2', 'm3']]
        with self.assertRaisesRegex(ValidationError, 'consumed'): compile_data(d)
    def test_unresolved_feeder_does_not_invent_player(self):
        d = fixture(); d['matches'][0].update(status='scheduled', games=[])
        d['matches'][0].pop('result_for', None)
        d['matches'].append(match('m2', b='c', slots=[{'winner': 'm1'}, {'entry': 'c'}], status='scheduled', games=[]))
        self.assertEqual(compile_data(d)['matches'][1]['players'], [None, 'c'])
        d['matches'][1]['status'] = 'live'
        with self.assertRaisesRegex(ValidationError, 'unresolved'): compile_data(d)
    def test_self_match(self):
        d = fixture(); d['matches'][0]['slots'][1] = {'entry': 'a'}
        with self.assertRaisesRegex(ValidationError, 'self'): compile_data(d)
    def test_bye(self):
        d = fixture(); d['matches'][0].update(status='bye', games=[], slots=[{'entry': 'a'}, {'bye': True}])
        d['matches'][0].pop('result_for', None)
        m = compile_data(d)['matches'][0]
        self.assertEqual(m['winner'], 'a'); self.assertIsNone(m['score'])
    def test_retirement_keeps_score_not_score_winner(self):
        d = fixture(); d['matches'][0].update(status='retired', games=[[11, 4]], in_progress_game=[8, 2], winner='b', reason='injury')
        m = compile_data(d)['matches'][0]
        self.assertEqual((m['winner'], m['score']), ('b', [1, 0]))
    def test_walkover_without_fabricated_games(self):
        d = fixture(); d['matches'][0].update(status='walkover', games=[], winner='b', reason='absent')
        self.assertIsNone(compile_data(d)['matches'][0]['score'])
        d['matches'][0]['games'] = [[11, 4]]
        with self.assertRaises(ValidationError): compile_data(d)
    def test_overdue_requires_and_records_blocker(self):
        d = fixture(); d['matches'][0].update(status='scheduled', games=[], scheduled_at='2026-01-01T10:00:00Z')
        d['matches'][0].pop('result_for', None)
        with self.assertRaisesRegex(ValidationError, 'blocker'): compile_data(d)
        d['matches'][0]['blocker'] = 'Awaiting official result'
        self.assertEqual(len(compile_data(d)['audit']), 1)
    def test_evidence_rules(self):
        d = fixture(); d['sources'][0]['kind'] = 'independent'
        with self.assertRaisesRegex(ValidationError, 'families'): compile_data(d)
        d['sources'].append({'id': 'second', 'kind': 'independent', 'family': 'second', 'url': 'https://example.org'})
        d['matches'][0]['verification']['source_ids'].append('second')
        compile_data(d)
        d['sources'][1]['family'] = 'official'
        with self.assertRaisesRegex(ValidationError, 'families'): compile_data(d)
    def test_future_verification(self):
        d = fixture(); d['matches'][0]['verification']['verified_at'] = '2027-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValidationError, 'snapshot'): compile_data(d)
    def test_invalid_nonterminal_verification_rejected_by_compiler(self):
        d = fixture(); d['matches'][0].update(status='scheduled', games=[], verification={'verified_at': 'invalid'})
        d['matches'][0].pop('result_for', None)
        with self.assertRaises(ValidationError): compile_data(d)

class GroupTests(unittest.TestCase):
    def test_table_and_rank_advancement(self):
        d = group_fixture(); d['matches'].append(match('final', slots=[{'group_rank': ['g', 1]}, {'group_rank': ['g', 2]}]))
        out = compile_data(d)
        self.assertTrue(out['groups'][0]['final'])
        self.assertEqual(out['groups'][0]['order'], list('abc'))
        self.assertEqual(out['matches'][-1]['players'], ['a', 'b'])
        self.assertEqual(out['groups'][0]['rows'][0]['points_for'], 44)
    def test_cross_draw_group_rank_reference_rejected(self):
        d = group_fixture(); d['draws'] = [{'id': 'main', 'name': 'Singles'}, {'id': 'other', 'name': 'Doubles'}]
        d['matches'].append(match('final', draw='other', slots=[{'group_rank': ['g', 1]}, {'group_rank': ['g', 2]}]))
        with self.assertRaisesRegex(ValidationError, 'cross-draw'): compile_data(d)
    def test_group_fixture_must_belong_to_group_draw(self):
        d = group_fixture(); d['draws'] = [{'id': 'main', 'name': 'Singles'}, {'id': 'other', 'name': 'Doubles'}]
        d['matches'][0]['draw'] = 'other'
        with self.assertRaisesRegex(ValidationError, 'draw mismatch'): compile_data(d)
    def test_incomplete_round_robin(self):
        d = group_fixture(); d['matches'].pop()
        with self.assertRaisesRegex(ValidationError, 'every pairing'): compile_data(d)
    def test_exact_tie_stays_unresolved(self):
        d = group_fixture(); d['matches'][1]['games'] = [[4, 11], [7, 11]]
        g = compile_data(d)['groups'][0]
        self.assertFalse(g['final'])
        d['groups'][0]['adjudication'] = {'order': ['c', 'a', 'b'], 'reason': 'Official tiebreak', 'verification': copy.deepcopy(VERIFICATION)}
        g = compile_data(d)['groups'][0]
        self.assertTrue(g['final']); self.assertEqual(g['order'], ['c', 'a', 'b'])
    def test_adjudication_needs_official_not_just_two_independent_sources(self):
        d = group_fixture()
        d['sources'][0]['kind'] = 'independent'
        d['sources'].append({'id': 'second', 'kind': 'independent', 'family': 'second', 'url': 'https://example.org'})
        for m in d['matches']: m['verification']['source_ids'].append('second')
        d['groups'][0]['adjudication'] = {'order': list('abc'), 'reason': 'Claimed ruling',
                                       'verification': dict(VERIFICATION, source_ids=['official', 'second'])}
        with self.assertRaisesRegex(ValidationError, 'official'): compile_data(d)
    def test_incomplete_group_cannot_be_adjudicated(self):
        d = group_fixture(); d['matches'][0].update(status='scheduled', games=[])
        d['matches'][0].pop('result_for', None)
        d['groups'][0]['adjudication'] = {'order': list('abc'), 'reason': 'Premature ruling', 'verification': copy.deepcopy(VERIFICATION)}
        with self.assertRaises(ValidationError): compile_data(d)
    def test_walkover_requires_adjudication(self):
        d = group_fixture(); d['matches'][0].update(status='walkover', games=[], winner='a', reason='absent')
        self.assertFalse(compile_data(d)['groups'][0]['final'])
    def test_cancelled_group_match_can_be_officially_adjudicated(self):
        d = group_fixture(); d['matches'][0].update(status='cancelled', games=[])
        d['matches'][0].pop('result_for', None)
        d['groups'][0]['adjudication'] = {'order': list('abc'), 'reason': 'Official cancellation ruling', 'verification': copy.deepcopy(VERIFICATION)}
        self.assertTrue(compile_data(d)['groups'][0]['final'])

class RenderTests(unittest.TestCase):
    def test_xss_escaping_and_embedded_model_consistency(self):
        d = fixture(); attack = '</script><script>alert("x")</script>'
        d['entries'][0]['name'] = attack; d['event']['name'] = attack; d['matches'][0]['round'] = attack
        out = compile_data(d); page = render(out)
        self.assertNotIn(attack, page)
        self.assertIn('&lt;/script&gt;', page)
        payload = re.search(r'<script type="application/json" id="tournament-data">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(payload), out)
        self.assertIn('href="index.html"', page)
    def test_unsafe_source_scheme_rejected(self):
        for url in ['javascript:alert(1)', 'data:text/html,evil', '//example.com', 'https://user:pass@example.com']:
            with self.subTest(url=url), self.assertRaises(ValidationError): safe_url(url)
    def test_empty_username_credentials_rejected(self):
        with self.assertRaises(ValidationError): safe_url('https://:secret@example.com')
    def test_missing_event_name_rejected_during_compilation(self):
        d = fixture(); del d['event']['name']
        with self.assertRaises(ValidationError): compile_data(d)
    def test_unknown_fields_rejected(self):
        d = fixture(); d['matches'][0]['socre'] = [2, 0]
        with self.assertRaises(ValidationError): compile_data(d)
    def test_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.json'; path.write_text('{"x": 1, "x": 2}')
            with self.assertRaisesRegex(ValidationError, 'duplicate'): load(path)

if __name__ == '__main__': unittest.main()
