"""Render the verified bracket model into the original connected-board UI."""
from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

if __package__:
    from .board_layout import is_final_round, plan_board, section_for
    from .teams import flag_license, team_assets, team_codes
else:
    from board_layout import is_final_round, plan_board, section_for
    from teams import flag_license, team_assets, team_codes

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'
STATUS = {'scheduled': '待赛', 'live': '进行中', 'completed': '已完赛', 'retired': '退赛',
          'walkover': '弃权', 'bye': '轮空', 'cancelled': '取消'}


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c')


def player_row(player, score, won, assets):
    name, teams = player['name'], player['teams']
    china = 'CHN' in teams
    classes = 'player cn' if china else 'player'
    if won is not None:
        classes += ' winner' if won else ' loser'
    flags = []
    for team in teams:
        country = escape(assets['countries'][team])
        if team in assets['flags']:
            flag = escape(assets['flags'][team])
            flags.append(f'<img class="flag" src="{flag}" alt="{country}代表队旗帜">')
        else:
            flags.append(f'<span class="team-badge neutral">{country}</span>')
    badge = '<span class="team-badge">中国</span>' if china else ''
    return (f'<div class="{classes}">{"".join(flags)}<span class="name">{escape(name)}</span>{badge}'
            f'<b class="score">{score if score is not None else "—"}</b></div>')


def match_card(match, assets, zone):
    classes = ['match']
    if match['status'] in ('completed', 'retired', 'walkover', 'bye', 'cancelled'):
        classes.append('done')
    else:
        classes.append('unverified' if match.get('blocker') else 'future')
    if any('CHN' in player['teams'] for player in match['players']):
        classes.append('contains-cn')
    elif all(player['teams'] for player in match['players']):
        classes.append('known-no-cn')
    title = ''
    if match.get('isFinal'):
        classes.append('final')
        champion = match['winner']
        name = match['players'][champion]['name'] if champion is not None else None
        label = escape(f'冠军 · {name}' if name else '冠军待定')
        title = f'<strong class="final-title" title="{label}">{label}</strong>'
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
    source_note = ('<span class="origin-note" aria-label="有晋级关系可查" title="有晋级关系可查">↗</span>'
                   if match['links'] else '')
    heading = f'<strong class="match-round">{escape(match["round"])}</strong>'
    return (f'<article class="{" ".join(classes)}" id="{match["domId"]}" data-match-id="{escape(match["id"])}"'
            f' data-sex="{escape(match["draw"])}"{style} tabindex="0" role="button" aria-label="{aria}">'
            f'<span class="num">{match["number"]:02}</span>{heading}{title}{rows}'
            f'<div class="meta"><span>{date}</span><span>{label}</span></div>'
            f'{source_note}</article>')


def source_link(source):
    return (f'<a href="{escape(source["url"])}" target="_blank" rel="noopener noreferrer">'
            f'{escape(source["label"])}</a>')


def group_table(group, dom_id, matches, entries, assets, zone):
    rows = []
    for index, row in enumerate(group['rows'], start=1):
        rank = str(index) if group['final'] else '—'
        scores = (row['played'], row['wins'], row['games_for'], row['games_against'], row['points_for'], row['points_against'])
        row_target = f' id="{dom_id}-rank-{index}" tabindex="-1"' if group['final'] else ''
        rows.append(f'<tr{row_target}><td>{rank}</td><td>{escape(entries[row["entry"]]["name"])}</td>' +
                    ''.join(f'<td>{value}</td>' for value in scores) + '</tr>')
    fixtures = ''.join(match_card(match, assets, zone) for match in matches)
    return (f'<section class="group" id="{dom_id}" tabindex="-1" data-group-id="{escape(group["id"])}">'
            f'<h2>{escape(group["name"])}</h2><p>{escape(group["reason"])}</p>'
            '<table><thead><tr><th>名次</th><th>选手／组合</th><th>场次</th><th>胜场</th>'
            '<th>胜局</th><th>负局</th><th>得分</th><th>失分</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><details><summary>小组赛对阵与比分</summary>'
            f'<div class="group-matches">{fixtures}</div></details></section>')


def plan_draw(matches, hints, context):
    sections = defaultdict(list)
    overrides = hints.get('sections', {})
    explicit = hints.get('rounds', {})
    for match in matches:
        if not match['group']:
            section = overrides.get(match['id'], section_for(match['round']))
            match['section'] = section
            sections[section].append(match)
            if section == 'qualification':
                match['preliminary'] = True

    consumed = {feeder for match in matches for feeder in match['feeders']}
    finals = [match for match in sections['main']
              if is_final_round(match['round']) and match['id'] not in consumed]
    if len(finals) == 1:
        finals[0]['isFinal'] = True
    final_id = finals[0]['id'] if len(finals) == 1 else None

    plans = {}
    for section in ('main', 'qualification', 'placement'):
        cards = sections[section]
        if cards or section in explicit:
            plan = plan_board(cards, explicit_columns=explicit.get(section),
                              qualification=section == 'qualification',
                              context=f'{context} / {section}',
                              final_id=final_id if section == 'main' else None)
            if cards:
                plans[section] = plan
                for match in cards:
                    if match['id'] in plan['boxes']:
                        match['box'] = plan['boxes'][match['id']]
    return sections, plans


