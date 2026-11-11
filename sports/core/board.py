"""Render the verified bracket model into the original connected-board UI."""
from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'
STATUS = {'scheduled': '待赛', 'live': '进行中', 'completed': '已完赛', 'retired': '退赛',
          'walkover': '弃权', 'bye': '轮空', 'cancelled': '取消'}


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c')


def split_preliminaries(matches):
    """Keep a sparse opening round that feeds the main draw beside the board."""
    rounds = defaultdict(list)
    for match in matches:
        rounds[match['round']].append(match)
    # Qualification results may be appended after the main draw in the source data.
    for first in rounds.values():
        seeds = {ident for match in first for ident in match['feeders']}
        for label, opening in rounds.items():
            if len(opening) * 2 <= len(first) and all(match['id'] in seeds for match in opening):
                return opening, [match for match in matches if match['round'] != label]
    return [], matches


def layout(matches):
    """Use round labels for draft columns and validated feeders for the wires."""
    by_id = {match['id']: match for match in matches}
    rounds = list(dict.fromkeys(match['round'] for match in matches))
    round_order = {name: index for index, name in enumerate(rounds)}
    position = {}

    def column(match):
        ident = match['id']
        if ident not in position:
            # A data file can list its matches in any order. Always place a feeder first.
            earliest = max((column(by_id[feeder]) + 1 for feeder in match['feeders'] if feeder in by_id), default=0)
            position[ident] = max(round_order[match['round']], earliest)
        return position[ident]

    columns = defaultdict(list)
    for match in matches:
        columns[column(match)].append(match)
    columns = [columns[key] for key in sorted(columns)]
    depth = max(0, len(columns) - 1)
    widths = [385, 375][:depth] + [295] * max(0, depth - 2) + [340]
    starts = [0]
    for width in widths[:-1]:
        starts.append(starts[-1] + width + 95)
    span = max(map(len, columns), default=1) * 100
    labels = []
    height = 162
    for index, matches_in_round in enumerate(columns):
        final = index == depth and len(matches_in_round) == 1
        labels.append(list(dict.fromkeys(match['round'] for match in matches_in_round)))
        for row, match in enumerate(matches_in_round):
            match['isFinal'] = final
            offset = 75 if final else 44
            center = (row + 0.5) * span / len(matches_in_round) - 6
            top = max(0, center - offset)
            match['box'] = starts[index], top, widths[index], top + offset
            height = max(height, int(top + 2 * offset + 12))
    successors = {feeder: match for match in matches for feeder in match['feeders']}
    for earlier, later in reversed(list(zip(columns, columns[1:]))):
        # A lone qualifier sits next to its destination rather than halfway down a full draw.
        if len(earlier) == 1 and len(later) > 1:
            match = earlier[0]
            target = successors.get(match['id'])
            if target is not None:
                x, _, width, _ = match['box']
                center = target['box'][3]
                match['box'] = x, center - 44, width, center
    halves = [len(column_matches) for column_matches in columns] == [16, 8, 4, 2, 1]
    return starts, labels, starts[depth] + widths[depth] + 2, height, halves


def player_row(player, score, won, assets):
    name, team = player['name'], player['team']
    classes = 'player'
    if team == 'CHN':
        classes += ' cn'
    if won is not None:
        classes += ' winner' if won else ' loser'
    flag = ''
    if team in assets['flags']:
        country = assets['countries'].get(team, team)
        flag = f'<img class="flag" src="{escape(assets["flags"][team])}" alt="{escape(country)}代表队旗帜">'
    elif team:
        flag = f'<span class="team-badge">{escape(team)}</span>'
    badge = '<span class="team-badge">中国</span>' if team == 'CHN' else ''
    return (f'<div class="{classes}">{flag}<span class="name">{escape(name)}</span>{badge}'
            f'<b class="score">{score if score is not None else "—"}</b></div>')


