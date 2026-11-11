'use strict';

const board = document.querySelector('#team-bracket');
const tabs = [...board.querySelectorAll('[role=tab]')];
const focusButton = board.querySelector('.focus');
const dialog = document.querySelector('#tie-dialog');
const detail = document.querySelector('#tie-detail');

function selectTab(tab) {
    for (const candidate of tabs) {
        const selected = candidate === tab;
        candidate.setAttribute('aria-selected', selected);
        candidate.tabIndex = selected ? 0 : -1;
        document.getElementById(candidate.getAttribute('aria-controls')).hidden = !selected;
    }
}

for (const [index, tab] of tabs.entries()) {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', event => {
        const targets = {
            ArrowLeft: (index - 1 + tabs.length) % tabs.length,
            ArrowRight: (index + 1) % tabs.length,
            Home: 0,
            End: tabs.length - 1,
        };
        if (!Object.hasOwn(targets, event.key)) return;
        event.preventDefault();
        const target = tabs[targets[event.key]];
        selectTab(target);
        target.focus();
    });
}

focusButton.addEventListener('click', () => {
    const pressed = focusButton.getAttribute('aria-pressed') !== 'true';
    focusButton.setAttribute('aria-pressed', pressed);
    board.classList.toggle('focus-china', pressed);
});

board.addEventListener('click', event => {
    const card = event.target.closest('button[data-detail]');
    if (!card) return;
    const template = document.getElementById(card.dataset.detail);
    detail.replaceChildren(template.content.cloneNode(true));
    dialog.showModal();
});
