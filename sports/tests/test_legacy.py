import copy
import json
from pathlib import Path
import re
import subprocess
import unittest
from sports.legacy import render_record

ROOT = Path(__file__).resolve().parents[2]
RECORDS = [json.loads(p.read_text()) for p in sorted((ROOT/'sports/data').glob('legacy-*.json'))]

class LegacyTests(unittest.TestCase):
    def test_all_four_render_and_reproduce_data(self):
        self.assertEqual(len(RECORDS), 4)
        for r in RECORDS:
            rendered = render_record(r, ROOT)
            self.assertNotIn('{{js:', rendered)
            self.assertNotIn('{{text:', rendered)
            self.assertIn('<canvas' if r['kind'] != 'worlds-swiss' else 'function renderSwissFlow()', rendered)
            # Only evaluate extracted JSON declarations, never UI or arbitrary template code.
            for key, value in r['data'].items():
                expression = re.search(r'const '+key+r' = (.*);', rendered).group(1)
                self.assertEqual(json.loads(expression), value)
            self.assertEqual(rendered, render_record(r, ROOT))

    def test_swiss_history_not_single_elimination(self):
        r = next(r for r in RECORDS if r['kind'] == 'worlds-swiss')
        self.assertEqual(sum(len(d[2]) for d in r['data']['swissDays']), 33)
        self.assertEqual(sum(len(d[2]) for d in r['data']['playinDays']), 6)
        self.assertEqual(len(r['data']['ko']), 7)
        self.assertNotIn('scores', r['data']['ko'][-1])
        bad = copy.deepcopy(r)
        bad['data']['ko'][0]['scores'] = [3, 0]
        with self.assertRaises(ValueError):render_record(bad, ROOT)

    def test_path_escape_and_archive_guard(self):
        for field, value in [('template','docs/index.html'),('template','sports/templates/../../../etc/passwd'),('output','sports/o.html'),('output','docs/../../x.html'),('template','/etc/passwd')]:
            bad = copy.deepcopy(RECORDS[0]);bad[field] = value
            with self.assertRaises(ValueError):render_record(bad, ROOT)
        archive = copy.deepcopy(next(r for r in RECORDS if r['kind']=='doubles-archive'))
        archive['maintenance']['mode']='live'
        with self.assertRaises(ValueError):render_record(archive, ROOT)

    def test_content_and_script_are_escaped(self):
        r = copy.deepcopy(RECORDS[0])
        k=next(iter(r['content']));r['content'][k]='<img src=x onerror=alert(1)>'
        output=render_record(r,ROOT)
        self.assertNotIn('<img src=x',output)
        self.assertIn('&lt;img src=x',output)
        r = copy.deepcopy(next(r for r in RECORDS if r['kind']=='prediction-archive'))
        r['data']['champ']['note']='</script><script>alert(1)</script>'
        output=render_record(r,ROOT)
        self.assertNotIn('</script><script>alert',output)

if __name__=='__main__':unittest.main()
