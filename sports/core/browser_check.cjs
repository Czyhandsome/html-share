const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '../..');
const index = pathToFileURL(path.join(root, 'docs/2026/11/20261104-1042-sports-brackets/index.html')).href;

async function checkBracket(page, groupFixture = false) {
    const model = JSON.parse(await page.locator('#tournament-data').textContent());
    const cards = page.locator('.match');
    const rendered = await cards.evaluateAll(elements => Object.fromEntries(elements.map(card => [card.dataset.matchId, {
        scores: [...card.querySelectorAll('.player strong')].map(score => score.textContent),
        winners: card.querySelectorAll('.winner').length,
    }])));
    assert.equal(await cards.count(), model.matches.length);
    for (const match of model.matches) {
        assert.deepEqual(rendered[match.id], {
            scores: match.score ? match.score.map(String) : ['—', '—'],
            winners: Number(Boolean(match.winner)),
        }, match.id);
    }

    await page.locator('#search').fill('没有这个测试选手');
    assert.equal(await page.locator('.match:visible').count(), 0);
    await page.locator('#clear').click();
    assert.equal(await page.locator('.match:visible').count(), model.matches.length);

    const chinese = new Set(model.entries.filter(entry => entry.team === 'CHN').map(entry => entry.id));
    const chineseMatches = model.matches.filter(match => match.players.some(player => chinese.has(player)));
    await page.locator('#china-only').check();
    assert.equal(await page.locator('.match:visible').count(), chineseMatches.length);
    if (page.url().includes('WTT-')) assert.ok(chineseMatches.length > 0, 'WTT team data missing');
    await page.locator('#clear').click();

    const draw = model.draws[0].id;
    await page.locator('#draw-filter').selectOption(draw);
    assert.equal(await page.locator('.match:visible').count(), model.matches.filter(match => (match.draw || 'main') === draw).length);
    await page.locator('#clear').click();

    if (model.matches.some(match => match.slots.some(slot => slot.winner || slot.group_rank))) {
        const last = model.matches.findLast(match => match.slots.some(slot => slot.winner || slot.group_rank));
        await cards.filter({has: page.getByRole('heading', {name: last.id, exact: true})}).locator('.route').click();
        assert.ok(await page.locator('.selected').count() >= 2);
        if (groupFixture) assert.equal(await page.locator('.selected').count(), 9);
        await page.locator('#clear').click();
        assert.equal(await page.locator('.selected').count(), 0);
    }
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile document overflows');
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
        let brackets = 0;
        for (const link of links) {
            await page.setViewportSize({width: 1280, height: 900});
            await page.goto(link);
            assert.ok(await page.title(), link);
            if (await page.locator('#tournament-data').count()) {
                await checkBracket(page);
                await page.getByRole('link', {name: '返回赛事索引', exact: false}).click();
                assert.equal(page.url(), index);
                brackets++;
            }
        }
        const example = path.join(scratch, 'groups-knockout.html');
        execFileSync(process.env.PYTHON || 'python3', ['sports/core/bracketkit.py',
            'sports/core/examples/groups-knockout.json', '-o', example], {cwd: root});
        await page.goto(pathToFileURL(example).href);
        await checkBracket(page, true);
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
