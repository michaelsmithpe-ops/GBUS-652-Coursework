# Week 01

Materials and coursework for Week 1 of GBUS 652: AI & LLM Foundations.

## Tic-Tac-Toe

[`index.html`](index.html) is a single-page browser game of Tic-Tac-Toe against the computer, built with plain HTML, CSS, and JavaScript (no dependencies). Open the file in any modern browser to play.

- **You are X, the computer is O.** The first move alternates each round.
- **Three difficulty levels:**
  - *Easy*: takes wins and usually blocks, but makes mistakes.
  - *Medium*: plays real strategy (win, block, create forks, center, corners) but doesn't defend against forks, so it can be beaten.
  - *Hard*: full minimax search; it never loses.
- **Extras:** animated moves and win line, scoreboard saved between visits, optional sound effects, and keyboard play (`1`–`9` to pick a square, `N` for a new round).
