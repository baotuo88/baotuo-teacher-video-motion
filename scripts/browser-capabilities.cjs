// UI-only mocked providers/jobs; no credential persistence or remote generation.
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
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(baseURL);
    await page.locator("#password").fill(password);
    await page.getByRole("button", { name: "进入工作台 →" }).click();
    await page.locator("#app").waitFor({ state: "visible" });
    const configs = ["storyboard", "image", "speech"].map((capability, i) => ({
      id: String(i + 1).repeat(32),
      name: { storyboard: "讲解编导", image: "白板插画", speech: "中文配音" }[
        capability
      ],
      capability,
      base_url: "https://mock.example/v1",
      model: capability + "-model",
      enabled: true,
      has_key: true,
    }));
    const project = {
      id: "p".repeat(32),
      title: "三类能力界面验收",
      topic: "Mock project",
      style: "whiteboard",
      version: 1,
      confirmed: true,
      scenes: [
        {
          title: "逐页生成",
          narration: "这是用于界面验收的口播。",
          points: ["图片生成", "语音合成"],
          duration: 3,
          layout: "points",
        },
      ],
    };
    let saved = null,
      submitted = null;
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
    await page.route("**/api/providers", (r) =>
      r.request().method() === "GET"
        ? r.fulfill({ json: configs })
        : ((saved = r.request().postDataJSON()),
          r.fulfill({ json: configs[2] })),
    );
    await page.route("**/api/projects", (r) => r.fulfill({ json: [project] }));
    await page.route("**/api/projects/" + project.id, (r) =>
      r.fulfill({ json: project }),
    );
    await page.route(
      "**/api/projects/" + project.id + "/generate-media",
      (r) => {
        submitted = r.request().postDataJSON();
        return r.fulfill({ json: { id: "mock-job" } });
      },
    );
    await page.route("**/api/jobs", (r) => r.fulfill({ json: [] }));
    await page.locator("[data-nav=providers]").click();
    await page.getByLabel("配置名称", { exact: true }).fill("复用语音服务");
    await page.getByLabel("能力类型", { exact: true }).selectOption("speech");
    await page
      .getByLabel("复用已有连接密钥（同地址）")
      .selectOption(configs[0].id);
    await page.getByLabel("模型 ID", { exact: false }).fill("speech-model");
    await page.getByLabel("音色 ID").fill("demo-voice");
    await page.getByLabel("语速倍率").fill("1.2");
    await page.screenshot({
      path: outputDir + "/capabilities-desktop.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: outputDir + "/capabilities-mobile.png",
      fullPage: true,
    });
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw Error("Mobile overflow");
    await page
      .getByRole("button", { name: "保存服务配置", exact: true })
      .click();
    await page.getByText("服务配置已保存", { exact: false }).waitFor();
    if (
      saved.capability !== "speech" ||
      saved.voice !== "demo-voice" ||
      saved.credential_source_id !== configs[0].id
    )
      throw Error("Wrong payload");
    await page.locator("[data-nav=projects]").click();
    await page.getByText(project.title, { exact: true }).click();
    await page.locator("[data-stage-link=media]").click();
    await page
      .getByRole("button", { name: "AI 生成图片", exact: true })
      .click();
    await page.locator(".generation-dialog").waitFor();
    await page.screenshot({
      path: outputDir + "/generation-dialog-mobile.png",
    });
    await page
      .locator(".generation-dialog")
      .getByRole("button", { name: "确认并生成", exact: true })
      .click();
    await page.getByText("任务已提交", { exact: true }).waitFor();
    if (submitted.provider_id !== configs[1].id || !submitted.confirm_cost)
      throw Error("Wrong image request");
    await page.locator("[data-nav=projects]").click();
    await page.getByText(project.title, { exact: true }).click();
    await page.locator("[data-stage-link=media]").click();
    await page
      .getByRole("button", { name: "AI 合成配音", exact: true })
      .click();
    await page
      .locator(".generation-dialog")
      .getByRole("button", { name: "确认并生成", exact: true })
      .click();
    await page.getByText("任务已提交", { exact: true }).waitFor();
    if (submitted.provider_id !== configs[2].id)
      throw Error("Wrong speech request");
    if (errors.length) throw Error(errors.join(";"));
    console.log(
      JSON.stringify({
        errors,
        capabilityConfig: true,
        credentialReuse: true,
        imageAndSpeechDialogs: true,
        mobileOverflow: false,
        mocked: true,
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
