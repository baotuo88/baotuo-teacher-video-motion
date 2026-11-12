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
  fs.mkdirSync(outputDir, { recursive: true });

  await page.addInitScript(() => {
    window.EventSource = class {
      constructor(url) {
        this.listeners = {};
        window.testStream = this;
      }
      addEventListener(type, fn) {
        this.listeners[type] = fn;
      }
      close() {
        this.closed = true;
      }
    };
  });
  await page.reload();
  await page.locator("#app").waitFor({ state: "visible" });
  const project = {
    id: "project-task-fixture",
    title: "项目内任务验收",
    topic: "",
    version: 1,
    confirmed: true,
    style: "whiteboard",
    scenes: [
      {
        title: "测试页面",
        narration: "测试口播",
        points: ["测试"],
        duration: 3,
        layout: "points",
      },
    ],
  };
  let deleted = false,
    submitted = false;
  await page.route("**/api/projects/*/production-settings", (r) =>
    r.fulfill({
      json: {
        version: 0,
        audio: "silent",
        voice: "zh-CN-XiaoxiaoNeural",
        provider: "",
      },
    }),
  );
  await page.route("**/api/projects", (r) =>
    r.fulfill({ json: deleted ? [] : [project] }),
  );
  await page.route("**/api/projects/" + project.id, (r) => {
    if (r.request().method() === "DELETE") {
      deleted = true;
      return r.fulfill({ json: { deleted: true } });
    }
    return r.fulfill({ json: project });
  });
  await page.route("**/api/projects/" + project.id + "/render", (r) => {
    submitted = true;
    return r.fulfill({ json: { id: "job-fixture" } });
  });
  await page.locator("[data-nav=projects]").click();
  await page.getByText(project.title, { exact: true }).click();
  await page.locator(".studio-shell").waitFor();
  await page.locator("[data-stage-link=export]").click();
  await page
    .getByRole("button", { name: "提交制作任务 →", exact: true })
    .click();
  if (!submitted) throw Error("Render not submitted");
  if ((await page.locator("#heading").textContent()) !== project.title)
    throw Error("Left project");
  await page.getByText("任务已提交", { exact: true }).waitFor();
  const job = {
    id: "job-fixture",
    project_id: project.id,
    snapshot: { project },
    status: "running",
    kind: "render",
    created: Date.now() / 1000,
  };
  async function emit(message) {
    await page.evaluate(
      ({ job, message }) =>
        window.testStream.listeners.snapshot({
          data: JSON.stringify({
            jobs: [job],
            events: { [job.id]: [{ created: Date.now() / 1000, message }] },
          }),
        }),
      { job, message },
    );
  }
  await emit("正在合成配音");
  await page.locator("[data-stage-link=results]").click();
  await page.locator(".live-log").filter({ hasText: "正在合成配音" }).waitFor();
  await page.locator("[data-stage-link=storyboard]").click();
  await page
    .locator("#scene-0 textarea")
    .first()
    .fill("实时日志更新不能覆盖这段编辑");
  await emit("开始渲染视频");
  if (
    (await page.locator("#scene-0 textarea").first().inputValue()) !==
    "实时日志更新不能覆盖这段编辑"
  )
    throw Error("Input overwritten");
  await page.locator("[data-stage-link=results]").click();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.locator("#project-tasks").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: outputDir + "/project-tasks-" + width + ".png",
      fullPage: true,
    });
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw Error("Overflow");
  }
  await page.locator(".project-menu > summary").click();
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "删除项目", exact: true }).click();
  if (deleted) throw Error("Deleted after cancel");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "删除项目", exact: true }).click();
  await page
    .getByText("项目已移入回收站，可从项目列表恢复；历史和成片已保留。", {
      exact: true,
    })
    .waitFor();
  if (!deleted) throw Error("Deletion missing");
  if (!(await page.evaluate(() => window.testStream.closed)))
    throw Error("Stream not closed");
  let restoreConflict = true;
  await page.route("**/api/project-trash", (r) =>
    r.fulfill({
      json: deleted ? [{ ...project, deleted_at: Date.now() / 1000 }] : [],
    }),
  );
  await page.route("**/api/project-trash/" + project.id + "/restore", (r) => {
    if (r.request().postDataJSON().version !== project.version)
      throw Error("Restore omitted version");
    if (restoreConflict)
      return r.fulfill({ status: 409, json: { detail: "回收站版本已变化" } });
    deleted = false;
    project.version++;
    return r.fulfill({ json: project });
  });
  await page.getByRole("button", { name: "回收站", exact: true }).click();
  const trash = page.locator(".project-trash-dialog");
  await trash
    .getByRole("heading", { name: project.title, exact: true })
    .waitFor();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    if (await trash.evaluate((n) => n.scrollWidth > n.clientWidth + 1))
      throw Error("Trash dialog overflow");
  }
  await trash.getByRole("button", { name: "恢复项目", exact: true }).click();
  await trash.getByText(/恢复未完成/).waitFor();
  if (!deleted) throw Error("Failed restore lost trash item");
  restoreConflict = false;
  await trash.getByRole("button", { name: "恢复项目", exact: true }).click();
  await trash.getByRole("heading", { name: "回收站为空" }).waitFor();
  await trash.getByRole("button", { name: "关闭", exact: true }).click();
  await page
    .locator("article.card")
    .getByText(project.title, { exact: true })
    .click();
  await page.locator(".studio-shell").waitFor();
  if (!(await page.locator("#save-state").textContent()).includes("v2"))
    throw Error("Restored project version missing");
  if (errors.length) throw Error(errors.join(";"));
  console.log(
    JSON.stringify({
      inProjectSubmission: true,
      liveLogs: true,
      editsPreserved: true,
      deleteConfirmation: true,
      trashRestore: true,
      trashConflict: true,
      streamClosed: true,
      errors,
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
