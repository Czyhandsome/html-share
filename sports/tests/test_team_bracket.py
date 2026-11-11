"""Coverage for individual scores, team results and official advancement."""

from copy import deepcopy
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from sports.build import INDEX, build
from sports.core.bracketkit import ValidationError, load
from sports.core.team_bracket import compile_team_record


SPORTS = Path(__file__).resolve().parents[1]
EXAMPLE = SPORTS / 'core/examples/team-bracket.json'


def by_id(items):
    return {item['id']: item for item in items}


class TeamBracketTests(unittest.TestCase):
    def setUp(self):
        self.record = load(EXAMPLE)
        self.data = self.record['data']
        self.ties = by_id(self.data['ties'])

    def compiled_ties(self):
        return by_id(compile_team_record(self.record)['ties'])

    def test_thomas_plays_all_five_then_clinches_knockout_at_three(self):
        ties = self.compiled_ties()
        group_tie = ties['thomas-group-1']
        self.assertEqual(group_tie['completed_date'], '2026-11-09')
        self.assertEqual(group_tie['score'], [5, 0])
        self.assertEqual(group_tie['winner'], 'thomas-cn')
        self.assertEqual([row['status'] for row in group_tie['matches']], ['completed'] * 5)
        self.assertEqual(group_tie['matches'][1]['lineup'][0], ['thomas-cn-1', 'thomas-cn-4'])

        semifinal = ties['thomas-final-1']
        self.assertEqual((semifinal['teams'], semifinal['score']), (['thomas-cn', 'thomas-kr'], [3, 0]))
        self.assertEqual([row['status'] for row in semifinal['matches']], ['completed'] * 3 + ['not_played'] * 2)
        self.assertEqual(ties['thomas-title']['teams'], ['thomas-cn', None])

    def test_uber_keeps_official_total_when_rubbers_are_unverified(self):
        ties = self.compiled_ties()
        group_tie = ties['uber-group-1']
        self.assertEqual(group_tie['score'], [4, 1])
        self.assertEqual([row['status'] for row in group_tie['matches']], ['unverified'] * 5)
        final = ties['uber-final-1']
        self.assertEqual((final['status'], final['score'], final['winner']), ('completed', [3, 1], 'uber-cn'))
        self.assertTrue(final['summary_only'])
        self.assertEqual([row['status'] for row in final['matches']], ['unverified'] * 4 + ['not_played'])
        self.assertTrue(all(row['games'] == [] for row in final['matches']))

    def test_asian_team_final_resolves_from_verified_aggregate(self):
        ties = self.compiled_ties()
        semifinal = ties['asian-sf-1']
        self.assertEqual((semifinal['score'], semifinal['winner']), ([3, 2], 'asian-cn'))
        self.assertTrue(semifinal['summary_only'])
        self.assertEqual(semifinal['matches'][1]['score'], [2, 0])
        self.assertEqual(ties['asian-final']['teams'], ['asian-cn', 'asian-jp'])

    def test_london_combines_direct_qualification_playoff_and_seed_group(self):
        ties = self.compiled_ties()
        playoff = ties['london-playoff-1']
        self.assertEqual(playoff['teams'], ['london-en', 'london-fr'])
        self.assertEqual(playoff['matches'][0]['score'], [3, 1])
        self.assertEqual(ties['london-main-1']['teams'], ['london-kr', 'london-en'])
        self.assertEqual(ties['london-main-2']['teams'], ['london-cn', 'london-hk'])

        # A completed group tie alone does not authorize a published seeding position.
        del by_id(self.data['groups'])['london-s1']['standings']
        self.assertEqual(self.compiled_ties()['london-main-2']['teams'], [None, 'london-hk'])

    def test_partial_aggregate_reconciles_with_later_detail(self):
        semifinal = self.ties['asian-sf-1']
        match = semifinal['matches'][0]
        semifinal['matches'] = []
        for position, players, winner in [(1, [1], 1), (2, [1, 4], 0), (3, [2], 1),
                                          (4, [2, 3], 0), (5, [3], 0)]:
            lineup = [[f'{team}-{player}' for player in players] for team in ('asian-cn', 'asian-id')]
            games = [[21, 17], [21, 18]] if winner == 0 else [[17, 21], [18, 21]]
            semifinal['matches'].append(dict(match, position=position, lineup=lineup, games=games))
        resolved = self.compiled_ties()['asian-sf-1']
        self.assertEqual(resolved['score'], [3, 2])
        self.assertFalse(resolved['summary_only'])

        semifinal['matches'][-1]['games'] = [[17, 21], [18, 21]]
        with self.assertRaisesRegex(ValidationError, 'contradict official tie score'):
            self.compiled_ties()

    def test_partial_detail_must_admit_the_official_clinch_order(self):
        semifinal = self.ties['asian-sf-1']
        # Three wins by the first team are still numerically possible, but it must win match five.
        semifinal['matches'].append(dict(semifinal['matches'][0], position=5,
                                         lineup=[['asian-cn-3'], ['asian-id-3']], games=[[17, 21], [18, 21]]))
        with self.assertRaisesRegex(ValidationError, 'clinch order'):
            self.compiled_ties()

    def test_rejects_lineup_player_from_wrong_team_and_wrong_discipline(self):
        lineup = self.ties['thomas-group-1']['matches'][1]['lineup']
        first = lineup[0]
        for invalid in (['thomas-cn-1', 'thomas-kr-1'], ['thomas-cn-1']):
            with self.subTest(lineup=invalid), self.assertRaisesRegex(ValidationError, 'lineup does not match'):
                lineup[0] = invalid
                self.compiled_ties()
        lineup[0] = first

    def test_rejects_cross_draw_winner_reference(self):
        self.ties['asian-final']['slots'][0] = {'winner': 'thomas-final-1'}
        with self.assertRaisesRegex(ValidationError, 'cross-draw advancement'):
            self.compiled_ties()

    def test_rejects_duplicated_advancement_and_cross_selector_team(self):
        main = self.ties['london-main-1']
        for duplicate in ({'winner': 'london-playoff-1'}, {'team': 'london-kr'}):
            extra = dict(main, id='london-main-3', slots=[duplicate, {'team': 'london-de'}])
            self.data['ties'].append(extra)
            with self.subTest(slot=duplicate), self.assertRaisesRegex(ValidationError, 'duplicate advancement|entered twice'):
                self.compiled_ties()
            self.data['ties'].pop()

    def test_rejects_incorrect_binding_and_nonofficial_aggregate(self):
        aggregate = self.ties['asian-sf-1']['official_result']
        binding = aggregate['result_for'][:]
        aggregate['result_for'].reverse()
        with self.assertRaisesRegex(ValidationError, 'official result_for'):
            self.compiled_ties()
        aggregate['result_for'] = binding

        for side in ('a', 'b'):
            self.data['sources'].append({'id': side, 'url': f'https://{side}.example.org/results', 'label': side,
                                         'kind': 'independent', 'family': f'{side}.example.org'})
        aggregate['verification']['source_ids'] = ['a', 'b']
        with self.assertRaisesRegex(ValidationError, 'official source is required'):
            self.compiled_ties()

    def test_official_completion_date_cannot_follow_verification(self):
        tie = self.ties['asian-sf-1']
        for value, error in [('2026-02-31', 'invalid completion date'), ('2026-11-10', 'verified before completion')]:
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, f'asian-sf-1: {error}'):
                tie['completed_date'] = value
                tie['official_result']['verification']['verified_at'] = '2026-11-09T12:00:00+08:00'
                self.compiled_ties()

    def test_knockout_bye_and_team_walkover_advance_without_games(self):
        semifinal = self.ties['asian-sf-1']
        verification = semifinal.pop('official_result')['verification']
        semifinal.pop('matches')
        semifinal['slots'][1] = {'bye': True}
        semifinal['bye_verification'] = verification
        bye = self.compiled_ties()['asian-sf-1']
        self.assertEqual((bye['status'], bye['score'], bye['winner']), ('bye', None, 'asian-cn'))

        del semifinal['bye_verification']
        semifinal['slots'][1] = {'team': 'asian-id'}
        semifinal['official_result'] = {'status': 'walkover', 'result_for': ['asian-cn', 'asian-id'],
                                       'winner': 1, 'reason': '示例整队弃权', 'verification': verification}
        ties = self.compiled_ties()
        walkover = ties['asian-sf-1']
        self.assertEqual((walkover['status'], walkover['score'], walkover['winner']), ('walkover', None, 'asian-id'))
        self.assertEqual([row['status'] for row in walkover['matches']], ['not_played'] * 5)
        self.assertEqual(ties['asian-final']['teams'], ['asian-id', 'asian-jp'])

    def test_invalid_association_is_rejected_and_compile_keeps_record(self):
        original = deepcopy(self.record)
        self.compiled_ties()
        self.assertEqual(self.record, original)
        by_id(self.data['teams'])['asian-cn']['team'] = 'ZZZ'
        with self.assertRaisesRegex(ValueError, 'asian-cn'):
            self.compiled_ties()

    def test_example_builds_catalog_entry_and_index_backlink(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sports/data').mkdir(parents=True)
            (root / 'sports/templates').mkdir()
            shutil.copy(EXAMPLE, root / 'sports/data/team-example.json')
            shutil.copy(SPORTS / 'templates/index.html', root / 'sports/templates/index.html')
            build(root=root)
            index = (root / INDEX).read_text(encoding='utf-8')
            self.assertIn('href="../../../team-bracket-example/index.html"', index)
            self.assertIn('乒羽团体赛录入示例（虚构）', index)
            output = (root / self.record['output']).read_text(encoding='utf-8')
            self.assertIn('href="../2026/11/20261104-1042-sports-brackets/index.html"', output)
            build(root=root, check=True)
