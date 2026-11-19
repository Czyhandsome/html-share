"""Lay out one independently sized section of an already validated bracket."""

from collections import defaultdict
from heapq import heappop, heappush
from itertools import groupby, pairwise
import re
import sys
from unicodedata import normalize


CARD_HEIGHT = 88
FINAL_HEIGHT = 150
ROW_GAP = 12
COLUMN_GAP = 95
QUALIFICATION = re.compile(
    r'^(?:(?:男子|女子|混合|男单|女单|男双|女双|混双)?(?:资格赛|资格轮|资格小组|资格附加赛|预选赛)'
    r'|qualifications?|qualifying|qualifiers?)'
    r'(?=\d|第|round|首|决赛|半决赛|final|semi-final|semifinal|[一二三四五六七八九十·(]|$)'
)
PLACEMENT = re.compile(
    r'^(?:季军赛|季军争夺战|铜牌赛|第三名赛|三四名决赛|3/4名决赛|排位赛|排名赛|'
    r'(?:third|3rd)-?place(?:match)?|bronze(?:medalmatch|match)?)'
    r'(?=第|[·(]|$)'
)
NAMED_ROUNDS = {
    '决赛': 2, '总决赛': 2, 'final': 2, 'grandfinal': 2,
    '半决赛': 4, '半决': 4, 'semifinal': 4, 'semi-final': 4, '四强': 4,
    '八强': 8, '四分之一决赛': 8, 'quarterfinal': 8, 'quarter-final': 8,
    '十六强': 16, '三十二强': 32, '六十四强': 64, '一百二十八强': 128,
}
ROUND_NUMBERS = {'首': 1, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                 '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _normalized(label):
    return re.sub(r'\s+', '', normalize('NFKC', label).casefold())


def section_for(round_name):
    label = _normalized(round_name)
    if QUALIFICATION.match(label):
        return 'qualification'
    if PLACEMENT.match(label):
        return 'placement'
    return 'main'


def _round_size(label):
    sizes = set()
    for part in label.split('·'):
        if part in NAMED_ROUNDS:
            sizes.add(NAMED_ROUNDS[part])
            continue
        match = re.fullmatch(r'(\d+)(?:强(?:赛)?|进(\d+))|(?:roundof|r)(\d+)|1/(\d+)决赛', part)
        if match is None:
            continue
        if match[4]:
            size = 2 * int(match[4])
        else:
            size = int(match[1] or match[3])
        if size >= 2 and not size & (size - 1) and (not match[2] or 2 * int(match[2]) == size):
            sizes.add(size)
    return next(iter(sizes)) if len(sizes) == 1 else None


def is_final_round(round_name):
    label = _normalized(round_name)
    return section_for(round_name) == 'main' and _round_size(label) == 2


def _qualification_number(label):
    match = re.search(r'(?:第?([一二三四五六七八九十首\d]+)轮|round(\d+))', label)
    if match is None:
        return None
    number = match[1] or match[2]
    return int(number) if number.isascii() and number.isdecimal() else ROUND_NUMBERS.get(number)


def _topological_order(predecessors):
    """Return a stable order and whether its dependencies determine a unique order."""
    rank = {ident: index for index, ident in enumerate(predecessors)}
    successors = defaultdict(list)
    missing = {}
    ready = []
    for ident, sources in predecessors.items():
        missing[ident] = len(sources)
        if not sources:
            heappush(ready, (rank[ident], ident))
        for source in sources:
            successors[source].append(ident)
    order = []
    unique = True
    while ready:
        unique = unique and len(ready) == 1
        _, ident = heappop(ready)
        order.append(ident)
        for target in successors[ident]:
            missing[target] -= 1
            if missing[target] == 0:
                heappush(ready, (rank[target], target))
    return order, unique and len(order) == len(predecessors)


def _round_keys(matches, feeders, order, qualification):
    keys = {}
    for match in matches.values():
        label = _normalized(match['round'])
        if qualification:
            number = _qualification_number(label)
            keys[match['id']] = ('number', number) if number is not None else ('label', label)
        else:
            size = _round_size(label)
            keys[match['id']] = ('size', size) if size is not None else ('label', label)
    if not qualification:
        return keys

    # Different depths with the same unnumbered qualification label are successive
    # rounds. Numbered rounds remain grouped even for seeds with no local feeder.
    repeated = {keys[target] for target, sources in feeders.items()
                for _, source in sources if keys[source] == keys[target] and keys[target][0] == 'label'}
    depth = {}
    for ident in order:
        depth[ident] = max((depth[source] + 1 for _, source in feeders[ident]), default=0)
    for ident, key in keys.items():
        if key in repeated:
            keys[ident] = ('depth', depth[ident])
    return keys


def _automatic_columns(keys, feeders):
    columns = defaultdict(list)
    for ident, key in keys.items():
        columns[key].append(ident)
    predecessors = {key: set() for key in columns}
    for target, candidates in feeders.items():
        for _, source in candidates:
            predecessors[keys[target]].add(keys[source])

    for kind, reverse in (('size', True), ('number', False), ('depth', False)):
        known = sorted((key for key in columns if key[0] == kind), reverse=reverse)
        for earlier, later in pairwise(known):
            predecessors[later].add(earlier)
    ordered, unique = _topological_order(predecessors)
    return [columns[key] for key in ordered] if unique else None


def _explicit_conflicts(columns, matches, feeders):
    if not isinstance(columns, list) or any(not isinstance(column, list) or not column for column in columns):
        return set(matches) or {'(no matches)'}

    positions = {}
    conflicts = set()
    for index, column in enumerate(columns):
        for ident in column:
            if not isinstance(ident, str):
                conflicts.update(matches)
                continue
            if ident in positions or ident not in matches:
                conflicts.add(ident)
            positions[ident] = index
    conflicts.update(matches.keys() - positions.keys())
    if conflicts:
        return conflicts
    for target, candidates in feeders.items():
        for _, source in candidates:
            if positions[source] >= positions[target]:
                conflicts.update((source, target))
    return conflicts


def _columns(columns, matches, starts=None):
    if starts is None:
        starts = [0] * len(columns)
    return [
        {'x': x, 'labels': list(dict.fromkeys(matches[ident]['round'].strip() or '轮次待核实' for ident in ids)), 'ids': ids}
        for x, ids in zip(starts, columns)
    ]


def _fallback(columns, matches):
    return {'columns': _columns(columns, matches), 'boxes': {}, 'paths': [],
            'width': 385, 'height': 0, 'fallback': True}


def _warn(context, conflicts):
    labels = ', '.join(sorted(conflicts))
    location = f' {context}' if context else ''
    print(f'Bracket layout{location}: conflicting or incomplete round hints for {labels}; using round list.',
          file=sys.stderr)


def _centers(matches, feeders, order, columns, final_id, explicit):
    used = {source for candidates in feeders.values() for _, source in candidates}
    roots = [ident for ident in matches if ident not in used]
    if explicit:
        root_for = {root: root for root in roots}
        for ident in reversed(order):
            for _, source in feeders[ident]:
                root_for[source] = root_for[ident]
        root_dependencies = {root: set() for root in roots}
        for column in columns:
            for previous, current in pairwise(root_for[ident] for ident in column):
                if previous != current:
                    root_dependencies[current].add(previous)
        ordered_roots, _ = _topological_order(root_dependencies)
        if len(ordered_roots) == len(roots):
            roots = ordered_roots

    final_shares_column = any(final_id in ids and len(ids) > 1 for ids in columns)
    pitch = (FINAL_HEIGHT if final_shares_column else CARD_HEIGHT) + ROW_GAP
    centers = {}
    next_row = pitch / 2
    stack = [(root, False) for root in reversed(roots)]
    # Walk upstream in slot order so adjacent subtrees use disjoint rows.
    while stack:
        ident, visited = stack.pop()
        candidates = feeders[ident]
        if not candidates:
            centers[ident] = next_row
            next_row += pitch
        elif visited:
            y = [centers[source] for _, source in candidates]
            centers[ident] = sum(y) / len(y)
        else:
            stack.append((ident, True))
            stack.extend((source, False) for _, source in reversed(candidates))
    return centers


def _paths(columns, feeders, boxes, round_sizes, final_id, ports, final_ports):
    positions = {ident: index for index, ids in enumerate(columns) for ident in ids}
    routes = defaultdict(list)
    for target, sides in feeders.items():
        x, top, _, _ = boxes[target]
        offsets = final_ports if target == final_id else ports
        for slot, source in sides:
            index = positions[source]
            if positions[target] != index + 1:
                continue
            source_size, target_size = round_sizes.get(source), round_sizes.get(target)
            if source_size is not None and target_size is not None and source_size != 2 * target_size:
                continue
            sx, _, width, sy = boxes[source]
            end_y = top + offsets[slot]
            bend = sx + width + COLUMN_GAP / 2
            path = f'M{sx + width:g} {sy:g}H{bend:g}V{end_y:g}H{x:g}'
            routes[index].append((min(sy, end_y), max(sy, end_y), source, target, slot, path))

    paths = []
    for candidates in routes.values():
        ceiling = float('-inf')
        for low, high, source, target, slot, path in sorted(candidates):
            # A common midpoint is safe only for disjoint vertical spans in a gutter.
            if low > ceiling:
                paths.append({'from': source, 'to': target, 'slot': slot, 'd': path})
                ceiling = high
    return paths


def plan_board(matches, *, explicit_columns=None, qualification=False, context='', final_id=None,
               ports=(19.5, 50.5), final_ports=(68.5, 99.5)):
    """Return card rectangles, slot-indexed paths, or dependency-ordered list groups."""
    matches = {match['id']: match for match in matches}
    feeders = {
        ident: [(slot, selector['winner']) for slot, selector in enumerate(match['slots'])
                if selector.get('winner') in matches]
        for ident, match in matches.items()
    }
    order, _ = _topological_order({ident: {source for _, source in sources} for ident, sources in feeders.items()})
    keys = _round_keys(matches, feeders, order, qualification)
    explicit = explicit_columns is not None
    conflicts = _explicit_conflicts(explicit_columns, matches, feeders) if explicit else set()
    if conflicts:
        _warn(context, conflicts)
    automatic = _automatic_columns(keys, feeders)
    columns = explicit_columns if explicit and not conflicts else automatic
    if conflicts or columns is None:
        list_columns = automatic if automatic is not None else [
            list(ids) for _, ids in groupby(order, key=keys.get)
        ]
        return _fallback(list_columns, matches)

    centers = _centers(matches, feeders, order, columns, final_id, explicit)
    ordered_columns = [sorted(ids, key=centers.get) for ids in columns]
    if explicit and columns != ordered_columns:
        conflicts = {wanted for column, actual in zip(columns, ordered_columns)
                     for wanted, placed in zip(column, actual) if wanted != placed}
        _warn(context, conflicts)
        return _fallback(columns, matches)

    widths = [385, 375][:max(0, len(columns) - 1)] + [295] * max(0, len(columns) - 3) + [340]
    starts = [0]
    for width in widths[:-1]:
        starts.append(starts[-1] + width + COLUMN_GAP)
    heights = {ident: FINAL_HEIGHT if ident == final_id else CARD_HEIGHT for ident in matches}
    first_top = min((centers[ident] - height / 2 for ident, height in heights.items()), default=0)
    padding = max(0, ROW_GAP / 2 - first_top)
    boxes = {
        ident: (x, centers[ident] + padding - heights[ident] / 2, width, centers[ident] + padding)
        for x, width, ids in zip(starts, widths, ordered_columns) for ident in ids
    }
    height = max((box[1] + heights[ident] + ROW_GAP for ident, box in boxes.items()), default=0)
    # Explicit columns are authoritative about which labels denote adjacent rounds.
    round_sizes = {ident: size for ident, (kind, size) in keys.items() if kind == 'size'} if not explicit else {}
    paths = _paths(ordered_columns, feeders, boxes, round_sizes, final_id, ports, final_ports)
    return {'columns': _columns(ordered_columns, matches, starts), 'boxes': boxes, 'paths': paths,
            'width': starts[-1] + widths[-1] + 2, 'height': height, 'fallback': False}
