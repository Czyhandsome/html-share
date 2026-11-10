const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '../..');
const index = pathToFileURL(path.join(root, 'docs/2026/11/20261104-1042-sports-brackets/index.html')).href;

async function checkConnectedBracket(page, groupFixture = false) {
    const {draws} = JSON.parse(await page.locator('#wtt-data').textContent());
    const panel = page.locator('#bracket');
    const tooltip = page.locator('#tooltip');
    const tabs = page.getByRole('tab');
    const drawIds = Object.keys(draws);
    const tabFor = draw => tabs.and(page.locator(`[id=${JSON.stringify(`tab-${draw}`)}]`));
    const matchFor = id => page.locator(`.match[data-match-id=${JSON.stringify(id)}]`);
    const firstTab = tabFor(drawIds[0]);
    const wtt = /\/WTT-(Frankfurt|Montpellier)-2026\.html$/.test(new URL(page.url()).pathname);
    const kumamoto = page.url().includes('kumamoto-masters-2026');

    assert.equal(await firstTab.getAttribute('aria-selected'), 'true');
    assert.equal(await tabs.count(), drawIds.length);
    assert.equal(await page.locator('.match').count(), Object.values(draws).flat().length);
    for (const [draw, matches] of Object.entries(draws)) {
        await tabFor(draw).click();
        assert.equal(await tabFor(draw).getAttribute('aria-selected'), 'true');
        assert.equal(await tabs.and(page.locator('[aria-selected="true"]')).count(), 1);
        assert.equal(await panel.getAttribute('aria-labelledby'), `tab-${draw}`);
        if (wtt || kumamoto) {
            const rounds = page.locator('.columns:visible span');
            assert.equal(await rounds.count(), 5);
            if (wtt) assert.equal(matches.length, 31);
        }

        const groupFixtures = page.locator('.group details:not([open]) summary:visible, .preliminaries:not([open]) summary:visible');
        while (await groupFixtures.count()) await groupFixtures.first().click();
        const visible = await page.locator('.match:visible').evaluateAll(elements => elements.map(card => ({
            id: card.dataset.matchId,
            names: [...card.querySelectorAll('.player .name')].map(name => name.textContent),
            scores: [...card.querySelectorAll('.player .score')].map(score => score.textContent),
            winners: [...card.querySelectorAll('.player')].map(player => player.classList.contains('winner')),
            china: card.classList.contains('contains-cn'),
        })));
        assert.deepEqual(visible.sort((a, b) => a.id.localeCompare(b.id)), matches.map(match => ({
            id: match.id,
            names: match.players.map(player => player.name),
            scores: match.scores ? match.scores.map(String) : ['—', '—'],
            winners: match.players.map((_, index) => match.winner === index),
            china: match.players.some(player => player.team === 'CHN'),
        })).sort((a, b) => a.id.localeCompare(b.id)));

        const edges = await panel.locator('.wires path').evaluateAll(paths => paths
            .filter(path => getComputedStyle(path).display !== 'none')
            .map(path => `${path.dataset.sex}:${path.dataset.from}:${path.dataset.to}`));
        const preliminary = new Set(matches.filter(match => match.preliminary).map(match => match.id));
        const expectedEdges = matches.flatMap(match => match.feeders.filter(from => !preliminary.has(from))
            .map(from => `${draw}:${from}:${match.id}`));
        if (wtt || kumamoto) assert.equal(edges.length, 30);
        if (kumamoto) {
            assert.equal(preliminary.size, draw === 'MS' ? 1 : 0);
            for (const [from, to, count] of [['R32', 'R16', 8], ['R16', 'QF', 4], ['QF', 'SF', 2], ['SF', 'F', 1]]) {
                for (let i = 1; i <= count; i++) {
                    assert.ok(edges.includes(`${draw}:${draw}-${from}-${i * 2 - 1}:${draw}-${to}-${i}`));
                    assert.ok(edges.includes(`${draw}:${draw}-${from}-${i * 2}:${draw}-${to}-${i}`));
                }
            }
        }
        assert.deepEqual(edges.sort(), expectedEdges.sort());
    }

    if (page.url().includes('WTT-Frankfurt-2026')) {
        assert.deepEqual(await matchFor('women-l4-0').locator('.player .name').allTextContents(), ['大藤沙月', '早田希娜']);
        assert.deepEqual(await matchFor('women-l4-0').locator('.player .score').allTextContents(), ['2', '4']);
        assert.deepEqual(await matchFor('men-l4-0').locator('.player .name').allTextContents(), ['弗兰西斯卡', '张本智和']);
        assert.deepEqual(await matchFor('men-l4-0').locator('.player .score').allTextContents(), ['2', '4']);
    }
    if (kumamoto) {
        assert.deepEqual(drawIds, ['MS', 'WS', 'MD', 'WD', 'XD']);
        assert.deepEqual(await matchFor('MS-Q4').locator('.score').allTextContents(), ['2', '0']);
        assert.deepEqual(await matchFor('MS-R32-1').locator('.score').allTextContents(), ['—', '—']);
        assert.deepEqual(await matchFor('WD-R32-1').locator('.score').allTextContents(), ['2', '1']);
        assert.deepEqual(await matchFor('WD-R16-1').locator('.name').allTextContents(), ['福島由紀／松本麻佑', '第 02 场胜者']);
    }

    await firstTab.click();
    if (drawIds.length > 1) assert.equal(await tabFor(drawIds[1]).getAttribute('aria-selected'), 'false');
    const firstDraw = draws[drawIds[0]];
    const scoredMatch = firstDraw.find(match => match.games.length && match.resultLinks.length);
    if (wtt || kumamoto || groupFixture) assert.ok(scoredMatch, 'fixture must contain a scored match with evidence');
    const sampleMatch = scoredMatch || firstDraw[0];
    if (!sampleMatch) return;
    const firstMatch = matchFor(sampleMatch.id);
    await firstMatch.hover();
    assert.ok(await tooltip.isVisible());
    if (scoredMatch) assert.match(await tooltip.locator('.tip-note').allTextContents().then(lines => lines.join(' ')), /逐局/);
    if (wtt || kumamoto) {
        assert.equal(await panel.locator('.wires path.hot').count(), 4);
    }
    if (wtt) {
        assert.ok(await firstMatch.locator('.flag').count() > 0);
    }

    await firstMatch.click();
    await firstTab.hover();
    assert.ok(await tooltip.isVisible(), 'click should pin the tooltip');
    if (scoredMatch) {
        const links = await tooltip.locator('.tip-sources a').evaluateAll(anchors => anchors.map(anchor => anchor.getAttribute('href')));
        assert.ok(scoredMatch.resultLinks.every(link => links.includes(link.url)));
    }
    await page.keyboard.press('Escape');
    assert.equal(await tooltip.isVisible(), false);
    assert.equal(await panel.locator('.wires path.hot').count(), 0);

    await firstTab.focus();
    await firstMatch.focus();
    assert.ok(await tooltip.isVisible(), 'keyboard focus should reveal match details');
    await firstMatch.press('Enter');
    await firstTab.focus();
    assert.ok(await tooltip.isVisible(), 'Enter should pin the tooltip');
    await page.keyboard.press('Escape');
    assert.equal(await tooltip.isVisible(), false);

    const focusButton = page.locator('button.focus');
    await focusButton.click();
    assert.equal(await focusButton.getAttribute('aria-pressed'), 'true');
    if (wtt) {
        assert.ok(await panel.locator('.match.contains-cn:visible').count() > 0);
        await page.waitForFunction(id => getComputedStyle(document.querySelector(`[data-match-id="${CSS.escape(id)}"]`)).opacity === '0.28', scoredMatch.id);
    }
    await focusButton.click();
    assert.equal(await focusButton.getAttribute('aria-pressed'), 'false');

    const sources = page.locator('#sources');
    const sourcesButton = page.locator('#source-button');
    await sourcesButton.click();
    assert.equal(await sourcesButton.getAttribute('aria-expanded'), 'true');
    assert.ok(await sources.isVisible());
    await sourcesButton.click();
    assert.equal(await sources.isVisible(), false);

    if (groupFixture) {
        assert.equal(await page.locator('.group table:visible').count(), 2);
        await matchFor('F').focus();
        assert.equal(await panel.locator('.wires path.hot').count(), 2);
        assert.equal(await page.locator('.group[data-group-id].selected').count(), 2);
        await page.keyboard.press('Escape');
    }

    await page.setViewportSize({width: 390, height: 844});
    await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
    await page.locator('.shell').evaluate(shell => { shell.scrollLeft = 0; });
    await page.waitForFunction(() => {
        const button = document.querySelector('button.focus').getBoundingClientRect();
        return button.left >= 0 && button.right <= innerWidth + 1;
    }, null, {timeout: 3000});
    if (wtt) assert.ok(await page.locator('.shell').evaluate(shell => shell.scrollWidth > shell.clientWidth), 'WTT bracket must scroll inside its shell on mobile');
}