def connect_draw(matches, plans, groups, group_dom):
    wired = {(path['from'], path['to'], path['slot'])
             for plan in plans.values() for path in plan['paths']}
    by_id = {match['id']: match for match in matches}
    for target in matches:
        for index, slot in enumerate(target['slots']):
            position = ('上方签位', '下方签位')[index]
            if 'winner' in slot and (slot['winner'], target['id'], index) not in wired:
                feeder = by_id[slot['winner']]
                relation = {'kind': 'winner', 'from': feeder['id'], 'to': target['id'], 'slot': index}
                target['links'].append(dict(relation, direction='source', target=feeder['domId'],
                    label=f'{position} · 第 {feeder["number"]:02} 场胜者（{feeder["round"]}）'))
                feeder['links'].append(dict(relation, direction='destination', target=target['domId'],
                    label=f'胜者进入第 {target["number"]:02} 场（{target["round"]}）的{position}'))
            elif 'group_rank' in slot:
                group_id, rank = slot['group_rank']
                group = groups[group_id]
                origin = group_dom[group_id] + (f'-rank-{rank}' if group['final'] else '')
                label = f'{position} · {group["name"]}第 {rank} 名'
                if not group['final']:
                    label += '（排名待定）'
                target['links'].append({
                    'kind': 'group_rank', 'direction': 'source', 'from': group_id, 'to': target['id'],
                    'slot': index, 'target': origin, 'label': label,
                })


def render_section(section, matches, plan, assets, zone):
    cards = {match['id']: match_card(match, assets, zone) for match in matches}
    title = {'main': '正赛签表', 'qualification': '资格赛', 'placement': '排位赛'}[section]
    labels = [' / '.join(column['labels']) for column in plan['columns']]
    if section == 'qualification' and len(labels) != len(set(labels)):
        labels = [f'{label} · 第 {index} 层' if labels.count(label) > 1 else label
                  for index, label in enumerate(labels, 1)]
    if plan['fallback']:
        rounds = ''.join(f'<section><h3>{escape(label)}</h3><div class="round-cards">'
                         + ''.join(cards[ident] for ident in column['ids']) + '</div></section>'
                         for label, column in zip(labels, plan['columns']))
        content = f'<div class="round-list" aria-label="{title}">{rounds}</div>'
    else:
        width, height = plan['width'], plan['height']
        headings = ''.join(
            f'<span style="left:{column["x"]:g}px;max-width:{plan["boxes"][column["ids"][0]][2]:g}px"'
            f' title="{escape(label)}">{escape(label)}</span>'
            for label, column in zip(labels, plan['columns'])
        )
        halves = ''
        if section == 'main' and [len(column['ids']) for column in plan['columns']] == [16, 8, 4, 2, 1] and len(plan['paths']) == 30:
            opening = plan['columns'][0]['ids']
            middle = sum(plan['boxes'][ident][3] for ident in opening[7:9]) / 2
            halves = (f'<span class="half" style="top:{middle / 2:g}px" aria-hidden="true">上半区</span>'
                      f'<span class="half" style="top:{middle * 1.5:g}px" aria-hidden="true">下半区</span>'
                      f'<div class="divider" style="top:{middle:g}px" aria-hidden="true"></div>')
        paths = ''.join(f'<path data-from="{escape(path["from"])}" data-to="{escape(path["to"])}"'
                        f' data-slot="{path["slot"]}" d="{path["d"]}"/>'
                        for path in plan['paths'])
        ordered_cards = ''.join(cards[ident] for column in plan['columns'] for ident in column['ids'])
        content = (f'<div class="board-track" style="width:{width:g}px">'
                   f'<div class="columns">{headings}</div>'
                   f'<section class="board" aria-label="{title}" style="height:{height:g}px">'
                   f'{halves}<svg class="wires" viewBox="0 0 {width:g} {height:g}" aria-hidden="true">{paths}</svg>'
                   f'{ordered_cards}</section></div>')
    if section == 'qualification':
        return (f'<details class="preliminaries secondary-bracket"><summary>{title} · {len(matches)} 场</summary>'
                f'<div class="bracket-scroll" tabindex="0" aria-label="{title}">{content}</div></details>')
    if section == 'placement':
        return (f'<section class="placement-bracket secondary-bracket"><h2>{title}</h2>'
                f'<div class="bracket-scroll" tabindex="0" aria-label="{title}">{content}</div></section>')
    return f'<div class="main-bracket">{content}</div>'


