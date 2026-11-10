#!/usr/bin/env python3
"""Build the tournament HTML and catalog from the repository's records."""
import argparse
import html
from pathlib import Path
import re
from posixpath import relpath
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sports.compiler import compile_record
from sports.core.bracketkit import load, render
from sports.legacy import KINDS, render_record

INDEX = 'docs/2026/11/20261104-1042-sports-brackets/index.html'


def build(check=False, root=ROOT):
    root = root.resolve()
    docs = root / 'docs'
    index = root / INDEX
    pending = {}
    record_ids = set()
    links = []
    backlinks = []
    for source in sorted((root / 'sports/data').iterdir()):
        if source.suffix.lower() not in {'.json', '.yaml', '.yml'}:
            continue
        try:
            record = load(source)
            target = (root / record['output']).resolve()
            if not target.is_relative_to(docs) or target.suffix != '.html' or target in {index, docs / 'index.html'}:
                raise ValueError('unsafe output')
            if target in pending or record['id'] in record_ids:
                raise ValueError('duplicate output or record ID')
            record_ids.add(record['id'])
            if record['kind'] == 'bracket-v1':
                model = compile_record(record, root)
                backlink = model['event'].setdefault('back_link', relpath(index, target.parent))
                backlinks.append((target, (target.parent / backlink).resolve()))
                page = render(model)
            elif record['kind'] in KINDS:
                page = render_record(record, root)
            else:
                raise ValueError('unknown adapter')
            title = re.search(r'<title>(.*?)</title>', page, re.DOTALL)
            if not title:
                raise ValueError('generated page needs a title')
            links.append((target, html.escape(html.unescape(title[1].strip()))))
            pending[target] = page
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'{source.name}: {exc}') from exc

    for target, backlink in backlinks:
        if (not backlink.is_relative_to(docs) or backlink == target or
                (backlink not in pending and backlink != index and not backlink.is_file())):
            raise ValueError(f'{target.relative_to(root)}: invalid return link {backlink}')
    items = '\n'.join(f'<li><a href="{quote(relpath(target, index.parent))}">{title}</a></li>'
                      for target, title in sorted(links, reverse=True))
    template = (root / 'sports/templates/index.html').read_text(encoding='utf-8')
    pending[index] = template.replace('{{events}}', items)
    # Compile every record and validate navigation before touching the output files.
    for target, page in pending.items():
        if check:
            if not target.is_file() or target.read_text(encoding='utf-8') != page:
                raise ValueError(f'generated output stale: {target.relative_to(root)}')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding='utf-8')
    print(f'Validated {len(links)} tournament pages and their index')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        build(args.check)
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')
