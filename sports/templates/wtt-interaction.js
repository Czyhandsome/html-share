'use strict';

const {draws, drawNames, snapshot, timezone, venueTimezone} = JSON.parse(document.getElementById('wtt-data').textContent);
const assets = JSON.parse(document.getElementById('wtt-assets').textContent);
const countries = new Map(Object.entries(assets.countries));
const flags = new Map(Object.entries(assets.flags));
const lookup = new Map(Object.values(draws).flat().map(match => [match.id, match]));
const board = document.getElementById('bracket');
const tooltip = document.getElementById('tooltip');
const cards = [...board.querySelectorAll('.match')];
const paths = [...board.querySelectorAll('.wires path')];
const groups = [...board.querySelectorAll('.group[data-group-id]')];
const drawSections = [...board.querySelectorAll('.columns[data-sex], .group[data-sex], .board-item[data-sex], .preliminaries[data-sex]')];
const tabs = [...document.querySelectorAll('.tabs button')];
const shell = document.querySelector('.shell');
const canvas = document.querySelector('.canvas');
const terminal = new Set(['completed', 'retired', 'walkover', 'bye', 'cancelled']);
const states = {completed: '已完赛', retired: '退赛', walkover: '弃权', bye: '轮空', cancelled: '取消', live: '进行中'};

let active = tabs[0]?.dataset.sex ?? Object.keys(draws)[0];
let pinned = null;

function escapeText(value) {
    return String(value).replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
}

function timeParts(iso, zone) {
    const formatter = new Intl.DateTimeFormat('zh-CN', {
        timeZone: zone, month: 'numeric', day: 'numeric', hour: '2-digit',
        minute: '2-digit', hourCycle: 'h23', weekday: 'short',
    });
    const parts = Object.fromEntries(formatter.formatToParts(new Date(iso)).map(part => [part.type, part.value]));
    return `${parts.month}月${parts.day}日 ${parts.weekday} ${parts.hour}:${parts.minute}`;
}

function show(draw) {
    active = draw;
    closeTip();
    for (const tab of tabs) {
        const isActive = tab.dataset.sex === draw;
        tab.setAttribute('aria-selected', isActive);
        if (isActive) board.setAttribute('aria-labelledby', tab.id);
    }
    for (const card of cards) card.hidden = card.dataset.sex !== draw;
    for (const path of paths) path.style.display = path.dataset.sex === draw ? '' : 'none';
    for (const section of drawSections) section.hidden = section.dataset.sex !== draw;
    const matches = draws[draw];
    const final = matches.find(match => match.isFinal);
    const finished = matches.filter(match => terminal.has(match.status)).length;
    const title = draw === 'men' ? '男单' : draw === 'women' ? '女单' : drawNames[draw];
    const entry = player => player.name + (player.teams.length ? '（' + teamNames(player) + '）' : '');
    const champion = final?.winner != null ? final.players[final.winner] : null;
    const progress = `${title} · ${finished} / ${matches.length} 场已有结果`;
    document.querySelector('.guidance .stat').textContent = champion ? `${progress} · 冠军 ${champion.name}` : progress;
    document.getElementById('takeaway').textContent = champion
        ? `${title}冠军：${entry(champion)} · 亚军：${entry(final.players[1 - final.winner])}`
        : progress;

    const groupMatches = matches.some(match => match.group || match.groupFeeders?.length);
    const bracket = board.querySelector('.board');
    const knockout = matches.filter(match => !match.group && !match.preliminary);
    const feederEdges = knockout.reduce((count, match) =>
        count + match.feeders.filter(id => !lookup.get(id).preliminary).length, 0);
    bracket.hidden = !knockout.length;
    canvas.querySelector('.edition strong').textContent = groupMatches ? (bracket.hidden ? '分组赛' : '小组 + 淘汰')
        : final && feederEdges === knockout.length - 1 ? `${knockout.length + 1} → 1` : '签表';
}

function clearRoutes() {
    for (const path of paths) path.classList.remove('hot');
    for (const card of cards) card.classList.remove('selected');
    for (const group of groups) group.classList.remove('selected');
}

