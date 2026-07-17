Vendored, unmodified third-party Lovelace frontend cards this integration's generated dashboard
depends on. Bundled directly (rather than requiring a separate manual HACS install) so the
dashboard works immediately on any install, per this project's "no manual steps" design goal -
see `assets.py`/`dashboard/register.py`.

- `button-card.js` - [custom-cards/button-card](https://github.com/custom-cards/button-card)
  v7.0.1, [MIT license](https://github.com/custom-cards/button-card/blob/master/LICENSE).
- `bubble-card.js` (+ `bubble-card.js.LICENSE.txt`) -
  [Clooos/Bubble-Card](https://github.com/Clooos/Bubble-Card) v3.2.5,
  [MIT license](https://github.com/Clooos/Bubble-Card/blob/main/LICENSE).
- `config-template-card.js` -
  [iantrich/config-template-card](https://github.com/iantrich/config-template-card) v1.3.6,
  [MIT license](https://github.com/iantrich/config-template-card/blob/master/LICENSE).
- `week-planner-card.js` -
  [FamousWolf/week-planner-card](https://github.com/FamousWolf/week-planner-card) v1.14.1,
  [MIT license](https://github.com/FamousWolf/week-planner-card/blob/main/LICENSE). This is the
  exact version this integration's calendar view was built and validated against (see
  `modules/calendar/dashboard.py`'s module docstring for its filter-semantics dependency on this
  specific version's internals) - do not bump without re-verifying that behavior.
