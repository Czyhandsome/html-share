"""Render the compiled team bracket as a single offline HTML document."""

from collections import defaultdict
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
import re

from .board import TEMPLATES, layout, source_link
from .teams import flag_license, team_assets, team_codes

STATUS = {
    'scheduled': '待赛', 'live': '进行中', 'completed': '已完赛',
    'walkover': '弃权', 'bye': '轮空', 'retired': '退赛',
    'unverified': '明细待核实', 'not_played': '未进行',
}


def _links(verification, sources):
    return ' · '.join(source_link(sources[key])
                      for key in (verification or {}).get('source_ids', []))


def _score(score):
    return '–'.join(str(value) for value in score) if score is not None else '—'


def _team_row(team, assets, *, score=None, winner=False, show_score=True):
    code = next(iter(team['teams']), '')
    marker = ''
    if code in assets['flags']:
        flag = escape(assets['flags'][code])
        name = escape(assets['countries'][code])
        marker = f'<img class="flag" src="{flag}" alt="{name}代表队旗帜">'
    elif code:
        marker = f'<span class="team-badge neutral">{escape(assets["countries"][code])}</span>'
    badge = '<span class="team-badge">中国</span>' if code == 'CHN' else ''
    points = f'<b class="score">{score if score is not None else "—"}</b>' if show_score else ''
    state = ' winner' if winner else ''
    return f'<span class="player{state}">{marker}<span class="name">{escape(team["name"])}</span>{badge}{points}</span>'


def _slot_name(slot, ties, groups):
    if 'winner' in slot:
        return f'{ties[slot["winner"]]["round"]}胜者'
    if 'group_rank' in slot:
        group, rank = slot['group_rank']
        return f'{groups[group]["name"]}第 {rank} 名'
    return slot.get('tbd', '轮空' if 'bye' in slot else '晋级席位待定')


def _rubber(match, team_ids, roster, sources):
    label = escape(match['name'])
    kind = '单打' if match['kind'] == 'singles' else '双打'
    lineup = match.get('lineup') or [[], []]
    sides = [
        '／'.join(roster[team].get(athlete, athlete) for athlete in players) if players else '阵容待核实'
        for team, players in zip(team_ids, lineup)
    ]
    state = STATUS[match['status']]
    if match['status'] == 'not_played':
        sides = ['—', '—']
    lines = []
    if match.get('games'):
        lines.append('<p class="games">逐局比分 ' +
                     ' · '.join(_score(game) for game in match['games']) + '</p>')
    if match.get('in_progress_game') is not None:
        lines.append('<p class="games">未完局 ' + _score(match['in_progress_game']) + '</p>')
    if match.get('reason'):
        lines.append(f'<p>{escape(match["reason"])}</p>')
    links = _links(match.get('verification'), sources)
    if links:
        lines.append(f'<p class="evidence">{links}</p>')
    teams = ''.join(
        f'<span class="lineup-side{" winner" if match["winner"] == index else ""}">{escape(name)}</span>'
        for index, name in enumerate(sides)
    )
    return (f'<li class="rubber" data-position="{match["position"]}" data-status="{match["status"]}">'
            f'<h3>{label}<small>{kind} · {state}</small></h3>'
            f'<div class="lineup">{teams}<b class="rubber-score">{_score(match["score"])}</b></div>'
            f'{"".join(lines)}</li>')


def _tie_status(tie):
    if tie['status'] in ('scheduled', 'live') and tie.get('blocker'):
        return '赛果待核实'
    return STATUS[tie['status']]


def _tie_details(tie, pairing, roster, groups, qualifications, sources, zone, venue_zone):
    parts = [f'<p class="tie-result">{_tie_status(tie)} · <strong>{_score(tie["score"])}</strong></p>']
    if tie.get('blocker'):
        parts.append(f'<p class="partial">{escape(tie["blocker"])}</p>')
    if tie.get('completed_date'):
        date = escape(tie['completed_date'])
        parts.append(f'<p>完赛日期 <time datetime="{date}">{date}</time></p>')
    if tie['summary_only']:
        missing = [escape(match['name']) for match in tie['matches'] if match['status'] == 'unverified']
        gap = '、'.join(missing)
        parts.append(f'<p class="partial">官方总比分已核实。待补单场明细为{gap}。</p>')
    if tie.get('scheduled_at'):
        instant = datetime.fromisoformat(tie['scheduled_at'])
        display = instant.astimezone(zone).strftime('%m/%d %H:%M %Z')
        venue = instant.astimezone(venue_zone).strftime('%m/%d %H:%M %Z')
        parts.append(f'<p>计划开赛 <time datetime="{escape(tie["scheduled_at"])}">{display}</time> · 当地 {venue}</p>')
    official = tie.get('official_result') or {}
    if official.get('reason'):
        parts.append(f'<p>{escape(official["reason"])}</p>')
    links = _links(official.get('verification'), sources)
    if links:
        parts.append(f'<p class="evidence">团体赛果 · {links}</p>')
    bye_links = _links(tie.get('bye_verification'), sources)
    if bye_links:
        parts.append(f'<p class="evidence">轮空依据 · {bye_links}</p>')
    schedule_links = _links(tie.get('schedule_verification'), sources)
    if schedule_links:
        parts.append(f'<p class="evidence">赛程 · {schedule_links}</p>')
    for slot in tie['slots']:
        if 'qualified' in slot:
            qualification = qualifications[slot['qualified']]
            parts.append(f'<p class="evidence">{escape(qualification["label"])} · '
                         f'{_links(qualification["verification"], sources)}</p>')
        elif 'group_rank' in slot:
            group = groups[slot['group_rank'][0]]
            if group.get('standings'):
                parts.append(f'<p class="evidence">{escape(group["name"])}正式排名 · '
                             f'{_links(group["standings"]["verification"], sources)}</p>')
    matches = ''.join(_rubber(match, tie['teams'], roster, sources) for match in tie['matches'])
    if matches:
        parts.append(f'<ol class="rubbers" aria-label="单场明细">{matches}</ol>')
    return (f'<template id="{tie["dom"]}-detail"><h2 id="tie-heading">{escape(pairing)}</h2>'
            f'{"".join(parts)}</template>')


