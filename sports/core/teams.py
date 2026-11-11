"""Resolve tournament association codes and load the checked-in flag assets."""

import base64
from functools import cache
import json
from pathlib import Path


VENDOR = Path(__file__).resolve().parents[1] / 'vendor' / 'team-flags'


@cache
def registry():
    return json.loads((VENDOR / 'teams.json').read_text(encoding='utf-8'))


@cache
def flag_license():
    return (VENDOR / 'LICENSE').read_text(encoding='utf-8')


def team_codes(value):
    """Resolve one association or the two associations of a doubles pair."""
    if not isinstance(value, str):
        raise ValueError('team must be a string')
    if not value:
        return ()
    codes = value.split('/')
    if len(codes) > 2:
        raise ValueError('team expects one code or two codes separated by /')
    data = registry()
    resolved = tuple(data['aliases'].get(code, code) for code in codes)
    for code in resolved:
        if code not in data['teams']:
            raise ValueError(f'unregistered team code {code!r}')
    if len(resolved) == 2 and resolved[0] == resolved[1]:
        raise ValueError('use a single team code for a same-association pair')
    return resolved


@cache
def _flag_uri(filename):
    try:
        svg = (VENDOR / filename).read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f'missing team flag {filename}') from exc
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg).decode('ascii')


def team_assets(codes):
    countries, flags = {}, {}
    teams = registry()['teams']
    for code in sorted(set(codes)):
        team = teams[code]
        countries[code] = team['name']
        if team['flag'] is not None:
            flags[code] = _flag_uri(team['flag'])
    return {'countries': countries, 'flags': flags}


def validate_entry_teams(entries, *, allow_empty=False):
    errors = []
    for entry in entries:
        try:
            codes = team_codes(entry.get('team'))
            if not codes and not allow_empty:
                raise ValueError('team is required for a real entry')
            team_assets(codes)
        except ValueError as exc:
            errors.append(f'entry {entry["id"]}: {exc}')
    if errors:
        raise ValueError('\n'.join(errors))