def render(model):
    entries = {entry['id']: dict(entry, teams=team_codes(entry['team'])) for entry in model['entries']}
    used_teams = set()
    groups = {group['id']: group for group in model['groups']}
    draw_names = {draw['id']: draw['name'] for draw in model['draws']}
    sources = {item['id']: {'url': item['url'], 'label': item.get('label', item['id'])}
               for item in model['sources']}
    group_dom = {ident: f'group-{index}' for index, ident in enumerate(groups)}
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
                players.append({'name': f'{groups[group_id]["name"]} 第 {rank} 名', 'team': '', 'teams': ()})
            elif 'winner' in slot:
                players.append({'name': f'第 {match_numbers[slot["winner"]]:02} 场胜者', 'team': '', 'teams': ()})
            else:
                players.append({'name': slot.get('tbd', '轮空' if 'bye' in slot else '晋级席位待定'), 'team': '', 'teams': ()})
        used_teams.update(code for player in players for code in player['teams'])
        winner = match['players'].index(match['winner']) if match['winner'] is not None else None
        group_feed = [slot['group_rank'][0] for slot in match['slots'] if 'group_rank' in slot]
        feeders = [slot['winner'] for slot in match['slots'] if 'winner' in slot]
        view = {
            'id': match['id'], 'draw': draw, 'domId': f'match-{index}', 'number': match_numbers[match['id']],
            'round': match['round'], 'players': players, 'scores': match['score'], 'winner': winner,
            'feeders': feeders, 'groupFeeders': group_feed, 'group': match.get('group'),
            'slots': match['slots'], 'links': [],
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

    assets = team_assets(used_teams)
    event = model['event']
    zone = ZoneInfo(event['timezone'])
    tabs, panels = [], []
    board_width, board_height = 660, 162
    active = next(iter(draws), None)
    layout_hints = model.get('layout', {})
    for draw, matches in draws.items():
        draw_attr = escape(draw)
        selected = draw == active
        hidden = '' if selected else ' hidden'
        tabs.append(f'<button role="tab" id="tab-{draw_attr}" aria-controls="bracket"'
                    f' aria-selected="{str(selected).lower()}" data-sex="{draw_attr}">{escape(draw_names[draw])}</button>')
        sections, plans = plan_draw(matches, layout_hints.get(draw, {}), f'{event["name"]} / {draw}')
        connect_draw(matches, plans, groups, group_dom)
        standings = ''.join(group_table(group, group_dom[ident], group_matches[ident], entries, assets, zone)
                            for ident, group in groups.items() if group_matches[ident][0]['draw'] == draw)
        rendered = {key: render_section(key, sections[key], plans[key], assets, zone)
                    for key in plans}
        main = plans.get('main', {})
        width, height = max(660, main.get('width', 0)), max(162, main.get('height', 0))
        if selected:
            board_width, board_height = width, height
        panels.append(f'<div class="draw-panel" data-sex="{draw_attr}" data-width="{width:g}"'
                      f' data-height="{height:g}"{hidden}>{standings}'
                      + ''.join(rendered.get(key, '') for key in ('qualification', 'main', 'placement')) + '</div>')
    notices = ''.join(f'<p>{escape(notice)}</p>' for notice in model.get('notices', []))
    source_html = ' · '.join(source_link(item) for item in sources.values())
    checked = datetime.fromisoformat(event['snapshot_at']).astimezone(zone).strftime('%Y-%m-%d %H:%M')
    time_label = '北京时间' if event['timezone'] == 'Asia/Shanghai' else event['timezone']
    view = {'draws': draws, 'drawNames': draw_names, 'snapshot': event['snapshot_at'],
            'timezone': event['timezone'], 'venueTimezone': event['venue_timezone']}
    values = {
        'title': escape(event['name']), 'heading': escape(event['name']), 'eyebrow': '赛事签表 · 赛果快照',
        'back_link': escape(event.get('back_link', 'index.html')), 'snapshot': escape(f'赛况快照 · {time_label} {checked}'),
        'summary': f'{len(model["matches"])} 场比赛', 'tabs': ''.join(tabs), 'panels': ''.join(panels),
        'sources': notices + f'<p>{source_html}</p>',
        'data': script_json(view), 'assets': script_json(assets),
        'flag_credit': f'<!-- Vendored flag-icons SVG license\n{flag_license().strip()}\n-->' if assets['flags'] else '',
        'styles': (TEMPLATES / 'wtt-style.css').read_text(encoding='utf-8'),
        'interaction': (TEMPLATES / 'wtt-interaction.js').read_text(encoding='utf-8'),
        'board_width': str(board_width), 'board_height': str(board_height),
    }
    template = (TEMPLATES / 'wtt-bracket.html').read_text(encoding='utf-8')
    return re.sub(r'\{\{(\w+)\}\}', lambda token: values[token[1]], template)