def _tie_card(tie, teams, ties, groups, assets, zone):
    sides = [
        teams[ident] if ident else {'name': _slot_name(slot, ties, groups), 'teams': ()}
        for ident, slot in zip(tie['teams'], tie['slots'])
    ]
    pairing = ' 对 '.join(team['name'] for team in sides)
    china = any('CHN' in team['teams'] for team in sides)
    marker = ' contains-cn' if china else ' known-no-cn' if all(team['teams'] for team in sides) else ''
    scores = tie['score'] or [None, None]
    rows = ''.join(_team_row(team, assets, score=scores[index], winner=bool(ident and ident == tie['winner']))
                   for index, (team, ident) in enumerate(zip(sides, tie['teams'])))
    label = _tie_status(tie)
    if tie['summary_only']:
        label += ' · 明细待补'
    time = tie.get('scheduled_at')
    time_text = tie.get('completed_date', '')[5:].replace('-', '/')
    if not time_text and time:
        time_text = datetime.fromisoformat(time).astimezone(zone).strftime('%m/%d %H:%M')
    position = ''
    if 'box' in tie:
        x, y, width, _ = tie['box']
        position = f' style="left:{x}px;top:{y:g}px;width:{width}px"'
    card = (f'<button type="button" class="tie-card{marker}" data-team-tie="{escape(tie["id"])}"'
            f' data-detail="{tie["dom"]}-detail" aria-haspopup="dialog"'
            f' aria-label="{escape(tie["round"] + " · " + pairing + " · " + _score(tie["score"]) + " · " + label)}"'
            f'{position}>{rows}<span class="tie-meta"><span>{time_text}</span><span>{label}</span></span></button>')
    return card, pairing


def _knockout(ties, cards):
    if not ties:
        return '<p class="pending">对阵待核实</p>'
    starts, labels, width, height, _ = layout(ties)
    for tie in ties:
        x, _, card_width, center = tie['box']
        top = max(0, center - 44)
        tie['box'] = x, top, card_width, top + 44
    positions = {tie['id']: tie['box'] for tie in ties}
    columns = ''.join(f'<span style="left:{x}px">{escape(" / ".join(names))}</span>'
                      for x, names in zip(starts, labels))
    wires = []
    for tie in ties:
        x, _, _, y = tie['box']
        for feeder in tie['feeders']:
            if feeder not in positions:
                continue
            fx, _, fw, fy = positions[feeder]
            center = (fx + fw + x) / 2
            wires.append(f'<path d="M{fx + fw:g} {fy:g} H{center:g} V{y:g} H{x:g}"/>')
    return (f'<div class="board-scroll" tabindex="0" aria-label="横向滚动查看淘汰赛签表">'
            f'<div class="board-width" style="width:{width}px"><div class="rounds">{columns}</div>'
            f'<div class="board" style="height:{height:g}px">'
            f'<svg class="wires" viewBox="0 0 {width} {height:g}" aria-hidden="true">{"".join(wires)}</svg>'
            f'{cards(ties)}</div></div></div>')


def _group(group, ties, cards, teams, sources, assets):
    standings = group.get('standings')
    order = standings['order'] if standings else group['teams']
    rows = ''.join(
        f'<tr><td>{rank if standings else "—"}</td><td>{_team_row(teams[ident], assets, show_score=False)}</td></tr>'
        for rank, ident in enumerate(order, 1)
    )
    ranking = _links(standings['verification'], sources) if standings else ''
    label = '官方排名' if standings else '排名待核实'
    return (f'<details class="group" data-group="{escape(group["id"])}">'
            f'<summary>{escape(group["name"])}<small>{label} · {len(ties)} 场</small></summary>'
            f'<table aria-label="{escape(group["name"] + "排名")}"><thead><tr><th scope="col">名次</th>'
            f'<th scope="col">代表队</th></tr></thead><tbody>{rows}</tbody></table>'
            f'<p class="evidence">{ranking}</p><div class="group-ties">{cards(ties)}</div></details>')


