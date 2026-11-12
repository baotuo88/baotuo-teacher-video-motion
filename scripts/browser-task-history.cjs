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

  await page.route("**/api/projects", (r) => r.fulfill({ json: [project] }));
  await page.route("**/api/projects/review-fixture", (r) =>
    r.fulfill({ json: project }),
  );
  await page.route("**/api/projects/review-fixture/production-settings", (r) =>
    r.fulfill({
      json: {
        version: 0,
        audio: "silent",
        voice: "zh-CN-XiaoxiaoNeural",
        provider: "",
      },
    }),
  );
  const jobs = Array.from({ length: 105 }, (_, index) => ({
    id: "history-" + String(105 - index).padStart(3, "0"),
    project_id: project.id,
    kind: "render",
    status: "succeeded",
    created: 200 - index,
    updated: 200 - index,
    snapshot: { project },
    result: {
      artifacts:
        index === 0 ? [{ name: "video-有字幕.mp4", kind: "video" }] : [],
    },
  }));
  let historyRequests = 0;
  await page.route("**/api/projects/review-fixture/job-history?*", (r) => {
    historyRequests++;
    if (new URL(r.request().url()).searchParams.get("before") !== jobs[99].id)
      throw Error("Wrong history cursor");
    return r.fulfill({ json: { items: jobs.slice(100), next_cursor: null } });
  });
  const events = Array.from({ length: 451 }, (_, i) => ({
    id: i + 1,
    created: i,
    message: "历史日志-" + i,
  }));
  const afters = [];
  await page.route("**/api/jobs/history-001/events?*", (r) => {
    const after = Number(new URL(r.request().url()).searchParams.get("after"));
    afters.push(after);
    return r.fulfill({
      json: events.filter((e) => e.id > after).slice(0, 200),
    });
  });
  await page.route("**/api/jobs/history-001/logs.txt", (r) =>
    r.fulfill({
      contentType: "text/plain",
      headers: { "Content-Disposition": "attachment; filename=logs.txt" },
      body: events.map((e) => e.message).join("\n"),
    }),
  );
  await page.reload();
  await page.locator("#app").waitFor({ state: "visible" });
  await page
    .locator("article.card")
    .getByText(project.title, { exact: true })
    .click();
  await page.locator("[data-stage-link=results]").click();
  async function snapshot(items) {
    await page.evaluate(
      (jobs) =>
        window.reviewStream.listeners.snapshot({
          data: JSON.stringify({ jobs, events: {} }),
        }),
      items,
    );
  }
  await snapshot(jobs.slice(0, 100));
  if ((await page.locator("[data-job-id]").count()) !== 100)
    throw Error("Wrong initial count");
  await page.evaluate(
    () =>
      (window.playerBeforeHistory = document.querySelector(
        "#project-job-list video",
      )),
  );
  await page.getByRole("button", { name: "加载更早任务", exact: true }).click();
  await page.locator('[data-job-id="history-001"]').waitFor();
  if ((await page.locator("[data-job-id]").count()) !== 105)
    throw Error("Old tasks missing");
  const newer = {
    ...jobs[0],
    id: "new-task",
    created: 300,
    updated: 300,
    result: null,
    status: "running",
  };
  await snapshot([newer, ...jobs.slice(0, 99)]);
  if ((await page.locator("[data-job-id]").count()) !== 106)
    throw Error("SSE discarded loaded history");
  if (
    await page.evaluate(
      () =>
        window.playerBeforeHistory !==
        document.querySelector("#project-job-list video"),
    )
  )
    throw Error("History load replaced player");
  const old = page.locator('[data-job-id="history-001"]');
  if (
    !(await old.locator(".live-log").textContent()).includes("不在实时日志窗口")
  )
    throw Error("Old task log misleading");
  await old.getByRole("button", { name: "查看日志", exact: true }).click();
  await old
    .getByText("已读取 200 条日志。还有后续日志可继续加载。", { exact: true })
    .waitFor();
  await old.getByRole("button", { name: "加载后续日志", exact: true }).click();
  await old
    .getByText("已读取 400 条日志。还有后续日志可继续加载。", { exact: true })
    .waitFor();
  await old.getByRole("button", { name: "加载后续日志", exact: true }).click();
  await old
    .locator(".manual-log")
    .filter({ hasText: "历史日志-450" })
    .waitFor();
  if (afters.join(",") !== "0,200,400") throw Error("Bad log pagination");
  if (
    (await old.locator(".manual-log").textContent()).split("\n").length !== 451
  )
    throw Error("Duplicated or skipped logs");
  // Replacing a changed task card must keep the log panel and its paging cursor.
  await snapshot([{ ...jobs[104], updated: 400 }, newer, ...jobs.slice(0, 98)]);
  await old.getByRole("button", { name: "刷新后续日志" }).click();
  if (afters.at(-1) !== 451) throw Error("Lost log cursor during update");
  // Real authenticated download completeness is covered by test_task_history.py.
  if (
    (await old
      .getByRole("link", { name: "下载完整日志" })
      .getAttribute("href")) !== "/api/jobs/history-001/logs.txt"
  )
    throw Error("Wrong download target");
  await page.setViewportSize({ width: 390, height: 1000 });
  if (
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth + 1,
    )
  )
    throw Error("History view mobile overflow");
  if (historyRequests !== 1) throw Error("Unexpected repeated history fetch");
  if (errors.length) throw Error(errors.join(";"));
  console.log(
    JSON.stringify({
      historyBeyond100: true,
      sseRetainsHistory: true,
      playerPreserved: true,
      logs451: true,
      logCursorPreserved: true,
      mobile: true,
      errors,
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
