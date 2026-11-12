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
  const projects = [
    {
      id: "layout-fixture",
      title: "布局验收项目",
      topic: "不写入真实数据",
      version: 1,
      confirmed: false,
      style: "whiteboard",
      scenes: [0, 1, 2].map((i) => ({
        title: "讲解第" + (i + 1) + "页",
        narration: "这一页讲解知识。",
        points: ["第一条要点"],
        duration: 5,
        layout: "points",
      })),
    },
  ];
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
  await page.route("**/api/projects", (r) => r.fulfill({ json: projects }));
  await page.route("**/api/projects/layout-fixture", (r) =>
    r.fulfill({ json: projects[0] }),
  );
  await page.locator("[data-nav=projects]").click();
  await page.getByLabel("搜索项目", { exact: true }).fill("不存在");
  await page.getByText("没有匹配的项目", { exact: true }).waitFor();
  await page.getByLabel("搜索项目", { exact: true }).fill("布局");
  await page.screenshot({
    path: outputDir + "/workspace-projects.png",
    fullPage: true,
  });
  await page.getByText("布局验收项目", { exact: true }).click();
  await page.locator("#scene-0").waitFor();
  if ((await page.locator(".scene:visible").count()) !== 1)
    throw Error("Expected focused scene");
  await page
    .locator("#scene-0 textarea")
    .first()
    .fill("保留尚未保存的口播修改");
  await page.locator(".outline-link").nth(1).click();
  await page.locator(".outline-link").nth(0).click();
  if (
    (await page.locator("#scene-0 textarea").first().inputValue()) !==
    "保留尚未保存的口播修改"
  )
    throw Error("Unsaved input lost");
  await page.getByRole("button", { name: "查看全部", exact: true }).click();
  if ((await page.locator(".scene:visible").count()) !== 3)
    throw Error("All scenes missing");
  await page.getByRole("button", { name: "逐页编辑", exact: true }).click();
  for (const stage of ["brief", "storyboard", "media", "export", "results"]) {
    await page.locator('[data-stage-link="' + stage + '"]').click();
    if ((await page.locator(".studio-stage:not([hidden])").count()) !== 1)
      throw Error("Stage visibility");
  }
  for (const width of [1440, 1100, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.screenshot({
      path: outputDir + "/workspace-editor-" + width + ".png",
      fullPage: true,
    });
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw Error("Overflow " + width);
  }
  if (errors.length) throw Error(errors.join(";"));
  console.log(
    JSON.stringify({
      errors,
      focusedEditing: true,
      unsavedEditsPreserved: true,
      search: true,
      panels: true,
      widths: [1440, 1100, 768, 390],
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
