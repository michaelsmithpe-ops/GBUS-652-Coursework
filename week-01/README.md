# Week 01

Materials and coursework for Week 1 of GBUS 652: AI & LLM Foundations.

## Tic-Tac-Toe

[`Tic-Tac-Toe.html`](Tic-Tac-Toe.html) is a single-page browser game of Tic-Tac-Toe, built with plain HTML, CSS, and JavaScript (no dependencies).

**▶ [Play it online](https://michaelsmithpe-ops.github.io/GBUS-652-Coursework/week-01/Tic-Tac-Toe.html)**, or download the file and open it in any modern browser.

- **Two modes:** play *vs Computer*, or switch to *2 Players* to take turns with someone on the same device. Each mode keeps its own scoreboard.
- **X and O alternate who moves first each round.** Against the computer, you are X.
- **Three difficulty levels** (vs Computer):
  - *Easy*: takes wins and usually blocks, but makes mistakes.
  - *Medium*: plays real strategy (win, block, create forks, center, corners) but doesn't defend against forks, so it can be beaten.
  - *Hard*: full minimax search; it never loses.
- **Extras:** animated moves and win line, scoreboard saved between visits, optional sound effects, and keyboard play (`1`–`9` to pick a square, `N` for a new round).
