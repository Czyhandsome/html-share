from collections import Counter
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import random
import unittest

from sports.core.board import plan_draw
from sports.core.board_layout import plan_board
from sports.core.bracketkit import compile_data, load, render
from sports.core.team_board import render_team
from sports.core.team_bracket import compile_team_record


SPORTS = Path(__file__).resolve().parents[1]
EXAMPLES = SPORTS / 'core' / 'examples'


def card(ident, round_name, *slots):
    slots = list(slots) + [{'tbd': '待定'} for _ in range(2 - len(slots))]
    return {
        'id': ident, 'round': round_name, 'group': None, 'slots': slots,
        'feeders': [slot['winner'] for slot in slots if 'winner' in slot],
    }


def columns(board):
    return [column['ids'] for column in board['columns']]


def edges(board):
    return {(path['from'], path['to'], path['slot']) for path in board['paths']}


def project_hong_kong():
    record = load(SPORTS / 'data' / 'hong-kong-open-2026.json')
    return [card(match['id'], match['round'], *match['slots'])
            for match in record['data']['matches'] if match['draw'] == 'MS']


class BracketLayoutTests(unittest.TestCase):
    def test_hong_kong_keeps_all_main_edges_and_two_qualifying_rounds(self):
        sections, plans = plan_draw(project_hong_kong(), {}, '香港公开赛 / MS')
        self.assertEqual(list(map(len, columns(plans['qualification']))), [8, 4])
        self.assertEqual(list(map(len, columns(plans['main']))), [16, 8, 4, 2, 1])
        for section, expected in [('main', 30), ('qualification', 8)]:
            local = {match['id'] for match in sections[section]}
            referenced = {
                (slot['winner'], match['id'], index)
                for match in sections[section] for index, slot in enumerate(match['slots'])
                if slot.get('winner') in local
            }
            self.assertEqual(len(referenced), expected)
            self.assertEqual(edges(plans[section]), referenced)

    def test_main_geometry_survives_qualifier_changes_and_result_only_updates(self):
        original = project_hong_kong()
        _, plans = plan_draw(deepcopy(original), {}, '香港公开赛 / MS')
        expected = plans['main']
        variants = [
            [match for match in original if match['round'] != '资格赛'],
            [card('extra', '资格赛', {'entry': 'a'}, {'entry': 'b'}), *original],
            [dict(match, status='completed', scores=[2, 1]) for match in original],
        ]
        shuffled = deepcopy(original)
        random.Random(2026).shuffle(shuffled)
        variants.append(shuffled)
        for variant in variants:
            with self.subTest(matches=len(variant)):
                _, variant_plans = plan_draw(deepcopy(variant), {}, '香港公开赛 / MS')
                self.assertEqual(variant_plans['main']['boxes'], expected['boxes'])
                self.assertEqual(variant_plans['main']['width'], expected['width'])
                self.assertEqual(variant_plans['main']['height'], expected['height'])
                self.assertEqual(edges(variant_plans['main']), edges(expected))

    def test_explicit_main_round_aliases_and_input_slots_control_geometry(self):
        matches = [
            card('lower', '1/4 决赛', {'bye': True}, {'entry': 'b'}),
            card('upper', '八强'),
            card('semi', '半决赛', {'winner': 'upper'}, {'winner': 'lower'}),
            card('other', '四分之一决赛'),
        ]
        diagram = plan_board(matches)
        self.assertEqual(columns(diagram), [['upper', 'lower', 'other'], ['semi']])
        self.assertEqual(edges(diagram), {('upper', 'semi', 0), ('lower', 'semi', 1)})
        self.assertLess(diagram['boxes']['upper'][3], diagram['boxes']['lower'][3])

    def test_one_quarterfinal_is_not_a_qualification_or_championship(self):
        quarter = card('quarter', '八强')
        bronze = card('bronze', '季军赛')
        sections, _ = plan_draw([quarter, bronze], {}, '样例')
        self.assertEqual([match['id'] for match in sections['main']], ['quarter'])
        self.assertEqual([match['id'] for match in sections['placement']], ['bronze'])
        self.assertFalse(quarter.get('isFinal', False))
        self.assertFalse(bronze.get('isFinal', False))

    def test_128_player_main_draw_stays_in_the_same_section(self):
        first_column = [card(f'128-{index}', '128进64') for index in range(64)]
        matches = first_column.copy()
        previous = first_column
        for size in (64, 32, 16, 8, 4, 2):
            name = f'{size}进{size // 2}' if size > 2 else '决赛'
            current = [
                card(f'{size}-{index}', name, *({'winner': source['id']} for source in previous[2 * index:2 * index + 2]))
                for index in range(size // 2)
            ]
            matches.extend(current)
            previous = current
        sections, plans = plan_draw(matches, {}, '128 人签表')
        self.assertEqual(len(sections['main']), 127)
        self.assertNotIn('qualification', plans)
        self.assertEqual(list(map(len, columns(plans['main']))), [64, 32, 16, 8, 4, 2, 1])
        self.assertEqual(len(edges(plans['main'])), 126)

    def test_ambiguous_round_order_keeps_a_list_and_exact_skip_is_not_drawn(self):
        early = card('early', '八强')
        middle = card('middle', '半决赛')
        final = card('final', '决赛', {'winner': 'early'}, {'winner': 'middle'})
        diagram = plan_board([final, early, middle])
        self.assertEqual(columns(diagram), [['early'], ['middle'], ['final']])
        self.assertEqual(edges(diagram), {('middle', 'final', 1)})

        first = card('first', '甲轮')
        second = card('second', '乙轮', {'winner': 'first'})
        third = card('third', '甲轮', {'winner': 'second'})
        fallback = plan_board([third, second, first])
        self.assertTrue(fallback['fallback'])
        self.assertEqual(columns(fallback), [['first'], ['second'], ['third']])
        self.assertEqual(edges(fallback), set())

    def test_incompatible_individual_round_hints_keep_both_link_directions(self):
        data = load(EXAMPLES / 'knockout.json')
        data['layout'] = {'main': {'rounds': {'main': [['F'], ['SF1', 'SF2']]}}}
        log = StringIO()
        with redirect_stderr(log):
            page = render(compile_data(data))
        self.assertIn('class="round-list"', page)
        self.assertIn(' / main / main', log.getvalue())
        self.assertIn('SF1', log.getvalue())
        payload = page.split('id="wtt-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        matches = {match['id']: match for match in json.loads(payload)['draws']['main']}
        actual = Counter((link['direction'], link['from'], link['to'], link['slot'], link['target'])
                         for match in matches.values() for link in match['links'])
        expected = Counter()
        for slot, feeder in enumerate(['SF1', 'SF2']):
            expected[('source', feeder, 'F', slot, matches[feeder]['domId'])] += 1
            expected[('destination', feeder, 'F', slot, matches['F']['domId'])] += 1
        self.assertEqual(actual, expected)

    def test_incomplete_team_round_hints_keep_the_recorded_ties(self):
        record = load(EXAMPLES / 'team-bracket.json')
        record['data']['layout'] = {'thomas-final': {'rounds': [['thomas-title']]}}
        log = StringIO()
        with redirect_stderr(log):
            page = render_team(compile_team_record(record))
        self.assertIn('class="round-list"', page)
        self.assertIn('thomas-final', log.getvalue())
        self.assertIn('thomas-sf-2', log.getvalue())
        for ident in ('thomas-final-1', 'thomas-sf-2', 'thomas-title'):
            self.assertEqual(page.count(f'data-team-tie="{ident}"'), 1)