async function main() {
    const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'sports-browser-'));
    try {
        const page = await browser.newPage({viewport: {width: 1280, height: 900}});
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(index);
        const links = await page.locator('main li a').evaluateAll(anchors => anchors.map(anchor => anchor.href));
        assert.ok(links.length >= 7, 'the tournament index is incomplete');
        const dates = await page.locator('main li .event-date time:first-child').evaluateAll(times => times.map(time => time.dateTime));
        assert.ok(dates.length >= 7, 'the tournament dates are missing');
        assert.deepEqual(dates, [...dates].sort().reverse());
        let brackets = 0;
        for (const link of links) {
            await page.setViewportSize({width: 1280, height: 900});
            await page.goto(link);
            assert.ok(await page.title(), link);
            const connected = /\/(?:WTT-(?:Frankfurt|Montpellier)-2026\.html|20261110-2200-kumamoto-masters-2026\/index\.html)$/.test(new URL(link).pathname);
            const hasBracket = await page.locator('#wtt-data').count();
            if (connected || hasBracket) {
                await checkConnectedBracket(page);
                brackets++;
            }
            const backLink = page.getByRole('link', {name: '返回赛事', exact: false});
            const back = await backLink.evaluate(anchor => anchor.href);
            await backLink.click();
            assert.equal(page.url(), connected || !hasBracket ? index : back);
        }
        const example = path.join(scratch, 'groups-knockout.html');
        execFileSync(process.env.PYTHON || 'python3', ['sports/core/bracketkit.py',
            'sports/core/examples/groups-knockout.json', '-o', example], {cwd: root});
        await page.goto(pathToFileURL(example).href);
        await checkConnectedBracket(page, true);
        assert.deepEqual(errors, []);
        console.log(`Browser checks passed: ${links.length} tournament links, ${brackets} live brackets and the group-to-knockout example`);
    } finally {
        await browser.close();
        fs.rmSync(scratch, {recursive: true, force: true});
    }
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
