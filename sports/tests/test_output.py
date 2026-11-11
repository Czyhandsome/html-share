from copy import deepcopy
import json
import shutil
import tempfile
from pathlib import Path
from html.parser import HTMLParser
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'core'))
from bracketkit import compile_data,render,load,ValidationError
from board import split_preliminaries
from sports.build import INDEX, build, parse_event_dates
from sports.core import teams
ROOT=Path(__file__).resolve().parents[1] / 'core'
class Inspect(HTMLParser):
 def __init__(self):
  super().__init__();self.ids=[];self.matches=[];self.external_assets=[];self.back=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if 'id' in d:self.ids.append(d['id'])
  if 'data-match-id' in d:self.matches.append(d['data-match-id'])
  if tag in ('script','img','iframe') and 'src' in d and not d['src'].startswith('data:'):self.external_assets.append(d['src'])
  if tag=='link' and not d.get('href','').startswith('data:'):self.external_assets.append(d.get('href'))
  if tag=='a' and d.get('href')=='index.html':self.back.append(True)
class OutputTests(unittest.TestCase):
 def test_examples_have_unique_ids_and_one_card_per_match(self):
  for file in (ROOT/'examples').glob('*.json'):
   with self.subTest(file=file):
    model=compile_data(load(file));page=render(model);p=Inspect();p.feed(page)
    self.assertEqual(len(p.ids),len(set(p.ids)))
    self.assertCountEqual(p.matches,[m['id'] for m in model['matches']])
    self.assertEqual(p.external_assets,[]);self.assertEqual(len(p.back),1)
    self.assertEqual(page,render(compile_data(load(file))))
 def test_appended_qualifier_stays_outside_main_bracket(self):
  main_draw = [
      {'id': 's1', 'round': '半决赛', 'feeders': ['q1']},
      {'id': 's2', 'round': '半决赛', 'feeders': []},
      {'id': 'f', 'round': '决赛', 'feeders': ['s1', 's2']},
  ]
  qualifier = {'id': 'q1', 'round': '资格赛', 'feeders': []}
  self.assertEqual(split_preliminaries(main_draw + [qualifier]), ([qualifier], main_draw))
 def test_yaml_json_equivalent(self):
  try:import yaml
  except ImportError:self.skipTest('PyYAML optional')
  self.assertEqual(load(ROOT/'examples/knockout.json'),load(ROOT/'examples/knockout.yaml'))
 def test_yaml_duplicate_keys_rejected(self):
  try:import yaml
  except ImportError:self.skipTest('PyYAML optional')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.yaml';p.write_text('x: 1\nx: 2\n')
   with self.assertRaises(ValidationError):load(p)
 def test_nonfinite_json_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.json';p.write_text('{"x": NaN}')
   with self.assertRaises(ValidationError):load(p)
 def test_index_targets_exist(self):
  class Links(HTMLParser):
   def handle_starttag(self,tag,attrs):
    if tag=='a':self.targets.append(dict(attrs)['href'])
  index=ROOT.parent.parent/'docs/2026/11/20261104-1042-sports-brackets/index.html'
  p=Links();p.targets=[];p.feed(index.read_text())
  self.assertTrue(p.targets)
  for target in p.targets:self.assertTrue((index.parent/target).is_file())
 def test_new_data_record_builds_page_and_updates_index(self):
  with tempfile.TemporaryDirectory() as directory:
   root = Path(directory)
   (root/'sports/data').mkdir(parents=True)
   (root/'sports/templates').mkdir()
   shutil.copy(ROOT.parent/'templates/index.html', root/'sports/templates/index.html')
   data = load(ROOT/'examples/knockout.json')
   data['event'].pop('back_link')
   target = 'docs/example/index.html'
   record = {'kind': 'bracket-v1', 'data': data}
   examples = [
       ('a-undated', 'docs/2099/undated/index.html', None),
       ('b-current', target, {'start': '2026-11-10', 'end': '2026-11-15'}),
       ('c-earlier', 'docs/2099/earlier/index.html', {
           'start': '2026-07-17', 'end': '2026-07-19', 'snapshot': '2026-07-17'}),
       ('d-later', 'docs/1999/later/index.html', {
           'start': '2026-07-17', 'end': '2026-07-19', 'snapshot': '2026-07-18'}),
   ]
   for ident, output, dates in examples:
    example = dict(record, id=ident, output=output)
    if dates is not None:
     example['event_dates'] = dates
    (root/'sports/data'/f'{ident}.json').write_text(json.dumps(example), encoding='utf-8')
   build(root=root)
   index = (root/INDEX).read_text(encoding='utf-8')
   links = [f'../../../{page}/index.html' for page in ('example', '1999/later', '2099/earlier', '2099/undated')]
   positions = [index.index(f'href="{link}"') for link in links]
   self.assertEqual(positions, sorted(positions))
   self.assertIn('<time datetime="2026-11-10">2026年11月10日</time>–<time datetime="2026-11-15">11月15日</time>', index)
   self.assertIn('快照 <time datetime="2026-07-18">2026年7月18日</time>', index)
   self.assertIn('data-match-id=', (root/target).read_text())
   build(check=True, root=root)
 def test_team_metadata_renders_aliases_mixed_pairs_and_neutral_entries(self):
  data = load(ROOT/'examples/knockout.json')
  data['entries'][0].update(name='示例组合甲／乙', team='GB-ENG/CHN')
  data['entries'][1]['team'] = 'AIN'
  data['entries'].append({'id': 'unused', 'name': 'Unused', 'team': 'KOR'})
  page = render(compile_data(data))
  assets = json.loads(page.split('id="wtt-assets" type="application/json">', 1)[1].split('</script>', 1)[0])
  view = json.loads(page.split('id="wtt-data" type="application/json">', 1)[1].split('</script>', 1)[0])
  first_match = view['draws']['main'][0]
  self.assertEqual([player['teams'] for player in first_match['players']], [['ENG', 'CHN'], ['AIN']])
  self.assertEqual(assets['countries']['ENG'], '英格兰')
  self.assertIn('中立', assets['countries']['AIN'])
  self.assertEqual(set(assets['flags']), {'CHN', 'ENG', 'GER'})
  self.assertNotIn('KOR', assets['countries'])
  self.assertIn('class="match done contains-cn"', page)
  self.assertIn('class="team-badge neutral"', page)
  self.assertIn('The MIT License', page)

 def test_build_rejects_invalid_real_entry_teams(self):
  with tempfile.TemporaryDirectory() as directory:
   root = Path(directory)
   (root/'sports/data').mkdir(parents=True)
   data = load(ROOT/'examples/knockout.json')
   record = {'id': 'event', 'kind': 'bracket-v1', 'output': 'docs/example/index.html', 'data': data}
   entry = data['entries'][0]
   data_file = root/'sports/data/event.json'
   for code, problem in [(None, 'team must be a string'), ('', 'team is required'), ('ZZZ', 'unregistered team code'),
                         ('CHN', 'missing team flag')]:
    with self.subTest(code=code):
     entry['team'] = code
     data_file.write_text(json.dumps(record), encoding='utf-8')
     registry = deepcopy(teams.registry())
     registry['teams']['CHN']['flag'] = 'missing-test-flag.svg'
     with patch.object(teams, 'registry', return_value=registry), self.assertRaisesRegex(
         ValueError, rf'event\.json: entry {entry["id"]}: {problem}'
     ):
      build(root=root)

 def test_catalog_event_dates_reject_invalid_input(self):
  for start, end in [('2026-1-01', '2026-01-02'), ('2026-02-30', '2026-03-01'), ('2026-01-02', '2026-01-01')]:
   with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, 'event_dates'):
    parse_event_dates({'event_dates': {'start': start, 'end': end}})
 def test_catalog_event_dates_load_yaml_dates(self):
  try:import yaml
  except ImportError:self.skipTest('PyYAML optional')
  with tempfile.TemporaryDirectory() as directory:
   path = Path(directory) / 'event.yaml'
   path.write_text('event_dates:\n  start: 2026-11-10\n  end: 2026-11-15\n')
   dates = parse_event_dates(load(path))
   self.assertEqual([value.isoformat() for value in dates[:2]], ['2026-11-10', '2026-11-15'])