function highlight(card) {
    clearRoutes();
    card.classList.add('selected');
    const matchId = card.dataset.matchId;
    const selected = new Set([matchId]);
    const selectedGroups = new Set();

    function ancestors(id) {
        const match = lookup.get(id);
        if (match.group) selectedGroups.add(match.group);
        for (const group of match.groupFeeders || []) selectedGroups.add(group);
        for (const feeder of match.feeders) {
            if (selected.has(feeder)) continue;
            selected.add(feeder);
            ancestors(feeder);
        }
    }

    ancestors(matchId);
    const queue = [matchId];
    for (const current of queue) {
        const origin = lookup.get(current);
        for (const next of draws[active]) {
            if (selected.has(next.id)) continue;
            if (next.feeders.includes(current) || (origin.group && next.groupFeeders?.includes(origin.group))) {
                selected.add(next.id);
                queue.push(next.id);
            }
        }
    }
    for (const path of paths) {
        path.classList.toggle('hot', selected.has(path.dataset.from) && selected.has(path.dataset.to));
    }
    for (const group of groups) {
        group.classList.toggle('selected', group.dataset.sex === active && selectedGroups.has(group.dataset.groupId));
    }
}

function sourceLinks(label, links) {
    const anchors = links.filter(source => /^https?:\/\//i.test(source.url)).map(source =>
        `<a href="${escapeText(source.url)}" target="_blank" rel="noopener noreferrer">${escapeText(source.label)}</a>`);
    return anchors.length ? `<div class="tip-note tip-sources">${label} · ${anchors.join(' · ')}</div>` : '';
}

function teamNames(player) {
    return player.teams.map(code => countries.get(code)).join('／');
}

function tooltipContent(match) {
    const pair = match.players.map(player => {
        const teamFlags = player.teams.filter(code => flags.has(code)).map(code =>
            `<img class="flag" src="${escapeText(flags.get(code))}" alt="${escapeText(countries.get(code))}代表队旗帜">`
        ).join('');
        const flag = player.teams.length ? teamFlags : '<span class="tip-placeholder">?</span>';
        const team = teamNames(player) || '代表队待定';
        return `<div class="tip-player">${flag}<div><div>${escapeText(player.name)}</div><div class="tip-country">${escapeText(team)}</div></div></div>`;
    }).join('<div class="tip-vs">VS</div>');
    const number = String(match.number).padStart(2, '0');
    let content = `<div class="tip-round">${escapeText(drawNames[active])} · ${escapeText(match.round)} · ${number} 场</div><div class="tip-pair">${pair}</div>`;

    if (match.scores) {
        content += `<div class="tip-final">${match.scores.join(' : ')}</div>`;
    }
    if (match.winner != null) {
        const outcome = match.group ? '获胜' : match.isFinal ? '夺冠' : '晋级';
        content += `<div class="tip-time">${escapeText(match.players[match.winner].name)} ${outcome}</div>`;
    }
    if (states[match.status]) {
        content += `<div class="tip-note">${states[match.status]}</div>`;
    }

    const displayZone = timezone === 'Asia/Shanghai' ? '北京时间' : timezone;
    if (match.completedDate) {
        content += `<div class="tip-note">完赛日期 · ${escapeText(match.completedDate)}</div>`;
    } else if (match.completedAt) {
        content += `<div class="tip-note">完赛 · ${escapeText(displayZone)} ${timeParts(match.completedAt, timezone)}</div>`;
    }
    if (match.scheduled) {
        content += `<div class="tip-note">计划开赛 · ${escapeText(displayZone)} ${timeParts(match.scheduled, timezone)}<br>当地 ${timeParts(match.scheduled, venueTimezone)}</div>`;
        if (!terminal.has(match.status) && match.status !== 'live') {
            const overdue = new Date(match.scheduled) <= new Date(snapshot);
            content += `<div class="tip-state">${overdue ? '计划时间已过，赛果待核实。' : '开赛时间可能随前场进度顺延。'}</div>`;
        }
    } else if (!terminal.has(match.status) && match.status !== 'live') {
        content += '<div class="tip-time">具体时间暂未核实</div>';
    }
    if (match.games.length) {
        content += `<div class="tip-note">逐局比分（上方选手在前）<br>${match.games.map(game => game.join('–')).join('、')}</div>`;
    }
    if (match.inProgressGame) {
        content += `<div class="tip-note">未完局 · ${match.inProgressGame.join('–')}</div>`;
    }
    for (const note of [match.reason, match.blocker, match.notice]) {
        if (note) content += `<div class="tip-note">${escapeText(note)}</div>`;
    }
    if (pinned) {
        content += sourceLinks('赛果来源', match.resultLinks || []) + sourceLinks('排期来源', match.scheduleLinks || []);
    }
    return content + '<div class="tip-pin">点击比赛固定详情 / 再次点击或按 Esc 关闭</div>';
}

