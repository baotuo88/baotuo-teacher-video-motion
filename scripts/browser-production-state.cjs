// Read-only authenticated UI / artifact inspection. Requires scripts/dev.py running.
const {
  fs,
  path,
  env,
  chromium,
  baseURL,
  password,
  outputDir,
} = require("./browser-test-support.cjs");
(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.CHROME_PATH ||
      (process.platform === "darwin"
        ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        : "/usr/bin/chromium"),
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(baseURL);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "进入工作台 →" }).click();
  await page.locator("#app").waitFor({ state: "visible" });

  await page.addInitScript(() => {
    window.EventSource = class {
      constructor() {
        this.listeners = {};
        window.reviewStream = this;
      }
      addEventListener(k, f) {
        this.listeners[k] = f;
      }
      close() {}
    };
  });
  const project = {
    id: "review-fixture",
    title: "整体检查模拟项目",
    topic: "",
    version: 1,
    confirmed: true,
    style: "whiteboard",
    scenes: [
      {
        title: "第一页",
        narration: "口播",
        points: ["要点"],
        duration: 3,
        layout: "points",
      },
    ],
  };
  let settings = {
    version: 0,
    audio: "silent",
    voice: "zh-CN-XiaoxiaoNeural",
    provider: "",
  };
  let failSave = false;
  await page.route(
    "**/api/projects/review-fixture/production-settings",
    async (r) => {
      if (r.request().method() === "PUT") {
        if (failSave)
          return r.fulfill({ status: 409, json: { detail: "并发设置冲突" } });
        await new Promise((resolve) => setTimeout(resolve, 150));
        settings = {
          ...r.request().postDataJSON(),
          version: settings.version + 1,
        };
      }
      return r.fulfill({ json: settings });
    },
  );
  await page.route("**/api/projects", (r) => r.fulfill({ json: [project] }));
  await page.route("**/api/projects/review-fixture", (r) =>
    r.fulfill({ json: project }),
  );
  await page.reload();
  await page.locator("#app").waitFor({ state: "visible" });
  await page
    .locator("article.card")
    .getByText(project.title, { exact: true })
    .click();
  await page.locator("[data-stage-link=results]").click();
  const job = {
    id: "review-job",
    project_id: project.id,
    kind: "render",
    status: "succeeded",
    snapshot: { project },
    created: 1,
    result: { artifacts: [{ name: "video-有字幕.mp4", kind: "video" }] },
  };
  await page.evaluate(
    (job) =>
      window.reviewStream.listeners.snapshot({
        data: JSON.stringify({ jobs: [job], events: {} }),
      }),
    job,
  );
  await page.evaluate(
    () =>
      (window.previousPlayer = document.querySelector(
        "#project-job-list video",
      )),
  );
  await page.route("**/api/jobs/review-job/events?*", (r) =>
    r.fulfill({ json: [{ created: 1, message: "已展开的任务日志" }] }),
  );
  await page
    .locator('[data-job-id="review-job"]')
    .getByRole("button", { name: "查看日志" })
    .click();
  await page.locator(".manual-log").waitFor();
  await page.evaluate(() => {
    window.previousLog = document.querySelector(".manual-log");
  });
  await page.evaluate(
    (job) =>
      window.reviewStream.listeners.snapshot({
        data: JSON.stringify({
          jobs: [
            { ...job, id: "other-job", status: "running", result: null },
            job,
          ],
          events: {},
        }),
      }),
    job,
  );
  if (
    await page.evaluate(
      () =>
        window.previousPlayer !==
        document.querySelector("#project-job-list video"),
    )
  )
    throw Error("Unrelated task replaced player");
  if (
    await page.evaluate(
      () =>
        window.previousLog !== document.querySelector(".manual-log") ||
        !window.previousLog.textContent.includes("已展开的任务日志"),
    )
  )
    throw Error("Expanded logs lost during task refresh");
  await page.locator("[data-stage-link=export]").click();
  await page.getByLabel("音轨来源", { exact: true }).selectOption("edge");
  await page.locator("[data-nav=projects]").click();
  await page
    .locator("article.card")
    .getByText(project.title, { exact: true })
    .click();
  await page.locator("[data-stage-link=export]").click();
  if (
    (await page.getByLabel("音轨来源", { exact: true }).inputValue()) !== "edge"
  )
    throw Error("Audio mode lost after reopen");
  await page
    .getByLabel("在线配音音色", { exact: true })
    .selectOption("zh-CN-YunxiNeural");
  await page.getByLabel("音轨来源", { exact: true }).selectOption("uploaded");
  await page.getByLabel("音轨来源", { exact: true }).selectOption("edge");
  await page.waitForFunction(() => state.settingsSession.saving === 0);
  await page.reload();
  await page
    .getByLabel("音轨来源", { exact: true })
    .waitFor({ state: "visible" });
  if (
    (await page.getByLabel("音轨来源", { exact: true }).inputValue()) !==
      "edge" ||
    (await page.getByLabel("在线配音音色", { exact: true }).inputValue()) !==
      "zh-CN-YunxiNeural"
  )
    throw Error("Rapid settings changes lost after reload");
  failSave = true;
  await page.getByLabel("音轨来源", { exact: true }).selectOption("uploaded");
  await page.waitForFunction(() => state.settingsSession.saving === 0);
  if (!(await page.locator("#notice").textContent()).includes("制作设置未保存"))
    throw Error("Save conflict hidden");
  if (settings.audio !== "edge")
    throw Error("Failed save overwrote stored settings");
  if (errors.length) throw Error(errors.join("\n"));
  console.log(
    "PASS: player identity, settings reopen/reload, serialized saves, visible conflict",
  );
  console.log("page_errors", errors);
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
