#!/usr/bin/env python3
"""Build the tournament HTML and catalog from the repository's records."""
import argparse
from datetime import date
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


def parse_event_dates(record):
    if 'event_dates' not in record:
        return None, None, None
    values = record['event_dates']
    if (not isinstance(values, dict) or not {'start', 'end'} <= values.keys()
            or values.keys() - {'start', 'end', 'snapshot'}):
        raise ValueError('event_dates needs start and end, with an optional snapshot')

    def read(key):
        value = values[key]
        if type(value) is date:  # YAML may resolve a plain scalar to a date.
            return value
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            raise ValueError(f'event_dates.{key} must be YYYY-MM-DD')
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f'invalid event_dates.{key}: {value}') from exc

    start, end = read('start'), read('end')
    if end < start:
        raise ValueError('event_dates.end precedes start')
    return start, end, read('snapshot') if 'snapshot' in values else None


def catalog_date(value, *, year=True):
    prefix = f'{value.year}年' if year else ''
    return f'<time datetime="{value.isoformat()}">{prefix}{value.month}月{value.day}日</time>'


def catalog_item(target, title, start, end, snapshot, parent):
    dates = ''
    if start is not None:
        span = catalog_date(start)
        if start != end:
            span += '–' + catalog_date(end, year=end.year != start.year)
        dates = f'<span class="event-date">{span}</span>'
        if snapshot is not None:
            dates += f'<span class="snapshot-date">快照 {catalog_date(snapshot)}</span>'
    return f'<li><a href="{quote(relpath(target, parent))}">{title}{dates}</a></li>'


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
            start, end, snapshot = parse_event_dates(record)
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
            links.append((target, html.escape(html.unescape(title[1].strip())), start, end, snapshot))
            pending[target] = page
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'{source.name}: {exc}') from exc

    for target, backlink in backlinks:
        if (not backlink.is_relative_to(docs) or backlink == target or
                (backlink not in pending and backlink != index and not backlink.is_file())):
            raise ValueError(f'{target.relative_to(root)}: invalid return link {backlink}')
    links.sort(key=lambda link: (link[2] is not None, link[2] or date.min, link[4] or date.min), reverse=True)
    items = '\n'.join(catalog_item(*link, index.parent) for link in links)
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
