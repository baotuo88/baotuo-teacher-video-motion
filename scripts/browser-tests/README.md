# Isolated browser regressions

Run from the repository root:

```sh
python3 -m pip install -r backend/requirements-dev.txt
npm ci --prefix scripts/browser-tests
(cd scripts/browser-tests && npx playwright install --with-deps chromium)
python3 scripts/browser-ci.py
```

The runner creates a temporary SQLite workspace, random admin password and encryption key,
starts only the API on a temporary localhost port, runs seven browser scripts, then stops the
API and deletes the temporary workspace. No Worker, upstream runtime or real provider credentials
are loaded. Browser requests outside the test origin are blocked; page-level fixture routes
simulate generation, streaming, history and recovery responses.

Results, screenshots and server/test logs go to `.data/browser-ci/` (ignored by Git).
`BROWSER_TEST_OUTPUT` selects another output directory. Do not point it at a sensitive directory
or publish logs from a real production browser session.

The CI job uses Playwright's managed Chromium on Ubuntu. On an unsupported local macOS release,
you can use an existing browser while keeping the isolated API/database:

```sh
BROWSER_TEST_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  python3 scripts/browser-ci.py
```

This override verifies browser behavior locally, not the Ubuntu-managed Chromium installation.
Individual `node scripts/browser-*.cjs` scripts still support the existing local dev server,
`.env` and installed Skill Playwright dependency when isolated mode is not enabled.

Coverage: responsive workspace, stage routing, unsaved draft recovery, save-while-typing,
project task stream, trash and restore, scene scroll, production preferences,
player node reuse, paged history/logs, and provider capability forms.
Mocked UI tests do not replace real API/integration tests or container rendering acceptance.

The container workflow requires both `test` and `browser` to pass before building the image.
Container smoke and actual video render checks must then pass before GHCR login/publish.
