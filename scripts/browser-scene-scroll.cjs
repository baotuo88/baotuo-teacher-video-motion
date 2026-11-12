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

  const project = {
    id: "scroll-fixture",
    title: "横条滚动回归",
    topic: "",
    version: 1,
    confirmed: true,
    style: "whiteboard",
    scenes: Array.from({ length: 20 }, (_, i) => ({
      title: "这是第" + (i + 1) + "页的讲解分镜",
      narration: "测试口播",
      points: ["要点"],
      duration: 3,
      layout: "points",
    })),
  };
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
  await page.route("**/api/projects/scroll-fixture", (r) =>
    r.fulfill({ json: project }),
  );
  await page.route("**/api/projects/scroll-fixture/events", (r) =>
    r.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'event: snapshot\ndata: {"jobs":[],"events":{}}\n\n',
    }),
  );
  await page.locator("[data-nav=projects]").click();
  await page.getByText(project.title, { exact: true }).click();
  await page.locator(".scene-outline").waitFor();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const stage of ["storyboard", "media"]) {
      await page.locator("[data-stage-link=" + stage + "]").click();
      const target = page.locator(".outline-link").nth(15);
      await target.scrollIntoViewIfNeeded();
      const before = await page
        .locator(".scene-outline")
        .evaluate((n) => n.scrollLeft);
      await target.click();
      const after = await page
        .locator(".scene-outline")
        .evaluate((n) => n.scrollLeft);
      if (before < 1 || Math.abs(after - before) > 2)
        throw Error(
          "Horizontal position reset: " +
            JSON.stringify({ width, stage, before, after }),
        );
      if (
        (await page.locator(".scene:visible").getAttribute("id")) !== "scene-15"
      )
        throw Error("Wrong active scene");
      const visible = await page
        .locator(".outline-link")
        .nth(15)
        .evaluate((n) => {
          const a = n.getBoundingClientRect(),
            b = n.parentElement.getBoundingClientRect();
          return a.left >= b.left - 1 && a.right <= b.right + 1;
        });
      if (!visible) throw Error("Selected tab is offscreen");
      await page.getByRole("button", { name: "查看全部", exact: true }).click();
      await page.getByRole("button", { name: "逐页编辑", exact: true }).click();
      if (
        (await page.locator(".scene-outline").evaluate((n) => n.scrollLeft)) < 1
      )
        throw Error("Rerender lost scroll");
    }
  }
  if (errors.length) throw Error(errors.join(";"));
  console.log(
    JSON.stringify({
      scrollPreserved: true,
      selectedVisible: true,
      stages: ["storyboard", "media"],
      widths: [1440, 390],
      errors,
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
