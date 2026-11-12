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
  if (await page.locator("[data-nav=jobs]").count())
    throw Error("Global tasks navigation still exists");
  await page.evaluate(() => {
    location.hash = "#/jobs";
  });
  await page.waitForURL("**/#/projects");
  let globalJobRequests = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/jobs") globalJobRequests++;
  });

  await page.addInitScript(() => {
    window.EventSource = class {
      constructor() {
        this.listeners = {};
        window.testStream = this;
      }
      addEventListener(k, f) {
        this.listeners[k] = f;
      }
      close() {
        this.closed = true;
      }
    };
  });
  const project = {
    id: "studio-fixture",
    title: "为什么天空是蓝色的",
    topic: "面向小学生讲解光的散射",
    version: 1,
    confirmed: true,
    style: "whiteboard",
    scenes: [0, 1, 2].map((i) => ({
      title: ["从一束阳光开始", "空气中的散射", "看见蓝色的天空"][i],
      narration: "阳光看上去是白色，其实包含不同颜色的光。",
      points: ["阳光由多种颜色组成", "不同颜色有不同的波长"],
      duration: 5,
      layout: "points",
    })),
  };
  let submitted = 0;
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
  await page.route("**/api/projects", (r) => r.fulfill({ json: [project] }));
  await page.route("**/api/projects/studio-fixture", (r) =>
    r.fulfill({ json: project }),
  );
  await page.route("**/api/projects/studio-fixture/render", (r) => {
    submitted++;
    return r.fulfill({ json: { id: "render-fixture" } });
  });
  await page.reload();
  await page.locator("#app").waitFor({ state: "visible" });
  await page.getByText(project.title, { exact: true }).click();
  await page.locator(".studio-shell").waitFor();
  async function stage(name) {
    await page.locator("[data-stage-link=" + name + "]").click();
  }
  await page.locator("#scene-0 textarea").first().fill("未保存内容必须保留");
  await stage("media");
  await page
    .getByRole("button", { name: "AI 生成图片", exact: true })
    .waitFor();
  await stage("storyboard");
  if (
    (await page.locator("#scene-0 textarea").first().inputValue()) !==
    "未保存内容必须保留"
  )
    throw Error("Lost input");
  await page.locator(".outline-link").nth(1).click();
  await page.locator(".outline-link").nth(0).click();
  if (
    (await page.locator("#scene-0 textarea").first().inputValue()) !==
    "未保存内容必须保留"
  )
    throw Error("Lost input on scene switch");
  for (const width of [1440, 1100, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const name of ["brief", "storyboard", "media", "export", "results"]) {
      await stage(name);
      await page.screenshot({
        path: outputDir + "/studio-" + name + "-" + width + ".png",
        fullPage: true,
      });
      if (
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        )
      )
        throw Error("Overflow " + name + " " + width);
    }
  }
  // Restore saved version through reload to test route persistence and paid-request UX with mocked endpoint.
  page.once("dialog", (d) => d.accept());
  await page.reload();
  await page.locator(".studio-shell").waitFor();
  if (!page.url().endsWith("/results")) throw Error("Stage route lost");
  await stage("export");
  await page
    .getByRole("button", { name: "提交制作任务 →", exact: true })
    .click();
  if (submitted !== 1 || !page.url().endsWith("/export"))
    throw Error("Unexpected navigation after submit");
  await page.getByText("任务已提交", { exact: true }).waitFor();
  const job = {
    id: "render-fixture",
    project_id: project.id,
    kind: "render",
    status: "running",
    snapshot: { project },
    created: Date.now() / 1000,
  };
  await page.evaluate(
    (job) =>
      window.testStream.listeners.snapshot({
        data: JSON.stringify({
          jobs: [job],
          events: {
            [job.id]: [{ created: Date.now() / 1000, message: "正在渲染页面" }],
          },
        }),
      }),
    job,
  );
  await page.getByText("视频制作 · 制作中", { exact: true }).waitFor();
  if (!page.url().endsWith("/export")) throw Error("Stream changed route");
  await page.getByRole("button", { name: "日志与结果", exact: true }).click();
  await page.locator(".live-log").filter({ hasText: "正在渲染页面" }).waitFor();
  await stage("storyboard");
  await page.locator(".outline-link").nth(1).click();
  await stage("export");
  await page.getByLabel("音轨来源", { exact: true }).selectOption("edge");
  await stage("results");
  const updated = { ...project, version: 2, confirmed: false };
  await page.route("**/api/projects/studio-fixture", (r) =>
    r.fulfill({ json: updated }),
  );
  const mediaJob = {
    ...job,
    id: "media-fixture",
    kind: "image",
    status: "succeeded",
    result: {
      asset: { id: "asset-fixture", name: "模拟图片", kind: "image" },
      application: { status: "applied", version: 2, message: "结果已自动应用" },
      review: {
        scope: "仅规则检查，不验证图片语义",
        suggestions: ["检查图片与主题是否一致。"],
      },
    },
  };
  await page.evaluate(
    (job) =>
      window.testStream.listeners.snapshot({
        data: JSON.stringify({ jobs: [job], events: {} }),
      }),
    mediaJob,
  );
  await page.locator("#save-state").filter({ hasText: "v2" }).waitFor();
  if (!page.url().endsWith("/results")) throw Error("Auto apply changed stage");
  // Reconnection replays current job snapshot.
  await page.evaluate(
    (job) =>
      window.testStream.listeners.snapshot({
        data: JSON.stringify({ jobs: [job], events: {} }),
      }),
    mediaJob,
  );
  await page.getByText("检查图片与主题是否一致。", { exact: true }).waitFor();
  if (
    await page.getByRole("button", { name: "应用到本页", exact: true }).count()
  )
    throw Error("Manual confirmation still required");
  await stage("media");
  if ((await page.locator(".scene:visible").getAttribute("id")) !== "scene-1")
    throw Error("Scene reset after auto applying");
  await stage("export");
  if (
    (await page.getByLabel("音轨来源", { exact: true }).inputValue()) !== "edge"
  )
    throw Error("Export preference reset");
  await stage("storyboard");
  await page.locator("#scene-1 textarea").first().fill("保留我的未保存编辑");
  await page.evaluate(
    (job) =>
      window.testStream.listeners.snapshot({
        data: JSON.stringify({ jobs: [job], events: {} }),
      }),
    {
      ...mediaJob,
      result: {
        ...mediaJob.result,
        application: { status: "applied", version: 3, message: "已应用" },
      },
    },
  );
  await page
    .getByText(
      "服务器已有新版本，当前草稿未被覆盖。请使用「草稿恢复」对比、导出或另存为新项目。",
      { exact: true },
    )
    .waitFor();
  if (
    (await page.locator("#scene-1 textarea").first().inputValue()) !==
    "保留我的未保存编辑"
  )
    throw Error("Dirty edit overwritten");
  // Recovery must preserve the dirty source and never PUT it while making a copy.
  let copiedDraft;
  await page.route("**/api/projects", (r) => {
    if (r.request().method() === "POST") {
      copiedDraft = r.request().postDataJSON();
      return r.fulfill({
        json: {
          ...copiedDraft,
          id: "draft-copy-fixture",
          version: 1,
          confirmed: false,
        },
      });
    }
    return r.fulfill({ json: [project] });
  });
  await page.getByRole("button", { name: "对比与保留草稿" }).click();
  const recovery = page.locator(".draft-recovery-dialog");
  await recovery.getByRole("heading", { name: "服务器 · v2" }).waitFor();
  if (
    !(await recovery.locator(".draft-document").first().textContent()).includes(
      "保留我的未保存编辑",
    )
  )
    throw Error("Recovery missing local draft");
  if (
    (await recovery.locator(".draft-document").nth(1).textContent()).includes(
      "保留我的未保存编辑",
    )
  )
    throw Error("Recovery overwrote server preview");
  const downloadEvent = page.waitForEvent("download");
  await recovery.getByRole("button", { name: "导出草稿 JSON" }).click();
  const download = await downloadEvent;
  const exported = JSON.parse(fs.readFileSync(await download.path(), "utf8"));
  if (exported.document.scenes[1].narration !== "保留我的未保存编辑")
    throw Error("Export lost draft");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    if (await recovery.evaluate((n) => n.scrollWidth > n.clientWidth + 1))
      throw Error("Recovery dialog overflow");
  }
  await recovery
    .getByRole("button", { name: "另存为新项目", exact: true })
    .click();
  await recovery.getByRole("button", { name: "打开草稿副本" }).waitFor();
  if (copiedDraft.scenes[1].narration !== "保留我的未保存编辑")
    throw Error("Copy omitted unsaved input");
  await recovery.getByRole("button", { name: "关闭", exact: true }).click();
  if (
    (await page.locator("#scene-1 textarea").first().inputValue()) !==
    "保留我的未保存编辑"
  )
    throw Error("Recovery discarded source");
  // API save conflicts offer the same recovery UI, not an overwrite/retry.
  await page.route("**/api/projects/studio-fixture", (r) =>
    r.request().method() === "PUT"
      ? r.fulfill({ status: 409, json: { detail: "版本冲突" } })
      : r.fulfill({ json: updated }),
  );
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await page.locator("#draft-conflict").waitFor({ state: "visible" });
  if (
    (await page.locator("#scene-1 textarea").first().inputValue()) !==
    "保留我的未保存编辑"
  )
    throw Error("Save conflict erased input");
  // Missing source project must not prevent local export/recovery.
  await page.route("**/api/projects/studio-fixture", (r) =>
    r.fulfill({ status: 404, json: { detail: "项目不存在" } }),
  );
  await page.getByRole("button", { name: "对比与保留草稿" }).click();
  await recovery.getByRole("heading", { name: "服务器版本不可用" }).waitFor();
  if (
    !(await recovery.locator(".draft-document").textContent()).includes(
      "保留我的未保存编辑",
    )
  )
    throw Error("Deleted source lost recovery draft");
  await recovery.getByRole("button", { name: "关闭", exact: true }).click();
  // Slow saves must not erase text entered while the request is in flight.
  let releaseSave;
  let pendingDocument;
  await page.route("**/api/projects/studio-fixture", async (r) => {
    if (r.request().method() !== "PUT") return r.fulfill({ json: updated });
    pendingDocument = r.request().postDataJSON();
    await new Promise((resolve) => {
      releaseSave = resolve;
    });
    return r.fulfill({
      json: { ...project, ...pendingDocument, version: 3, confirmed: false },
    });
  });
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  for (let tries = 0; !releaseSave && tries < 100; tries++)
    await page.waitForTimeout(20);
  if (!releaseSave) throw Error("Save request did not arrive");
  await page.locator("#scene-1 textarea").first().fill("保存请求期间继续输入");
  releaseSave();
  await page
    .getByText("已保存提交时的内容；你随后输入的修改仍未保存。", {
      exact: true,
    })
    .waitFor();
  if (
    (await page.locator("#scene-1 textarea").first().inputValue()) !==
    "保存请求期间继续输入"
  )
    throw Error("Save response erased new input");
  if (!(await page.evaluate(() => state.dirty && state.project.version === 3)))
    throw Error("New input incorrectly marked saved");
  if (globalJobRequests) throw Error("Unexpected global job polling");
  if (errors.length) throw Error(errors.join(";"));
  console.log(
    JSON.stringify({
      stages: true,
      routes: true,
      draftPreserved: true,
      draftRecovery: true,
      saveWhileTyping: true,
      submissionStaysInPlace: true,
      dock: true,
      errors,
      widths: [1440, 1100, 768, 390],
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