function positionTip(event, card) {
    const rect = card.getBoundingClientRect();
    const anchorX = event?.clientX ?? rect.right;
    const anchorY = event?.clientY ?? rect.top;
    const right = anchorX + 17;
    const left = right + tooltip.offsetWidth < innerWidth - 12 ? right : anchorX - tooltip.offsetWidth - 17;
    const top = Math.min(anchorY + 16, innerHeight - tooltip.offsetHeight - 12);
    tooltip.style.left = Math.max(8, left) + 'px';
    tooltip.style.top = Math.max(8, top) + 'px';
}

function showTip(card, event) {
    highlight(card);
    tooltip.innerHTML = tooltipContent(lookup.get(card.dataset.matchId));
    tooltip.classList.toggle('pinned', Boolean(pinned));
    tooltip.setAttribute('role', pinned ? 'dialog' : 'tooltip');
    tooltip.setAttribute('aria-label', '比赛详情');
    tooltip.hidden = false;
    positionTip(event, card);
}

function closeTip(restoreFocus = false) {
    if (restoreFocus && pinned && tooltip.contains(document.activeElement)) {
        pinned.focus({preventScroll: true});
    }
    pinned = null;
    tooltip.hidden = true;
    tooltip.classList.remove('pinned');
    clearRoutes();
}

function focusChina(button) {
    const enabled = button.getAttribute('aria-pressed') !== 'true';
    button.setAttribute('aria-pressed', enabled);
    board.classList.toggle('focused', enabled);
}

function toggleSources() {
    const panel = document.getElementById('sources');
    panel.hidden = !panel.hidden;
    document.getElementById('source-button').setAttribute('aria-expanded', !panel.hidden);
}

for (const tab of tabs) {
    tab.addEventListener('click', () => show(tab.dataset.sex));
}
for (const card of cards) {
    card.addEventListener('mouseenter', event => { if (!pinned) showTip(card, event); });
    card.addEventListener('mousemove', event => { if (!pinned) positionTip(event, card); });
    card.addEventListener('mouseleave', () => { if (!pinned) closeTip(); });
    card.addEventListener('focus', () => { if (!pinned) showTip(card); });
    card.addEventListener('blur', () => { if (!pinned) closeTip(); });
    card.addEventListener('click', event => {
        if (pinned === card) {
            closeTip(true);
            return;
        }
        pinned = card;
        showTip(card, event.detail ? event : null);
        if (!event.detail) tooltip.focus({preventScroll: true});
    });
    card.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            card.click();
        }
    });
}
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeTip(true); });
document.addEventListener('click', event => {
    if (!event.target.closest('.match, #tooltip')) closeTip();
});

function fit() {
    // The cards and their connecting paths share the same scaled canvas.
    const width = document.documentElement.clientWidth;
    const canvasWidth = canvas.offsetWidth;
    const scale = Math.min(1, Math.max(0.55, width / canvasWidth));
    shell.style.width = Math.min(width, canvasWidth) + 'px';
    canvas.style.zoom = scale;
    canvas.style.setProperty('--usable-width', Math.min(canvasWidth, width / scale) + 'px');
    closeTip();
}

window.addEventListener('resize', fit);
window.addEventListener('scroll', () => { if (!pinned) closeTip(); });
shell.addEventListener('scroll', () => { if (!pinned) closeTip(); });
if (active) show(active);
fit();
