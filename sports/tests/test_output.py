import json
import shutil
import tempfile
from pathlib import Path
from html.parser import HTMLParser
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'core'))
from bracketkit import compile_data,render,load,ValidationError
from sports.build import INDEX, build
ROOT=Path(__file__).resolve().parents[1] / 'core'
class Inspect(HTMLParser):
 def __init__(self):
  super().__init__();self.ids=[];self.matches=[];self.external_assets=[];self.back=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if 'id' in d:self.ids.append(d['id'])
  if 'data-match-id' in d:self.matches.append(d['data-match-id'])
  if tag in ('script','img','iframe') and 'src' in d:self.external_assets.append(d['src'])
  if tag=='link':self.external_assets.append(d.get('href'))
  if tag=='a' and d.get('href')=='index.html':self.back.append(True)
class OutputTests(unittest.TestCase):
 def test_examples_have_unique_ids_and_one_card_per_match(self):
  for file in (ROOT/'examples').glob('*.json'):
   with self.subTest(file=file):
    model=compile_data(load(file));page=render(model);p=Inspect();p.feed(page)
    self.assertEqual(len(p.ids),len(set(p.ids)))
    self.assertEqual(p.matches,[m['id'] for m in model['matches']])
    self.assertEqual(p.external_assets,[]);self.assertEqual(len(p.back),1)
    self.assertEqual(page,render(compile_data(load(file))))
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
   record = {'id': 'example', 'kind': 'bracket-v1', 'output': target, 'data': data}
   (root/'sports/data/example.json').write_text(json.dumps(record), encoding='utf-8')
   build(root=root)
   self.assertIn('../../../example/index.html', (root/INDEX).read_text())
   self.assertIn('data-match-id=', (root/target).read_text())
   build(check=True, root=root)
