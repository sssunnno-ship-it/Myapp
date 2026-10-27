# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

A single-file Streamlit shopping list (`app.py`). All four build stages in `PROMPTS.md` are done (skeleton → features → UI → Playwright review), and the bugs from the review are fixed. Not a git repository yet; not yet deployed.

- `PRD.md` — product requirements (Korean). Source of truth for features, data model, UI layout, and acceptance criteria. Feature IDs `F-1`–`F-9` are referenced in code docstrings.
- `PROMPTS.md` — the staged build prompts. Stage 4 is the review checklist to re-run after significant changes.

Write user-facing text and replies in Korean.

## Commands

```bash
pip install -r requirements.txt
streamlit run app.py                                              # opens a browser
streamlit run app.py --server.headless true --server.port 8501    # for Playwright testing
```

Streamlit picks up `app.py` edits on the next rerun, but `.streamlit/config.toml` (theme) changes need a server restart.

## Testing

No test framework or linter is set up.
- **Logic checks:** use `streamlit.testing.v1.AppTest`. Two `AppTest` instances act as two tabs, which is how to test multi-session behaviour. AppTest does not emulate `clear_on_submit`, so the "input clears after add" check always fails there; verify it in a real browser.
- **UI checks:** use Playwright against the running server. Click a checkbox through `[data-testid="stCheckbox"] label`; the input itself is hidden. Row actions are icon buttons named `✏️` / `🗑️`. The edit row uses text buttons `저장` / `취소`. Item names are `.item-name` (with `.done` when checked). Rows are `[class*="st-key-row_"]`. Wait for `[data-testid="stStatusWidget"]` to disappear after each action.
- Both kinds of test read and write the real `data/items.json`, so back it up first and remove it afterwards. Playwright screenshots can only be saved inside the project; they go in `.playwright-mcp/`, which is gitignored.
- `ConnectionResetError` tracebacks in the server log on Windows come from page reloads closing the websocket. They are harmless.

## Architecture

- **The file is the source of truth, not the session.** Each tab or device gets its own session. `init_state()` reloads `data/items.json` on every rerun into `st.session_state.shopping_items`. Don't use the name `.items`: it collides with the dict-like `items()` method. Never mutate that list and save it directly. Go through `mutate(change)` or `update_item(id, **fields)`: they re-read the file under a shared `st.cache_resource` RLock, apply the change, and save. Saving the session copy overwrites other tabs' changes.
- **Persistence:** `save_items()` writes a `.json.tmp` file and then calls `os.replace`, so readers never see a half-written file. `load_items()` returns `[]` when the file is missing. When the file is corrupt, it first copies it to `items.json.bak` and then returns `[]`. `normalize_item()` fills in fields that older data lacks (`quantity` defaults to 1).
- **All state changes happen in `on_*` callbacks** (`on_click` / `on_change`), never inline after a widget, so the UI never renders one rerun behind. `mutate()` also closes the pending "전체 삭제" confirmation (`confirm_clear`).
- **Validation lives in `validate(name, qty)`, not in widget limits.** `max_chars` drops a too-long paste entirely, and `min_value`/`max_value` silently revert out-of-range numbers. So the inputs have no limits, and the callbacks store a warning in `add_error` / `edit_error`.
- **Widget keys are derived from the item `id`** (`check_`, `edit_`, `delete_`, `edit_name_`, `edit_qty_`, `save_`, `cancel_`), because duplicate names are allowed. `render_item_row` writes `st.session_state[f"check_{id}"]` from the file before creating the checkbox (no `value=`), so changes from another tab override stale widget state. `on_start_edit` seeds the edit widgets the same way.
- **UI:** the `CSS` block is injected with `st.html` and forces `st.columns` to stay on one row at mobile widths. Every column holding a button must match the `:has(.stButton, .stFormSubmitButton)` rule, or it gets squeezed or wraps its label. Item names render through `st.html` with `html.escape`, not markdown. The list displays unchecked items first; the stored order is unchanged.

## Known limitations

- Other tabs don't update live. They see changes on their next interaction or reload.
- `clear_on_submit` also clears the input when validation fails, so the user has to retype.
- The file lock only works within a single server process. On Streamlit Cloud the filesystem is ephemeral and shared by every visitor, so v1.0 is a single personal list. Durable storage (Google Sheets, Supabase, SQLite) is a future change.

## Constraints from PRD

- Keep everything in `app.py`. The target is about 300 lines; it is currently 317.
- Out of scope: auth, multiple lists, sharing, categories, prices.
- Must work at mobile width (~390px) without horizontal scroll, in both light and dark themes.