def _qualification_list(items, teams, sources):
    if not items:
        return ''
    rows = ''.join(
        f'<li><strong>{escape(teams[item["team"]]["name"])}</strong> · {escape(item["label"])}'
        f' <span class="evidence">{_links(item["verification"], sources)}</span></li>'
        for item in items
    )
    return f'<details class="qualifications"><summary>官方晋级名单</summary><ul>{rows}</ul></details>'


def render_team(model):
    event = model['event']
    zone, venue_zone = ZoneInfo(event['timezone']), ZoneInfo(event['venue_timezone'])
    sources = {source['id']: source for source in model['sources']}
    teams = {team['id']: dict(team, teams=team_codes(team['team'])) for team in model['teams']}
    assets = team_assets(code for team in teams.values() for code in team['teams'])
    for team in teams.values():
        if not team.get('name'):
            team['name'] = assets['countries'][team['teams'][0]]
    roster = {ident: {player['id']: player['name'] for player in team['players']}
              for ident, team in teams.items()}
    groups = {group['id']: group for group in model['groups']}
    qualifications = {item['id']: item for item in model['qualifications']}
    stage_qualifications = defaultdict(list)
    for item in qualifications.values():
        stage_qualifications[item['stage']].append(item)
    ties = {}
    for index, tie in enumerate(model['ties']):
        ties[tie['id']] = dict(tie, dom=f'tie-{index}',
                               feeders=[slot['winner'] for slot in tie['slots'] if 'winner' in slot])
    by_stage, by_group = defaultdict(list), defaultdict(list)
    for tie in ties.values():
        by_stage[tie['stage']].append(tie)
        if tie.get('group'):
            by_group[tie['group']].append(tie)

    detail_templates = []

    def cards(items):
        output = []
        for tie in items:
            card, pairing = _tie_card(tie, teams, ties, groups, assets, zone)
            output.append(card)
            detail_templates.append(
                _tie_details(tie, pairing, roster, groups, qualifications, sources, zone, venue_zone)
            )
        return ''.join(output)

    tabs, panels = [], []
    for index, draw in enumerate(model['draws']):
        tabs.append(f'<button type="button" id="team-tab-{index}" role="tab"'
                    f' aria-controls="team-draw-{index}" aria-selected="{str(not index).lower()}"'
                    f' tabindex="{0 if not index else -1}">{escape(draw["name"])}</button>')
        sections = []
        for stage in (item for item in model['stages'] if item['draw'] == draw['id']):
            ident = stage['id']
            if stage['kind'] == 'group':
                body = ''.join(_group(group, by_group[group['id']], cards, teams, sources, assets)
                               for group in groups.values() if group['stage'] == ident)
            else:
                body = _knockout(by_stage[ident], cards)
            qualifying = _qualification_list(stage_qualifications[ident], teams, sources)
            sections.append(f'<section class="stage" data-stage="{escape(ident)}">'
                            f'<h2>{escape(stage["name"])}</h2>{qualifying}{body}</section>')
        hidden = ' hidden' if index else ''
        panels.append(f'<div id="team-draw-{index}" role="tabpanel" aria-labelledby="team-tab-{index}"'
                      f'{hidden}>{"".join(sections)}</div>')
    stamp = datetime.fromisoformat(event['snapshot_at']).astimezone(zone).strftime('%Y-%m-%d %H:%M')
    time_label = '北京时间' if event['timezone'] == 'Asia/Shanghai' else event['timezone']
    notices = ''.join(f'<p>{escape(note)}</p>' for note in model.get('notices', []))
    evidence = ' · '.join(source_link(item) for item in sources.values())
    values = {
        'title': escape(event['name']),
        'back_link': escape(event.get('back_link', 'index.html')),
        'snapshot': f'赛况快照 · {escape(time_label)} {stamp}',
        'tabs': ''.join(tabs),
        'panels': ''.join(panels),
        'details': ''.join(detail_templates),
        'sources': f'{notices}<p>{evidence}</p>',
        'styles': (TEMPLATES / 'team-style.css').read_text(encoding='utf-8'),
        'interaction': (TEMPLATES / 'team-interaction.js').read_text(encoding='utf-8'),
        'flag_credit': f'<!-- Vendored flag-icons SVG license\n{flag_license().strip()}\n-->' if assets['flags'] else '',
    }
    template = (TEMPLATES / 'team-bracket.html').read_text(encoding='utf-8')
    return re.sub(r'\{\{(\w+)\}\}', lambda token: values[token[1]], template)