def match_card(match, assets, zone, hidden):
    classes = ['match']
    if match['status'] in ('completed', 'retired', 'walkover', 'bye', 'cancelled'):
        classes.append('done')
    else:
        classes.append('unverified' if match.get('blocker') else 'future')
    if any(player['team'] == 'CHN' for player in match['players']):
        classes.append('contains-cn')
    title = ''
    if match.get('isFinal'):
        classes.append('final')
        champion = match['winner']
        name = match['players'][champion]['name'] if champion is not None else None
        title = '<strong class="final-title">' + escape(f'冠军 · {name}' if name else '冠军待定') + '</strong>'
    style = ''
    if 'box' in match:
        x, y, width, _ = match['box']
        style = f' style="left:{x}px;top:{y:g}px;width:{width}px"'
    date = match['completedDate']
    if date:
        date = date[5:].replace('-', '/')
    else:
        time = match['completedAt'] or match['scheduled']
        date = datetime.fromisoformat(time).astimezone(zone).strftime('%m/%d %H:%M') if time else '时间待核实'
    label = STATUS[match['status']]
    if match['status'] == 'scheduled' and match.get('blocker'):
        label = '赛况待核实'
    elif match['status'] == 'scheduled' and not match['scheduled']:
        date, label = '', '赛果待录'
    rows = ''.join(player_row(player, match['scores'][i] if match['scores'] is not None else None,
                              i == match['winner'] if match['winner'] is not None else None, assets)
                   for i, player in enumerate(match['players']))
    pairing = ' 对 '.join(player['name'] for player in match['players'])
    aria = escape(f'{match["round"]}：{pairing}')
    return (f'<article class="{" ".join(classes)}" id="{match["domId"]}" data-match-id="{escape(match["id"])}"'
            f' data-sex="{escape(match["draw"])}"{style} tabindex="0" role="button" aria-label="{aria}"{hidden}>'
            f'<span class="num">{match["number"]:02}</span>{title}{rows}'
            f'<div class="meta"><span>{date}</span><span>{label}</span></div></article>')


def source_link(source):
    return (f'<a href="{escape(source["url"])}" target="_blank" rel="noopener noreferrer">'
            f'{escape(source["label"])}</a>')


def group_table(group, matches, entries, assets, zone, hidden):
    rows = []
    for index, row in enumerate(group['rows'], start=1):
        rank = str(index) if group['final'] else '—'
        scores = (row['played'], row['wins'], row['games_for'], row['games_against'], row['points_for'], row['points_against'])
        rows.append(f'<tr><td>{rank}</td><td>{escape(entries[row["entry"]]["name"])}</td>' +
                    ''.join(f'<td>{value}</td>' for value in scores) + '</tr>')
    fixtures = ''.join(match_card(match, assets, zone, '') for match in matches)
    return (f'<section class="group" data-group-id="{escape(group["id"])}" data-sex="{escape(matches[0]["draw"])}"{hidden}>'
            f'<h2>{escape(group["name"])}</h2><p>{escape(group["reason"])}</p>'
            '<table><thead><tr><th>名次</th><th>选手／组合</th><th>场次</th><th>胜场</th>'
            '<th>胜局</th><th>负局</th><th>得分</th><th>失分</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><details><summary>小组赛对阵与比分</summary>'
            f'<div class="group-matches">{fixtures}</div></details></section>')


