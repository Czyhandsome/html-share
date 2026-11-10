"""Preserve inherited results and require evidence for changes to the WTT baseline."""
import json
from pathlib import Path
import unittest
from sports.compiler import compile_record, ValidationError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name('fixtures')

def record(slug='frankfurt'):
    return json.loads((ROOT / f'sports/data/wtt-{slug}-2026.json').read_text())

class MigrationTests(unittest.TestCase):
    def test_all_original_pairings_scores_winners_and_games_preserved(self):
        for slug in ['Frankfurt', 'Montpellier']:
            raw = json.loads((FIXTURES / f'WTT-{slug}-2026.baseline.json').read_text())
            model = compile_record(record(slug.lower()), ROOT)
            matches = {m['id']: m for m in model['matches']}
            names = {e['id']: e['name'] for e in model['entries']}
            sources = {s['id']: s['url'] for s in model['sources']}
            self.assertEqual(len(matches), 62)
            for draw, originals in raw.items():
                for old in originals:
                    with self.subTest(event=slug, match=old['id']):
                        m = matches[old['id']]
                        self.assertEqual(m['draw'], draw)
                        if old.get('winner') is not None:
                            players = [names[p] for p in m['players']]
                            self.assertEqual(players, old['players'])
                            self.assertEqual(m['score'], old['scores'])
                            self.assertEqual(m['games'], old.get('games') or [])
                            self.assertEqual(players.index(names[m['winner']]), old['winner'])
                        self.assertEqual(m.get('scheduled_at'), old.get('scheduled'))
                        self.assertEqual(m.get('completed_date'), old.get('completedDate'))
                        schedule_evidence = m.get('schedule_verification', {})
                        self.assertEqual([sources[s] for s in schedule_evidence.get('source_ids', [])],
                                         old.get('scheduleSources', []))
                        self.assertEqual(schedule_evidence.get('verified_at'), old.get('scheduleCheckedAt'))

    def test_frankfurt_imports_teams_for_filtering(self):
        model = compile_record(record(), ROOT)
        teams = {e['name']: e['team'] for e in model['entries']}
        self.assertEqual(len(teams), 64)
        self.assertTrue(all(teams.values()))
        self.assertEqual({name for name, team in teams.items() if team == 'CHN'},
                         {'向鹏', '梁靖崑', '周启豪', '温瑞博', '王楚钦', '王艺迪', '陈熠', '蒯曼', '陈幸同'})
    def test_frankfurt_missing_results_are_bound_to_the_verified_route(self):
        r = record()
        model = compile_record(r, ROOT)
        matches = {m['id']: m for m in model['matches']}
        names = {e['id']: e['name'] for e in model['entries']}
        self.assertEqual(len(r['migration_releases']), 19)
        self.assertFalse(model['audit'])
        self.assertTrue(all(m['status'] == 'completed' for m in matches.values()))
        for final, champion in [('men-l4-0', '张本智和'), ('women-l4-0', '早田希娜')]:
            self.assertEqual(matches[final]['score'], [2, 4])
            self.assertEqual(names[matches[final]['winner']], champion)
        semifinal = matches['men-l3-0']
        self.assertEqual([names[p] for p in semifinal['players']], ['弗兰西斯卡', '户上隼辅'])

    def test_carried_results_are_not_claimed_as_new_verification(self):
        for slug in ['frankfurt', 'montpellier']:
            r = record(slug); model = compile_record(r, ROOT)
            for m in model['matches']:
                if m['id'] in r['inherited_evidence']:
                    self.assertEqual(m['verification_status'], 'imported_unverified')
                    self.assertTrue(m['migration_notice'])
    def test_changed_imported_match_rejected_before_evidence_dispatch(self):
        r = record(); m = r['data']['matches'][0]
        m.update(status='scheduled', games=[], blocker='test downgrade')
        m.pop('verification'); m.pop('result_for')
        with self.assertRaisesRegex(ValidationError, 'imported match changed'): compile_record(r, ROOT)
    def test_changed_imported_point_rejected(self):
        r = record(); r['data']['matches'][0]['games'][0][1] += 1
        with self.assertRaisesRegex(ValidationError, 'imported match changed'): compile_record(r, ROOT)
    def test_context_name_team_source_and_rule_cannot_silently_change(self):
        for target, key, value in [('entries', 'name', 'Replacement player'), ('entries', 'team', 'CHN'),
                                   ('sources', 'url', 'https://example.com/replaced-evidence'),
                                   ('sources', 'kind', 'official')]:
            r = record(); r['data'][target][0][key] = value
            with self.subTest(target=target, key=key), self.assertRaisesRegex(ValidationError, 'context changed'):
                compile_record(r, ROOT)
        r = record(); r['data']['rules']['early']['points'] = 9
        with self.assertRaisesRegex(ValidationError, 'context changed'): compile_record(r, ROOT)
    def test_unreferenced_new_sources_do_not_invalidate_imports(self):
        r = record(); r['data']['sources'].append({'id': 'new', 'url': 'https://example.org', 'kind': 'official', 'family': 'new'})
        compile_record(r, ROOT)
    def test_missing_imported_match_rejected(self):
        r = record(); r['data']['matches'].pop(0)
        with self.assertRaisesRegex(ValidationError, 'migration lock/data'): compile_record(r, ROOT)
    def test_removing_inherited_marker_restores_strict_evidence(self):
        r = record(); r['inherited_evidence'].pop(r['data']['matches'][0]['id'])
        with self.assertRaisesRegex(ValidationError, 'official source or two'): compile_record(r, ROOT)
    def test_pending_edit_needs_explicit_release_record(self):
        r = record()
        r['migration_releases'].pop('men-r32-7')
        with self.assertRaisesRegex(ValidationError, 'pending baseline changed'):
            compile_record(r, ROOT)

    def test_release_record_is_not_a_result_evidence_bypass(self):
        r = record()
        match = next(m for m in r['data']['matches'] if m['id'] == 'men-r32-7')
        match.pop('verification')
        with self.assertRaisesRegex(ValidationError, 'verification'):
            compile_record(r, ROOT)

    def test_release_requires_audit_fields_and_known_pending_id(self):
        for releases in [{'nonexistent': {'reason': 'x', 'authorization': 'y'}},
                         {'men-r32-7': {'reason': 'x'}}, {'men-r32-7': {'reason': '', 'authorization': 'y'}}]:
            r = record(); r['migration_releases'] = releases
            with self.subTest(releases=releases), self.assertRaises(ValidationError): compile_record(r, ROOT)

if __name__ == '__main__': unittest.main()
