"""Strict compiler plus fingerprinted, explicitly unverified legacy imports.

Migration locks are integrity guardrails, not an authorization/security boundary.
An audited pending release records the maintenance decision; it does not itself
prove user authorization or relax the core result evidence requirements.
"""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'core'))
from bracketkit import Compiler, ValidationError, require, timestamp, render


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def match_context(data, match):
    """Bind meaning, not just IDs. Unreferenced new sources/entries remain allowed."""
    entry_ids = set(match.get('result_for', []))
    entry_ids.update(s['entry'] for s in match['slots'] if 'entry' in s)
    source_ids = set(match.get('verification', {}).get('source_ids', []))
    source_ids.update(match.get('schedule_verification', {}).get('source_ids', []))
    entries = {e['id']: e for e in data['entries']}
    sources = {s['id']: s for s in data.get('sources', [])}
    predecessors = {}
    if not match.get('result_for'):
        matches = {m['id']: m for m in data['matches']}
        seen = set()
        def visit(ident):
            if ident in seen or ident not in matches:
                return
            seen.add(ident)
            feeder = matches[ident]
            predecessors[ident] = {k: feeder.get(k) for k in ('status', 'result_for', 'games', 'winner', 'slots')}
            entry_ids.update(feeder.get('result_for', []))
            entry_ids.update(s['entry'] for s in feeder['slots'] if 'entry' in s)
            for slot in feeder['slots']:
                if 'winner' in slot:
                    visit(slot['winner'])
        for slot in match['slots']:
            if 'winner' in slot:
                visit(slot['winner'])
    return {'predecessors': predecessors, 'entries': {k: entries.get(k) for k in sorted(entry_ids)},
            'sources': {k: sources.get(k) for k in sorted(source_ids)},
            'rule': data['rules'].get(match['rule'])}


class MigratedCompiler(Compiler):
    def __init__(self, data, inherited, locks, contexts=None, pending=None, releases=None):
        self.inherited, self.locks = inherited, locks
        contexts, pending, releases = contexts or {}, pending or {}, releases or {}
        require(isinstance(inherited, dict) and isinstance(releases, dict), 'migration metadata must be objects')
        matches = {m['id']: m for m in data['matches']}
        for ident, meta in inherited.items():
            require(ident in locks and ident in matches, 'import not present in migration lock/data: ' + ident)
            require(isinstance(meta, dict) and isinstance(meta.get('notice'), str) and meta['notice'].strip(),
                    'inherited record needs an explicit notice')
            require(fingerprint(matches[ident]) == locks[ident],
                    ident + ': imported match changed; remove its inherited marker and provide newly verified evidence')
            require(ident in contexts and fingerprint(match_context(data, matches[ident])) == contexts[ident],
                    ident + ': imported entry/source/rule context changed; newly verified evidence required')
        for ident, release in releases.items():
            require(ident in pending, 'release must name a locked pending match: ' + ident)
            require(isinstance(release, dict) and set(release) == {'reason', 'authorization'},
                    'pending release needs reason and authorization reference')
            require(all(isinstance(release[k], str) and release[k].strip() for k in release),
                    'pending release reason/authorization must be nonempty text')
        for ident, lock in pending.items():
            require(ident in matches, 'locked pending match missing: ' + ident)
            if ident in releases:
                continue
            require(fingerprint(matches[ident]) == lock['match'] and
                    fingerprint(match_context(data, matches[ident])) == lock['context'],
                    ident + ': pending baseline changed; explicit migration_releases record required')
        super().__init__(data)

    def evidence(self, verification, where):
        if where not in self.inherited:
            return super().evidence(verification, where)
        # No assertion of official status or independence is made for carried evidence.
        require(isinstance(verification, dict), 'import must retain source links')
        ids = verification.get('source_ids', [])
        require(ids and all(x in self.sources for x in ids), 'invalid imported source ids')
        require(timestamp(verification['verified_at']) <= self.snapshot, 'invalid import timestamp')
        return ids

    def compile(self):
        model = super().compile()
        for m in model['matches']:
            if m['id'] in self.inherited:
                m['verification_status'] = 'imported_unverified'
                m['migration_notice'] = self.inherited[m['id']]['notice']
        return model


def compile_record(record, root):
    data = record['data']
    inherited = record.get('inherited_evidence', {})
    lock_path = root / 'sports/migration-lock.json'
    lockfile = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    ident = record['id']
    model = MigratedCompiler(data, inherited, lockfile.get('matches', {}).get(ident, {}),
                             lockfile.get('contexts', {}).get(ident, {}),
                             lockfile.get('pending', {}).get(ident, {}),
                             record.get('migration_releases', {})).compile()
    model['notices'] = record.get('notices', [])
    if record.get('migration_releases'):
        model['migration_releases'] = record['migration_releases']
    return model
