// Shared bootstrap: isolated CI never reads .env, local workspace data or Skill dependencies.
const fs = require("node:fs");
const path = require("node:path");
const isolated = process.env.BROWSER_TEST_ISOLATED === "1";
const env =
  isolated || !fs.existsSync(".env")
    ? {}
    : Object.fromEntries(
        fs
          .readFileSync(".env", "utf8")
          .split("\n")
          .filter((line) => line.includes("=") && !line.startsWith("#"))
          .map((line) => {
            const index = line.indexOf("=");
            return [line.slice(0, index), line.slice(index + 1)];
          }),
      );
const baseURL =
  process.env.BASE_URL || "http://127.0.0.1:" + (env.PORT || 8000);
const password = process.env.ADMIN_PASSWORD || env.ADMIN_PASSWORD;
const outputDir = process.env.BROWSER_TEST_OUTPUT || ".data/e2e";
fs.mkdirSync(outputDir, { recursive: true });
let implementation;
if (isolated)
  implementation = require("./browser-tests/node_modules/playwright");
else {
  const rid = JSON.parse(
    fs.readFileSync(".data/runtimes/active.json"),
  ).runtime_id;
  implementation = require(
    path.join(
      process.cwd(),
      ".data/runtimes",
      rid,
      "skill/node_modules/playwright-core",
    ),
  );
}
// Apply network isolation before the scripts register their mock routes.
const chromium = {
  async launch(options) {
    if (isolated) {
      delete options.executablePath;
      if (process.env.BROWSER_TEST_CHROME)
        options.executablePath = process.env.BROWSER_TEST_CHROME;
    }
    const browser = await implementation.chromium.launch(options);
    const newPage = browser.newPage.bind(browser);
    browser.newPage = async (...args) => {
      const page = await newPage(...args);
      if (isolated) {
        await page.context().route("**/*", (route) => {
          const url = new URL(route.request().url());
          return url.origin === new URL(baseURL).origin ||
            ["blob:", "data:"].includes(url.protocol)
            ? route.continue()
            : route.abort("blockedbyclient");
        });
      }
      return page;
    };
    return browser;
  },
};
module.exports = { fs, path, env, chromium, baseURL, password, outputDir };