def render(model):
    assets = json.loads((TEMPLATES / 'wtt-assets.json').read_text(encoding='utf-8'))
    entries = {entry['id']: entry for entry in model['entries']}
    groups = {group['id']: group for group in model['groups']}
    draw_names = {draw['id']: draw['name'] for draw in model['draws']}
    sources = {item['id']: {'url': item['url'], 'label': item.get('label', item['id'])}
               for item in model['sources']}
    group_for = {match['id']: match['group'] for match in model['matches'] if match.get('group')}
    draws = {draw: [] for draw in draw_names}
    group_matches = defaultdict(list)
    match_numbers = {}
    counts = defaultdict(int)
    for match in model['matches']:
        draw = match.get('draw', 'main')
        counts[draw] += 1
        match_numbers[match['id']] = counts[draw]

    for index, match in enumerate(model['matches']):
        draw = match.get('draw', 'main')
        players = []
        for ident, slot in zip(match['players'], match['slots']):
            if ident:
                players.append(entries[ident])
            elif 'group_rank' in slot:
                group_id, rank = slot['group_rank']
                players.append({'name': f'{groups[group_id]["name"]} 第 {rank} 名', 'team': ''})
            elif 'winner' in slot:
                players.append({'name': f'第 {match_numbers[slot["winner"]]:02} 场胜者', 'team': ''})
            else:
                players.append({'name': slot.get('tbd', '轮空' if 'bye' in slot else '晋级席位待定'), 'team': ''})
        winner = match['players'].index(match['winner']) if match['winner'] is not None else None
        group_feed = [slot['group_rank'][0] for slot in match['slots'] if 'group_rank' in slot]
        feeders = []
        for slot in match['slots']:
            if 'winner' in slot:
                ident = slot['winner']
                if ident in group_for:
                    group_feed.append(group_for[ident])
                else:
                    feeders.append(ident)
        view = {
            'id': match['id'], 'draw': draw, 'domId': f'match-{index}', 'number': match_numbers[match['id']],
            'round': match['round'], 'players': players, 'scores': match['score'], 'winner': winner,
            'feeders': feeders, 'groupFeeders': group_feed, 'group': match.get('group'),
            'games': match['games'], 'inProgressGame': match.get('in_progress_game'),
            'scheduled': match.get('scheduled_at'), 'completedDate': match.get('completed_date'),
            'completedAt': match.get('completed_at'), 'status': match['status'],
            'resultLinks': [sources[ident] for ident in match['verified_source_ids']],
            'scheduleLinks': [sources[ident] for ident in match['schedule_source_ids']],
            'notice': match.get('migration_notice'), 'blocker': match.get('blocker'), 'reason': match.get('reason'),
        }
        if view['group']:
            group_matches[view['group']].append(view)
        draws[draw].append(view)

    event = model['event']
    zone = ZoneInfo(event['timezone'])
    tabs, columns, cards, wires, preliminary_panels = [], [], [], [], []
    board_width, board_height = 660, 162
    active = next(iter(draws), None)
    for draw, matches in draws.items():
        draw_attr = escape(draw)
        selected = draw == active
        hidden = '' if selected else ' hidden'
        tabs.append(f'<button role="tab" id="tab-{draw_attr}" aria-controls="bracket"'
                    f' aria-selected="{str(selected).lower()}" data-sex="{draw_attr}">{escape(draw_names[draw])}</button>')
        knockout = [match for match in matches if not match['group']]
        preliminary, knockout = split_preliminaries(knockout)
        if preliminary:
            for match in preliminary:
                match['preliminary'] = True
            fixtures = ''.join(match_card(match, assets, zone, '') for match in preliminary)
            title = escape(preliminary[0]['round'])
            preliminary_panels.append(f'<details class="preliminaries" data-sex="{draw_attr}"{hidden}>'
                                      f'<summary>{title} · {len(preliminary)} 场已录入</summary>'
                                      f'<div class="group-matches">{fixtures}</div></details>')
        starts, labels, width, height, halves = layout(knockout)
        board_width, board_height = max(board_width, width), max(board_height, height)
        headings = ''.join(f'<span style="left:{starts[col]}px">{escape(" / ".join(names))}</span>'
                           for col, names in enumerate(labels))
        columns.append(f'<div class="columns" data-sex="{draw_attr}"{hidden}>{headings}</div>')
        if halves:
            draw_marker = f' data-sex="{draw_attr}"{hidden} aria-hidden="true"'
            cards.extend([f'<div class="board-item half top"{draw_marker}>上半区</div>',
                          f'<div class="board-item half bottom"{draw_marker}>下半区</div>',
                          f'<div class="board-item divider"{draw_marker}></div>'])
        positions = {match['id']: match['box'] for match in knockout}
        for match in knockout:
            cards.append(match_card(match, assets, zone, hidden))
            x, _, _, y = match['box']
            for feeder in match['feeders']:
                if feeder not in positions:
                    continue  # The qualification card is in the preliminary panel.
                fx, _, fw, fy = positions[feeder]
                center = (fx + fw + x) / 2
                wires.append(f'<path data-sex="{draw_attr}" data-from="{escape(feeder)}" data-to="{escape(match["id"])}"'
                             f' d="M{fx + fw:g} {fy:g} H{center:g} V{y:g} H{x:g}"'
                             + ('' if selected else ' style="display:none"') + '/>')
    standings = ''.join(group_table(group, group_matches[ident], entries, assets, zone,
                                    '' if group_matches[ident][0]['draw'] == active else ' hidden')
                        for ident, group in groups.items())
    notices = ''.join(f'<p>{escape(notice)}</p>' for notice in model.get('notices', []))
    source_html = ' · '.join(source_link(item) for item in sources.values())
    checked = datetime.fromisoformat(event['snapshot_at']).astimezone(zone).strftime('%Y-%m-%d %H:%M')
    time_label = '北京时间' if event['timezone'] == 'Asia/Shanghai' else event['timezone']
    view = {'draws': draws, 'drawNames': draw_names, 'snapshot': event['snapshot_at'],
            'timezone': event['timezone'], 'venueTimezone': event['venue_timezone']}
    values = {
        'title': escape(event['name']), 'heading': escape(event['name']), 'eyebrow': '赛事签表 · 赛果快照',
        'back_link': escape(event.get('back_link', 'index.html')), 'snapshot': escape(f'赛况快照 · {time_label} {checked}'),
        'summary': f'{len(model["matches"])} 场比赛', 'tabs': ''.join(tabs), 'columns': ''.join(columns),
        'groups': standings + ''.join(preliminary_panels),
        'cards': '\n'.join(cards), 'wires': '\n'.join(wires), 'sources': notices + f'<p>{source_html}</p>',
        'data': script_json(view), 'assets': script_json(assets),
        'styles': (TEMPLATES / 'wtt-style.css').read_text(encoding='utf-8'),
        'interaction': (TEMPLATES / 'wtt-interaction.js').read_text(encoding='utf-8'),
        'board_width': str(board_width), 'board_height': str(board_height),
    }
    template = (TEMPLATES / 'wtt-bracket.html').read_text(encoding='utf-8')
    return re.sub(r'\{\{(\w+)\}\}', lambda token: values[token[1]], template)
