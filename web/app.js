"use strict";
const $ = (s) => document.querySelector(s);
const state = {
  csrf: "",
  tab: "projects",
  project: null,
  dirty: false,
  providers: [],
  assets: new Map(),
  renderOptions: {
    audio: "silent",
    voice: "zh-CN-XiaoxiaoNeural",
    provider: "",
  },
  poll: null,
};
const labels = {
  queued: "等待制作",
  running: "制作中",
  succeeded: "已完成",
  failed: "失败",
  interrupted: "已中断",
  unknown_outcome: "结果待确认",
  cancelled: "已取消",
};
const capabilities = {
  storyboard: "文本分镜",
  image: "图片生成",
  speech: "语音合成",
};
const styles = {
  whiteboard: "白板手绘",
  study: "安静书卷",
  chalkboard: "课堂黑板",
  "warm-story": "暖色故事",
  "tech-dark": "深色科技",
};
function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "value") n.value = v;
    else n.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined)
      n.append(
        typeof child === "string" ? document.createTextNode(child) : child,
      );
  }
  return n;
}
function notice(message) {
  $("#notice").hidden = !message;
  $("#notice").textContent = message || "";
}
async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.body) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  if (options.method && options.method !== "GET")
    headers["X-CSRF-Token"] = state.csrf;
  const r = await fetch("/api" + path, { ...options, headers });
  let data;
  try {
    data = await r.json();
  } catch {
    throw Error("服务响应异常");
  }
  if (!r.ok) {
    if (r.status === 401) showLogin();
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return data;
}
function safe(action) {
  return async (...args) => {
    try {
      await action(...args);
    } catch (e) {
      notice(e.message);
    }
  };
}
function button(text, action, cls = "") {
  return el(
    "button",
    { type: "button", class: cls, onclick: safe(action) },
    text,
  );
}
function badge(status) {
  return el("span", { class: "badge " + status }, labels[status] || status);
}
function select(options, value, onchange) {
  const n = el(
    "select",
    { onchange: (e) => onchange(e.target.value) },
    Object.entries(options).map(([k, v]) => el("option", { value: k }, v)),
  );
  n.value = value;
  return n;
}
function field(label, node) {
  if (!node.hasAttribute("aria-label")) node.setAttribute("aria-label", label);
  return el("label", {}, label, node);
}
function empty(title, text) {
  return el("div", { class: "empty" }, el("h3", {}, title), el("p", {}, text));
}
function showLogin() {
  clearInterval(state.poll);
  $("#login").hidden = false;
  $("#app").hidden = true;
}
async function enter() {
  const d = await api("/auth/session");
  state.csrf = d.csrf;
  $("#login").hidden = true;
  $("#app").hidden = false;
  await navigate("projects");
  state.poll = setInterval(() => {
    if (state.tab === "jobs" && !document.hidden)
      loadJobs(false).catch(() => {});
  }, 3000);
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/auth/login", {
      method: "POST",
      body: { password: $("#password").value },
    });
    $("#password").value = "";
    $("#login-error").textContent = "";
    await enter();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});
$("#logout").onclick = safe(async () => {
  await api("/auth/logout", { method: "POST" });
  showLogin();
});
document
  .querySelectorAll("[data-nav]")
  .forEach((n) => (n.onclick = safe(() => navigate(n.dataset.nav))));
function canLeave() {
  return !state.dirty || confirm("有未保存修改，确定离开吗？");
}
async function navigate(tab) {
  if (!canLeave()) return;
  state.dirty = false;
  state.tab = tab;
  state.project = null;
  notice("");
  document
    .querySelectorAll("[data-nav]")
    .forEach((n) => n.classList.toggle("active", n.dataset.nav === tab));
  const titles = {
    projects: "我的视频项目",
    jobs: "制作任务",
    assets: "素材库",
    providers: "模型服务",
    runtimes: "Skill 运行时",
    system: "运行状态",
  };
  $("#heading").textContent = titles[tab];
  $("#crumb").textContent = "工作空间 / " + titles[tab];
  $("#new-project").hidden = tab !== "projects";
  $("#content").replaceChildren();
  await {
    projects: loadProjects,
    jobs: loadJobs,
    assets: loadAssets,
    providers: loadProviders,
    runtimes: loadRuntimes,
    system: loadSystem,
  }[tab]();
}
$("#new-project").onclick = () => $("#create-dialog").showModal();
$("#close-create").onclick = () => $("#create-dialog").close();
$("#create-form").onsubmit = safe(async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const p = await api("/projects", {
    method: "POST",
    body: { title: f.get("title"), topic: f.get("topic"), scenes: [] },
  });
  $("#create-dialog").close();
  e.target.reset();
  await openProject(p.id);
});
async function loadProjects() {
  const items = await api("/projects");
  const grid = el("div", { class: "grid" });
  for (const p of items) {
    grid.append(
      el(
        "article",
        {
          class: "card",
          onclick: safe(() => openProject(p.id)),
          tabindex: 0,
          onkeydown: safe((e) => {
            if (e.key === "Enter") return openProject(p.id);
          }),
        },
        el(
          "div",
          { class: "thumbnail" },
          el("strong", {}, p.title),
          el(
            "small",
            {},
            "WHITEBOARD / " +
              String(p.scenes.length).padStart(2, "0") +
              " SCENES",
          ),
        ),
        el(
          "div",
          { class: "card-body" },
          el("p", {}, p.topic || "让一个想法变得清晰，从第一份分镜开始。"),
          el(
            "div",
            { class: "meta" },
            el(
              "span",
              {},
              new Date(p.updated * 1000).toLocaleDateString() +
                " · v" +
                p.version,
            ),
            el(
              "span",
              { class: "badge " + (p.confirmed ? "confirmed" : "") },
              p.confirmed ? "分镜已确认" : "草稿",
            ),
          ),
        ),
      ),
    );
  }
  $("#content").replaceChildren(
    el(
      "section",
      { class: "hero" },
      el(
        "div",
        {},
        el("h2", {}, "把复杂的事，讲得简单一些。"),
        el(
          "p",
          {},
          "编写分镜、选择画面、交给后台制作。每一次创作都有独立版本，每一次更新都可追溯。",
        ),
      ),
      el("div", { class: "sketch" }, "✎"),
    ),
    el("p", { class: "section-label" }, "全部项目 · " + items.length),
    items.length
      ? grid
      : empty(
          "第一段讲解，从这里开始",
          "点击右上角「新建视频」，或先在模型服务中配置分镜模型。",
        ),
  );
}
async function openProject(id) {
  if (!canLeave()) return;
  state.project = await api("/projects/" + id);
  state.dirty = false;
  state.tab = "editor";
  state.providers = await api("/providers");
  state.renderOptions = {
    audio: "silent",
    voice: "zh-CN-XiaoxiaoNeural",
    provider: "",
  };
  await hydrateAssets();
  renderEditor();
}
function change(fn) {
  fn();
  state.dirty = true;
  const n = $("#save-state");
  if (n) n.textContent = "有未保存修改";
}
function input(value, changeFn, max) {
  return el("input", {
    value,
    maxlength: max || 600,
    oninput: (e) => change(() => changeFn(e.target.value)),
  });
}
function area(value, changeFn, rows = 3, max = 600) {
  return el(
    "textarea",
    {
      rows,
      maxlength: max,
      oninput: (e) => change(() => changeFn(e.target.value)),
    },
    value,
  );
}
async function saveProject() {
  const p = state.project;
  const updated = await api("/projects/" + p.id, {
    method: "PUT",
    body: {
      version: p.version,
      title: p.title,
      topic: p.topic,
      style: p.style,
      scenes: p.scenes,
    },
  });
  state.project = updated;
  state.dirty = false;
  renderEditor();
  notice("已保存 v" + updated.version + "；如需制作，请确认分镜。");
}
function renderEditor() {
  const p = state.project;
  $("#heading").textContent = p.title;
  $("#crumb").textContent = "视频项目 / 分镜编辑";
  $("#new-project").hidden = true;
  document
    .querySelectorAll("[data-nav]")
    .forEach((n) => n.classList.toggle("active", n.dataset.nav === "projects"));
  const scenes = el("div", { class: "scene-list" });
  const outline = el(
    "div",
    { class: "scene-outline" },
    el("span", { class: "muted" }, p.scenes.length + " 页分镜"),
  );
  p.scenes.forEach((s, i) => {
    outline.append(
      button(
        String(i + 1).padStart(2, "0") + " " + s.title,
        () =>
          $("#scene-" + i).scrollIntoView({
            behavior: "smooth",
            block: "start",
          }),
        "outline-link",
      ),
    );
    const card = el(
      "section",
      { class: "scene", id: "scene-" + i },
      el(
        "div",
        { class: "scene-heading" },
        el("span", { class: "scene-number" }, String(i + 1).padStart(2, "0")),
        input(s.title, (v) => (s.title = v), 50),
        el(
          "div",
          { class: "scene-controls" },
          button("↑", () => {
            if (i) {
              change(
                () =>
                  ([p.scenes[i - 1], p.scenes[i]] = [
                    p.scenes[i],
                    p.scenes[i - 1],
                  ]),
              );
              renderEditor();
            }
          }),
          button("↓", () => {
            if (i < p.scenes.length - 1) {
              change(
                () =>
                  ([p.scenes[i + 1], p.scenes[i]] = [
                    p.scenes[i],
                    p.scenes[i + 1],
                  ]),
              );
              renderEditor();
            }
          }),
          button(
            "删除",
            () => {
              if (!confirm("删除这一页分镜？保存后生效。")) return;
              change(() => p.scenes.splice(i, 1));
              renderEditor();
            },
            "quiet danger",
          ),
        ),
      ),
      field(
        "口播内容",
        area(s.narration, (v) => (s.narration = v), 3),
      ),
      field(
        "画面要点 · 每行一条，最多 4 条",
        area(
          s.points.join("\n"),
          (v) => (s.points = v.split("\n").filter(Boolean)),
          3,
          403,
        ),
      ),
      el(
        "div",
        { class: "row" },
        field(
          "画面布局",
          select(
            { points: "逐条讲解", process: "步骤流程", compare: "对比卡片" },
            s.layout,
            (v) => change(() => (s.layout = v)),
          ),
        ),
        field(
          "静音预览时长 / 秒",
          el("input", {
            type: "number",
            min: 2,
            max: 60,
            value: s.duration,
            oninput: (e) => change(() => (s.duration = Number(e.target.value))),
          }),
        ),
      ),
      el(
        "div",
        { class: "scene-media" },
        sceneAsset(s, "image"),
        sceneAsset(s, "audio"),
      ),
      s.image_id
        ? el(
            "p",
            { class: "note" },
            "已绑定图片：本页使用「左侧要点 + 右侧图片」。移除图片后恢复所选布局。",
          )
        : null,
    );
    scenes.append(card);
  });
  if (!p.scenes.length)
    scenes.append(
      empty(
        "先写下故事的第一幕",
        "添加一页分镜，或展开右侧「AI 分镜」生成初稿。",
      ),
    );
  scenes.append(
    button(
      "＋ 添加一页分镜",
      () => {
        if (p.scenes.length >= 30) throw Error("最多30页");
        change(() =>
          p.scenes.push({
            title: "新的讲解",
            narration: "在这里写下这一页的口播。",
            points: ["画面要点"],
            layout: "points",
            duration: 5,
            image_id: null,
            audio_id: null,
          }),
        );
        renderEditor();
      },
      "wide add-scene",
    ),
  );
  const provider = select(
    Object.fromEntries(
      state.providers
        .filter(
          (x) => x.enabled && (x.capability || "storyboard") === "storyboard",
        )
        .map((x) => [x.id, x.name + " / " + x.model]),
    ),
    state.renderOptions.provider ||
      state.providers.find(
        (x) => x.enabled && (x.capability || "storyboard") === "storyboard",
      )?.id,
    (v) => (state.renderOptions.provider = v),
  );
  const audio = select(
    {
      silent: "静音预览 · 无需联网",
      uploaded: "上传配音 · 逐页 WAV",
      edge: "Edge 在线配音",
    },
    state.renderOptions.audio,
    (v) => {
      state.renderOptions.audio = v;
      voiceWrap.hidden = v !== "edge";
      audioNote.textContent = audioHelp(v);
    },
  );
  const voice = select(
    {
      "zh-CN-XiaoxiaoNeural": "晓晓 · 中文女声",
      "zh-CN-YunxiNeural": "云希 · 中文男声",
      "en-US-JennyNeural": "Jenny · English",
    },
    state.renderOptions.voice,
    (v) => (state.renderOptions.voice = v),
  );
  const voiceWrap = field("在线配音音色", voice);
  voiceWrap.hidden = audio.value !== "edge";
  function audioHelp(value) {
    return value === "uploaded"
      ? "每一页都需绑定 WAV 素材，视频时长按真实音频计算。"
      : value === "edge"
        ? "需要联网；服务可用性受外部服务影响。"
        : "无真实语音。先验证画面，不产生 API 费用。";
  }
  const audioNote = el("p", { class: "note" }, audioHelp(audio.value));
  const settings = el(
    "details",
    { class: "settings-group", open: "" },
    el("summary", {}, "项目设置"),
    field(
      "项目名称",
      input(p.title, (v) => (p.title = v), 60),
    ),
    field(
      "视觉风格",
      select(styles, p.style, (v) => change(() => (p.style = v))),
    ),
    field(
      "创作要求",
      area(p.topic, (v) => (p.topic = v), 3, 5000),
    ),
  );
  const ai = el(
    "details",
    { class: "settings-group" },
    el("summary", {}, "AI 分镜"),
    field("模型服务", provider),
    button(
      "生成分镜",
      async () => {
        if (state.dirty) throw Error("请先保存修改");
        if (!provider.value) throw Error("请先配置模型服务");
        if (!confirm("将调用外部模型，可能产生费用，是否继续？")) return;
        await api("/projects/" + p.id + "/storyboard", {
          method: "POST",
          body: {
            version: p.version,
            provider_id: provider.value,
            idempotency_key: crypto.randomUUID(),
            confirm_cost: true,
          },
        });
        await navigate("jobs");
      },
      "wide",
    ),
    el(
      "p",
      { class: "note" },
      "生成结果先审阅再应用，不会自动覆盖正在编辑的内容。",
    ),
  );
  const exportGroup = el(
    "section",
    { class: "export-group" },
    el(
      "div",
      { class: "panel-title" },
      el("h3", {}, "预览与导出"),
      el("span", { class: "badge" }, "1920 × 1080"),
    ),
    field("音轨来源", audio),
    voiceWrap,
    audioNote,
    button(
      "提交制作任务 →",
      async () => {
        if (state.dirty) throw Error("请先保存修改");
        if (!p.confirmed) throw Error("请先确认当前分镜");
        if (audio.value === "uploaded" && p.scenes.some((s) => !s.audio_id))
          throw Error("请为每一页绑定 WAV 配音");
        if (audio.value === "edge" && !confirm("Edge 配音需要联网，是否继续？"))
          return;
        await api("/projects/" + p.id + "/render", {
          method: "POST",
          body: {
            version: p.version,
            audio: audio.value,
            voice: voice.value,
            fps: 24,
            idempotency_key: crypto.randomUUID(),
          },
        });
        await navigate("jobs");
      },
      "primary wide",
    ),
  );
  const side = el(
    "div",
    { class: "editor-side" },
    el("div", { class: "settings-stack" }, settings, ai, exportGroup),
  );
  const save = button("保存修改", saveProject);
  const confirmButton = button(
    "确认分镜",
    async () => {
      if (state.dirty) throw Error("请先保存修改");
      state.project = await api("/projects/" + p.id + "/confirm", {
        method: "POST",
        body: { version: p.version },
      });
      renderEditor();
      notice("分镜已确认，可以提交制作任务。");
    },
    "primary",
  );
  const history = async () => {
    if (state.dirty) throw Error("请先保存修改");
    const rows = await api("/projects/" + p.id + "/revisions");
    const dialog = el(
      "dialog",
      { class: "history-dialog" },
      el("h2", {}, "项目历史版本"),
      el("p", { class: "muted" }, "恢复会创建新的草稿，不改变旧任务或成片。"),
    );
    const close = () => {
      dialog.close();
      dialog.remove();
    };
    for (const r of rows)
      dialog.append(
        el(
          "div",
          { class: "history-row" },
          el(
            "div",
            {},
            el("strong", {}, "v" + r.version + " · " + r.document.title),
            el("p", { class: "muted" }, r.document.scenes.length + " 页分镜"),
          ),
          button("恢复", async () => {
            if (!confirm("恢复为新草稿版本？")) return;
            state.project = await api("/projects/" + p.id + "/restore", {
              method: "POST",
              body: { version: p.version, target_version: r.version },
            });
            await hydrateAssets();
            close();
            renderEditor();
          }),
        ),
      );
    dialog.append(button("关闭", close));
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    document.body.append(dialog);
    dialog.showModal();
  };
  $("#content").replaceChildren(
    el(
      "div",
      { class: "editor-toolbar" },
      el(
        "div",
        { class: "actions" },
        button("← 项目", () => navigate("projects"), "quiet"),
        button("历史版本", history),
        button("复制", async () => {
          if (state.dirty) throw Error("请先保存");
          const copy = await api("/projects/" + p.id + "/duplicate", {
            method: "POST",
          });
          await openProject(copy.id);
        }),
      ),
      el(
        "div",
        { class: "actions" },
        el(
          "small",
          { id: "save-state" },
          state.dirty
            ? "有未保存修改"
            : "v" + p.version + " · " + (p.confirmed ? "分镜已确认" : "待确认"),
        ),
        save,
        confirmButton,
      ),
    ),
    outline,
    el("div", { class: "editor-grid" }, scenes, side),
  );
}
async function hydrateAssets() {
  const ids = [
    ...new Set(
      state.project.scenes
        .flatMap((s) => [s.image_id, s.audio_id])
        .filter(Boolean),
    ),
  ];
  await Promise.all(
    ids.map(async (id) => {
      try {
        state.assets.set(id, await api("/assets/" + id));
      } catch {
        state.assets.delete(id);
      }
    }),
  );
}

function assetUrl(asset, thumbnail = false) {
  return "/api/assets/" + asset.id + (thumbnail ? "/thumbnail" : "/content");
}
function mediaPreview(asset) {
  return asset.kind === "image"
    ? el("img", {
        src: assetUrl(asset, true),
        alt: asset.name,
        loading: "lazy",
      })
    : el(
        "div",
        { class: "audio-preview" },
        el("span", {}, "♫"),
        el("small", {}, asset.duration.toFixed(1) + " 秒 · WAV"),
      );
}
async function uploadFile(file, kind) {
  if (!file || !file.size || file.size > 20 * 1024 * 1024)
    throw Error("请选择不超过 20MB 的文件");
  const response = await fetch(
    "/api/assets?" + new URLSearchParams({ name: file.name, kind }),
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": state.csrf,
        "Content-Type": "application/octet-stream",
      },
      body: file,
    },
  );
  const data = await response.json();
  if (!response.ok)
    throw Error(typeof data.detail === "string" ? data.detail : "上传失败");
  state.assets.set(data.id, data);
  return data;
}
function uploader(onDone, fixedKind = null, report = notice) {
  const kind = select(
    { image: "图片 · PNG / JPEG / WebP", audio: "配音 · 16-bit PCM WAV" },
    fixedKind || "image",
    () => update(),
  );
  if (fixedKind) kind.disabled = true;
  const file = el("input", { type: "file", "aria-label": "选择上传文件" });
  const message = el(
    "p",
    { class: "muted upload-status", "aria-live": "polite" },
    "单个文件最多 20MB；不会调用外部 API。",
  );
  const submit = button(
    "上传素材",
    async () => {
      submit.disabled = true;
      file.disabled = true;
      kind.disabled = true;
      message.textContent = "正在上传并检查素材…";
      try {
        const asset = await uploadFile(file.files[0], kind.value);
        message.textContent = "上传成功";
        file.value = "";
        await onDone(asset);
      } catch (error) {
        message.textContent = error.message;
        report(error.message);
      } finally {
        submit.disabled = false;
        file.disabled = false;
        kind.disabled = !!fixedKind;
      }
    },
    "primary",
  );
  function update() {
    file.accept = kind.value === "image" ? ".png,.jpg,.jpeg,.webp" : ".wav";
    file.value = "";
  }
  update();
  return el(
    "section",
    { class: "upload-panel" },
    el(
      "div",
      {},
      el("h3", {}, "上传自己的素材"),
      el(
        "p",
        { class: "muted" },
        "图片会规范化为 PNG；WAV 保留实际时长，供逐页配音使用。",
      ),
    ),
    el("div", { class: "upload-controls" }, kind, file, submit),
    message,
  );
}
async function loadAssets() {
  const items = await api("/assets");
  items.forEach((a) => state.assets.set(a.id, a));
  const search = el("input", {
    type: "search",
    placeholder: "搜索素材名称",
    "aria-label": "搜索素材",
  });
  const filter = select(
    { all: "全部素材", image: "图片", audio: "配音" },
    "all",
    () => draw(),
  );
  const grid = el("div", { class: "asset-grid" });
  const count = el("small", { class: "muted" });
  function draw() {
    const shown = items.filter(
      (a) =>
        (filter.value === "all" || a.kind === filter.value) &&
        a.name.toLowerCase().includes(search.value.toLowerCase()),
    );
    count.textContent = shown.length + " 个素材";
    grid.replaceChildren();
    for (const a of shown) {
      const preview = mediaPreview(a);
      const card = el(
        "article",
        { class: "asset-card" },
        preview,
        el(
          "div",
          { class: "asset-info" },
          el("h3", { title: a.name }, a.name),
          el(
            "p",
            { class: "muted" },
            a.kind === "image"
              ? a.width +
                  " × " +
                  a.height +
                  " · " +
                  (a.bytes / 1024).toFixed(0) +
                  " KB"
              : a.duration.toFixed(1) + " 秒 · " + a.sample_rate + " Hz",
          ),
        ),
      );
      if (a.kind === "audio")
        card.append(
          el("audio", {
            controls: "",
            preload: "none",
            src: assetUrl(a),
            "aria-label": a.name,
          }),
        );
      card.append(
        el(
          "div",
          { class: "asset-actions" },
          el(
            "a",
            { href: assetUrl(a), target: "_blank", rel: "noopener" },
            "查看原文件 ↗",
          ),
          button(
            "归档",
            async () => {
              if (
                !confirm("从素材库隐藏？历史项目和任务仍可使用，不删除文件。")
              )
                return;
              await api("/assets/" + a.id, { method: "DELETE" });
              await loadAssets();
            },
            "quiet danger",
          ),
        ),
      );
      grid.append(card);
    }
    if (!shown.length)
      grid.append(
        empty(
          "没有符合条件的素材",
          "上传图片或 WAV 配音，再到分镜页面选择素材。",
        ),
      );
  }
  search.oninput = draw;
  $("#content").replaceChildren(
    uploader(async () => {
      await loadAssets();
      notice("素材已上传，可在分镜中选择。");
    }),
    el("div", { class: "library-toolbar" }, search, filter, count),
    grid,
    el(
      "p",
      { class: "note" },
      "归档只隐藏素材，不会破坏旧版本。当前不开放 SVG/GIF 上传；图片上限 1600 万像素，配音上限 120 秒。",
    ),
  );
  draw();
}
async function pickAsset(kind, onPick) {
  const dialog = el("dialog", {
    class: "asset-dialog",
    "aria-label": kind === "image" ? "选择画面图片" : "选择本页配音",
  });
  const error = el("p", { class: "dialog-error", "aria-live": "polite" });
  const search = el("input", {
    type: "search",
    placeholder: "搜索名称",
    "aria-label": "搜索可选素材",
  });
  const grid = el("div", { class: "asset-picker-grid" });
  let items = [];
  function close() {
    dialog.close();
    dialog.remove();
  }
  function draw() {
    grid.replaceChildren();
    for (const a of items.filter((a) =>
      a.name.toLowerCase().includes(search.value.toLowerCase()),
    )) {
      const card = el(
        "article",
        { class: "asset-card" },
        mediaPreview(a),
        el("div", { class: "asset-info" }, el("h3", { title: a.name }, a.name)),
      );
      if (kind === "audio")
        card.append(
          el("audio", { controls: "", preload: "none", src: assetUrl(a) }),
        );
      card.append(
        button(
          "使用此素材",
          () => {
            onPick(a);
            close();
          },
          "wide",
        ),
      );
      grid.append(card);
    }
    if (!grid.childElementCount)
      grid.append(
        empty("还没有可选素材", "可在上方直接上传，无需离开编辑器。"),
      );
  }
  async function refresh() {
    items = await api("/assets?kind=" + kind);
    items.forEach((a) => state.assets.set(a.id, a));
    draw();
  }
  search.oninput = draw;
  dialog.append(
    el(
      "div",
      { class: "dialog-heading" },
      el(
        "div",
        {},
        el("p", { class: "eyebrow" }, "MEDIA LIBRARY"),
        el("h2", {}, kind === "image" ? "选择画面图片" : "选择本页配音"),
      ),
      button("关闭", close),
    ),
    error,
    uploader(
      async (a) => {
        await refresh();
        error.textContent = "上传完成，点击「使用此素材」即可绑定。";
      },
      kind,
      (msg) => (error.textContent = msg),
    ),
    search,
    grid,
  );
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
  try {
    await refresh();
  } catch (e) {
    error.textContent = e.message;
  }
}
function sceneAsset(scene, kind) {
  const field = kind === "image" ? "image_id" : "audio_id";
  const a = state.assets.get(scene[field]);
  const title = kind === "image" ? "画面图片" : "本页配音";
  const box = el(
    "div",
    { class: "scene-asset " + kind },
    el(
      "div",
      { class: "panel-title" },
      el("strong", {}, title),
      scene[field]
        ? el("span", { class: "badge confirmed" }, "已绑定")
        : el("small", { class: "muted" }, "可选"),
    ),
  );
  if (a) {
    if (kind === "image")
      box.append(el("img", { src: assetUrl(a, true), alt: a.name }));
    else
      box.append(
        el("audio", { controls: "", preload: "none", src: assetUrl(a) }),
      );
    box.append(
      el(
        "small",
        { class: "asset-name", title: a.name },
        a.name + (a.archived ? " · 已归档" : ""),
      ),
    );
  } else
    box.append(
      el(
        "p",
        { class: "muted" },
        scene[field]
          ? "素材不可用，请重新选择"
          : kind === "image"
            ? "图片右侧展示，要点保留在左侧。"
            : "上传录制好的 WAV，导出时选择「逐页配音」。",
      ),
    );
  box.append(
    el(
      "div",
      { class: "actions" },
      button(a ? "更换素材" : "选择素材", () =>
        pickAsset(kind, (a) => {
          change(() => (scene[field] = a.id));
          renderEditor();
        }),
      ),
      scene[field]
        ? button(
            "移除",
            () => {
              change(() => (scene[field] = null));
              renderEditor();
            },
            "quiet",
          )
        : null,
    ),
  );
  box.append(
    button(
      kind === "image" ? "AI 生成图片" : "AI 合成配音",
      () => mediaDialog(scene, kind),
      "wide media-generate",
    ),
  );
  return box;
}

async function mediaDialog(scene, kind) {
  if (state.dirty) throw Error("请先保存修改");
  if (!state.project.confirmed) throw Error("请先确认当前分镜");
  const capability = kind === "image" ? "image" : "speech";
  const configs = state.providers.filter(
    (p) => p.enabled && p.capability === capability,
  );
  if (!configs.length)
    throw Error(
      "请先在模型服务中添加启用的" + capabilities[capability] + "配置",
    );
  const project = state.project;
  const index = project.scenes.indexOf(scene);
  const selection = select(
    Object.fromEntries(configs.map((p) => [p.id, p.name + " / " + p.model])),
    configs[0].id,
    () => {},
  );
  const prompt = el("textarea", {
    rows: 4,
    maxlength: 4000,
    placeholder: "可选：留空根据本页标题、要点和口播生成提示词",
  });
  const error = el("p", { class: "dialog-error", "aria-live": "polite" });
  const close = () => {
    dialog.close();
    dialog.remove();
  };
  const submit = button(
    "确认并生成",
    async () => {
      submit.disabled = true;
      try {
        await api("/projects/" + project.id + "/generate-media", {
          method: "POST",
          body: {
            version: project.version,
            provider_id: selection.value,
            scene_index: index,
            prompt: kind === "image" ? prompt.value : "",
            confirm_cost: true,
            idempotency_key: crypto.randomUUID(),
          },
        });
        close();
        await navigate("jobs");
      } catch (e) {
        error.textContent = e.message;
      } finally {
        submit.disabled = false;
      }
    },
    "primary",
  );
  const dialog = el(
    "dialog",
    { class: "generation-dialog" },
    el("h2", {}, capabilities[capability] + " · 第" + (index + 1) + "页"),
    el("p", { class: "muted" }, scene.title),
    field("服务与模型", selection),
    kind === "image"
      ? field("图片生成说明", prompt)
      : el("div", { class: "note" }, "将合成当前口播：" + scene.narration),
    el(
      "p",
      { class: "note" },
      "本次会调用外部服务，可能产生费用。结果先保存到素材库，不自动覆盖当前页面。",
    ),
    error,
    el("div", { class: "actions" }, button("取消", close), submit),
  );
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
}

let lastJobs = "";
async function loadJobs(force = true) {
  const items = await api("/jobs");
  const signature = JSON.stringify(items);
  if (!force && signature === lastJobs) return;
  lastJobs = signature;
  const list = el("div");
  for (const j of items) {
    const p = j.snapshot.project;
    const card = el(
      "section",
      { class: "job" },
      el(
        "div",
        { class: "job-head" },
        el(
          "h3",
          {},
          p.title +
            " · " +
            ({
              render: "视频制作",
              storyboard: "AI 分镜",
              image: "AI 图片",
              speech: "AI 配音",
            }[j.kind] || j.kind),
        ),
        badge(j.status),
      ),
      el(
        "p",
        {},
        "版本 v" +
          p.version +
          " · " +
          new Date(j.created * 1000).toLocaleString() +
          " · " +
          (j.runtime_id || ""),
      ),
      j.error ? el("p", { class: "danger" }, j.error) : null,
    );
    const actions = el(
      "div",
      { class: "actions" },
      button("打开项目", () => openProject(j.project_id)),
      button("查看日志", async () => {
        const events = await api("/jobs/" + j.id + "/events");
        let log = card.querySelector("pre");
        if (!log) {
          log = el("pre");
          card.append(log);
        }
        log.textContent =
          events
            .map(
              (e) =>
                new Date(e.created * 1000).toLocaleTimeString() +
                " " +
                e.message,
            )
            .join("\n") || "任务等待 Worker 领取";
      }),
    );
    if (["queued", "running"].includes(j.status))
      actions.append(
        button(
          j.cancel_requested ? "正在取消…" : "取消任务",
          async () => {
            await api("/jobs/" + j.id + "/cancel", { method: "POST" });
            await loadJobs();
          },
          "danger",
        ),
      );
    if (
      ["failed", "interrupted", "cancelled", "unknown_outcome"].includes(
        j.status,
      )
    )
      actions.append(
        button("重试", async () => {
          if (!confirm("请先确认供应商账单。重新执行可能产生费用，确定继续？"))
            return;
          await api("/jobs/" + j.id + "/retry", {
            method: "POST",
            body: { confirm_cost: true, idempotency_key: crypto.randomUUID() },
          });
          await loadJobs();
        }),
      );
    if (j.kind === "storyboard" && j.status === "succeeded") {
      actions.append(
        button("查看生成分镜", () => {
          let view = card.querySelector("pre");
          if (!view) {
            view = el("pre");
            card.append(view);
          }
          view.textContent = j.result.scenes
            .map(
              (s, i) =>
                `${i + 1}. ${s.title}\n${s.narration}\n画面：${s.points.join(" / ")}`,
            )
            .join("\n\n");
        }),
        button(
          "应用到项目",
          async () => {
            if (!confirm("将替换该版本的分镜；已被修改的项目会拒绝应用。"))
              return;
            await api("/jobs/" + j.id + "/apply", {
              method: "POST",
              body: { version: p.version },
            });
            await openProject(j.project_id);
          },
          "primary",
        ),
      );
    }
    if (
      ["image", "speech"].includes(j.kind) &&
      j.status === "succeeded" &&
      j.result?.asset
    ) {
      const a = j.result.asset;
      card.append(
        el(
          "div",
          { class: "generated-preview" },
          j.kind === "image"
            ? el("img", { src: assetUrl(a), alt: a.name, loading: "lazy" })
            : el("audio", {
                controls: "",
                preload: "metadata",
                src: assetUrl(a),
              }),
        ),
      );
      actions.append(
        button(
          "应用到本页",
          async () => {
            if (!confirm("将替换本页选中的素材并产生新草稿版本，是否继续？"))
              return;
            await api("/jobs/" + j.id + "/apply", {
              method: "POST",
              body: { version: p.version },
            });
            await openProject(j.project_id);
          },
          "primary",
        ),
      );
      card.append(
        el(
          "p",
          { class: "note" },
          "结果已保存到素材库。项目若已修改，可在编辑器手动选用；旧素材不会被删除。",
        ),
      );
    }
    card.append(actions);
    if (j.result?.artifacts) {
      const links = el("div", { class: "downloads" });
      for (const a of j.result.artifacts) {
        const url =
          "/api/jobs/" + j.id + "/artifacts/" + encodeURIComponent(a.name);
        links.append(el("a", { href: url, download: a.name }, a.name + " ↗"));
        if (a.kind === "video" && a.name.includes("有字幕"))
          card.append(
            el("video", {
              controls: "",
              preload: "metadata",
              src: url,
              poster: "/api/jobs/" + j.id + "/artifacts/preview.png",
            }),
          );
      }
      card.append(links);
    }
    list.append(card);
  }
  $("#content").replaceChildren(
    el(
      "p",
      { class: "note" },
      "任务由独立 Worker 执行，关闭网页不会停止。失败或中断不会自动重试外部付费请求。",
    ),
    items.length
      ? list
      : empty("还没有制作任务", "先打开一个项目，确认分镜后提交制作。"),
  );
}
async function loadProviders(edit = null) {
  const items = await api("/providers");
  const form = el("form", { class: "panel provider-form" });
  const name = el("input", {
    required: "",
    maxlength: 60,
    value: edit?.name || "",
    placeholder: "例如：我的分镜服务",
  });
  const url = el("input", {
    required: "",
    type: "url",
    value: edit?.base_url || "",
    placeholder: "https://your-provider.example/v1",
  });
  const key = el("input", {
    type: "password",
    autocomplete: "new-password",
    placeholder: edit ? "留空使用已保存的 Key" : "填写此服务的 API Key",
  });
  const model = el("input", {
    required: "",
    maxlength: 100,
    value: edit?.model || "",
    placeholder: "从下方列表选择，或手动填写模型 ID",
  });
  const capability = select(
    capabilities,
    edit?.capability || "storyboard",
    () => updateCapability(),
  );
  const source = select(
    {
      "": "不复用 / 手动填写 Key",
      ...Object.fromEntries(
        items.filter((p) => p.id !== edit?.id).map((p) => [p.id, p.name]),
      ),
    },
    "",
    (id) => {
      const p = items.find((p) => p.id === id);
      if (p) url.value = p.base_url;
      invalidate();
    },
  );
  const imageSize = select(
    {
      auto: "服务默认（不发送尺寸）",
      "1024x1024": "1024 × 1024",
      "1536x1024": "1536 × 1024",
      "1024x1536": "1024 × 1536",
      "1792x1024": "1792 × 1024",
      "1024x1792": "1024 × 1792",
    },
    edit?.image_size || "auto",
    () => {},
  );
  const speechVoice = el("input", {
    value: edit?.voice || "alloy",
    maxlength: 100,
    placeholder: "供应商音色 ID",
  });
  const speechSpeed = el("input", {
    type: "number",
    min: 0.25,
    max: 4,
    step: 0.05,
    value: edit?.speed || 1,
  });
  const imageOptions = el(
    "div",
    { class: "capability-options" },
    field("图片尺寸 · 依供应商支持", imageSize),
  );
  const speechOptions = el(
    "div",
    { class: "capability-options" },
    field("音色 ID", speechVoice),
    field("语速倍率", speechSpeed),
  );
  function updateCapability() {
    imageOptions.hidden = capability.value !== "image";
    speechOptions.hidden = capability.value !== "speech";
  }
  updateCapability();
  const enabled = select(
    { true: "启用", false: "禁用" },
    String(edit?.enabled ?? true),
    () => {},
  );
  const search = el("input", {
    type: "search",
    placeholder: "搜索模型 ID…",
    "aria-label": "搜索模型列表",
  });
  const results = el("div", {
    class: "model-results",
    "aria-label": "可用模型",
  });
  const status = el(
    "p",
    { class: "model-status", "aria-live": "polite" },
    "填写地址和 Key 后获取列表；不需要先保存配置。",
  );
  const picker = el(
    "section",
    { class: "model-picker", hidden: "" },
    search,
    results,
  );
  let ids = [],
    sequence = 0,
    busy = false;
  function renderResults() {
    const matches = ids.filter((id) =>
      id.toLowerCase().includes(search.value.toLowerCase()),
    );
    results.replaceChildren();
    for (const id of matches.slice(0, 200)) {
      const choice = button(
        id,
        () => {
          model.value = id;
          renderResults();
        },
        "model-option" + (model.value === id ? " selected" : ""),
      );
      choice.setAttribute("aria-pressed", String(model.value === id));
      choice.title = id;
      results.append(choice);
    }
    if (!matches.length)
      results.append(
        el("p", { class: "muted" }, "没有匹配的模型，可以手动填写。"),
      );
    if (matches.length > 200)
      results.append(
        el("p", { class: "muted" }, "仅显示前 200 项，请输入关键词缩小范围。"),
      );
  }
  function invalidate() {
    sequence++;
    ids = [];
    picker.hidden = true;
    status.textContent = "连接配置已变化，请重新获取模型列表。";
  }
  url.addEventListener("input", invalidate);
  key.addEventListener("input", invalidate);
  search.oninput = renderResults;
  model.addEventListener("input", renderResults);
  const fetchModels = button("获取模型列表", async () => {
    if (busy) return;
    if (!url.value.trim()) {
      status.textContent = "请先填写 Base URL。";
      url.focus();
      return;
    }
    if (!key.value && !edit && !source.value) {
      status.textContent = "请先填写 API Key。";
      key.focus();
      return;
    }
    const requestId = ++sequence;
    busy = true;
    fetchModels.disabled = true;
    fetchModels.textContent = "正在获取…";
    picker.hidden = true;
    status.textContent = "正在由后端读取 /models，不发送生成请求…";
    try {
      const data = await api("/providers/models/discover", {
        method: "POST",
        body: {
          base_url: url.value.trim(),
          api_key: key.value || null,
          provider_id: edit?.id || source.value || null,
        },
      });
      if (requestId !== sequence || !form.isConnected) return;
      ids = data.models.map((m) => m.id);
      search.value = "";
      picker.hidden = false;
      renderResults();
      status.textContent = ids.length
        ? `已获取 ${ids.length} 个模型。点击选择，不会自动覆盖已选模型。${data.skipped ? " 已过滤无效条目。" : ""}`
        : "服务返回空列表，可直接手动填写模型 ID。";
    } catch (error) {
      if (requestId === sequence && form.isConnected) {
        status.textContent = error.message + "；手动填写仍可保存。";
      }
    } finally {
      busy = false;
      fetchModels.disabled = false;
      fetchModels.textContent = "重新获取模型";
    }
  });
  form.append(
    el("p", { class: "eyebrow" }, "PROVIDER CONNECTION"),
    el("h2", {}, edit ? "编辑模型服务" : "添加模型服务"),
    field("配置名称", name),
    field("能力类型", capability),
    !edit ? field("复用已有连接密钥（同地址）", source) : null,
    field("Base URL · 包含 API 前缀，例如 /v1", url),
    field("API Key · 加密保存，不回显", key),
    el(
      "div",
      { class: "model-fetch-row" },
      fetchModels,
      el(
        "small",
        { class: "muted" },
        edit ? "可使用已保存的 Key" : "无需先保存",
      ),
    ),
    status,
    picker,
    field("模型 ID · 支持手动填写", model),
    imageOptions,
    speechOptions,
    el(
      "p",
      { class: "note" },
      "请按所选能力选择模型。文本使用聊天协议、图片使用 images/generations、语音使用 audio/speech；模型列表成功不代表生成权限已验证。",
    ),
    field("状态", enabled),
    el(
      "div",
      { class: "actions" },
      el("button", { type: "submit", class: "primary" }, "保存服务配置"),
      edit ? button("取消编辑", () => loadProviders()) : null,
    ),
  );
  form.onsubmit = safe(async (e) => {
    e.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      await api("/providers" + (edit ? "/" + edit.id : ""), {
        method: edit ? "PUT" : "POST",
        body: {
          name: name.value,
          capability: capability.value,
          image_size: imageSize.value,
          voice: speechVoice.value,
          speed: Number(speechSpeed.value),
          credential_source_id: source.value || null,
          base_url: url.value,
          model: model.value,
          api_key: key.value || null,
          enabled: enabled.value === "true",
        },
      });
      sequence++;
      key.value = "";
      await loadProviders();
      notice("服务配置已保存，未发送生成测试请求。");
    } finally {
      submit.disabled = false;
    }
  });
  const list = el(
    "div",
    { class: "provider-list" },
    el(
      "div",
      { class: "panel-title" },
      el("h3", {}, "已保存的服务"),
      el("small", { class: "muted" }, items.length + " 个配置"),
    ),
  );
  for (const p of items)
    list.append(
      el(
        "section",
        { class: "panel provider-card" },
        el(
          "div",
          { class: "panel-title" },
          el("h3", {}, p.name),
          el(
            "span",
            { class: "badge " + (p.enabled ? "confirmed" : "") },
            p.enabled ? "已启用" : "已禁用",
          ),
        ),
        el("p", { class: "provider-model" }, p.model),
        el("code", {}, p.base_url),
        el(
          "p",
          { class: "note" },
          "密钥：" +
            (p.has_key ? "已加密保存" : "未设置") +
            " · 能力：" +
            capabilities[p.capability || "storyboard"],
        ),
        button("编辑 / 获取模型", async () => {
          await loadProviders(p);
          $(".provider-form").scrollIntoView({
            block: "start",
            behavior: "smooth",
          });
        }),
      ),
    );
  if (!items.length)
    list.append(empty("尚未配置服务", "填写左侧连接信息，获取模型并保存。"));
  list.append(
    el(
      "section",
      { class: "panel provider-help" },
      el("h3", {}, "连接说明"),
      el(
        "p",
        {},
        "支持兼容聊天协议的公网 HTTPS 服务。基地址后自动追加 /models 获取列表。",
      ),
      el(
        "p",
        {},
        "服务未开放列表、Key 无权限或网络异常时，可手动填写模型。不会静默更换地址、跟随重定向或自动重试。",
      ),
      el(
        "p",
        {},
        "修改已保存的服务地址时，需要重新输入 Key，防止旧密钥被发送到其他服务。",
      ),
    ),
  );
  $("#content").replaceChildren(
    el(
      "p",
      { class: "note" },
      "支持文本、图片、语音三类兼容协议，可复用同地址密钥。图片和语音从确认后的分镜中逐页生成；私网服务和任意供应商协议暂不支持。",
    ),
    el(
      "div",
      { class: "capability-overview" },
      Object.entries(capabilities).map(([id, label]) =>
        el(
          "div",
          { class: "panel" },
          el("h3", {}, label),
          el(
            "p",
            { class: "muted" },
            items.filter(
              (p) => p.enabled && (p.capability || "storyboard") === id,
            ).length + " 个启用配置",
          ),
        ),
      ),
    ),
    el("div", { class: "provider-layout" }, form, list),
  );
}

async function loadRuntimes() {
  const d = await api("/runtimes");
  const list = el("div");
  for (const r of d.items) {
    const card = el(
      "section",
      { class: "panel" },
      el(
        "div",
        { class: "panel-title" },
        el("h3", {}, r.id),
        el(
          "span",
          {
            class:
              "badge " + (d.active?.runtime_id === r.id ? "confirmed" : ""),
          },
          d.active?.runtime_id === r.id ? "当前默认" : "候选 / 历史",
        ),
      ),
      el(
        "pre",
        {},
        "Skill  " +
          r.skill_commit +
          "\nEngine " +
          r.engine_commit +
          "\n静态检查：" +
          (r.inspection.static_ok ? "通过" : "失败") +
          " / 样片验证记录：" +
          (r.verified ? "存在" : "未验证"),
      ),
      el(
        "div",
        { class: "actions" },
        button("查看 Skill 文档", async () => {
          const doc = await api("/runtimes/" + r.id + "/documents");
          const view = el("pre", {}, doc.skill);
          card.append(view);
        }),
        button(
          "激活 / 回滚至此版本",
          async () => {
            if (!r.verified) throw Error("先通过 CLI 完成真实样片验证");
            if (!confirm("仅影响以后提交的任务，确认切换？")) return;
            await api("/runtimes/activate", {
              method: "POST",
              body: { runtime_id: r.id, confirm: true },
            });
            await loadRuntimes();
          },
          "primary",
        ),
      ),
    );
    list.append(card);
  }
  $("#content").replaceChildren(
    el(
      "section",
      { class: "hero" },
      el(
        "div",
        {},
        el("h2", {}, "更新有据，创作无忧。"),
        el(
          "p",
          {},
          "Skill 和引擎独立锁定版本。每个任务保存自己的运行时，不被后续升级覆盖。",
        ),
      ),
    ),
    el(
      "p",
      { class: "note" },
      "下载和验证候选版本目前由管理员通过 CLI 执行，不会在网页自动执行未知上游代码。上游新增功能仍需适配器和界面支持。",
    ),
    d.items.length
      ? list
      : empty(
          "还没有运行时",
          "参照 README 的 stage → verify → activate 步骤准备首个版本。",
        ),
  );
}
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
enter().catch(() => showLogin());

async function loadSystem() {
  const status = await api("/system/status");
  const names = {
    database: ["数据库", "检查数据卷权限、数据库版本及完整性。"],
    worker: ["后台 Worker", "启动独立 Worker；检查容器日志和健康状态。"],
    disk: ["磁盘空间", "扩容或先备份后清理；不要直接删除素材或数据库。"],
    admin_password: ["管理员密码", "设置至少 16 位的随机密码。"],
    encryption_key: [
      "API 密钥加密",
      "设置有效 Fernet 密钥；已有数据不要随意更换密钥。",
    ],
    runtime: [
      "渲染运行时",
      "准备、真实渲染验证并激活指定版本的 Skill 运行时。",
    ],
  };
  $("#content").replaceChildren(
    el(
      "section",
      { class: "panel" },
      el(
        "div",
        { class: "panel-title" },
        el("h3", {}, status.ready ? "基础环境已就绪" : "上线检查尚未通过"),
        button("重新检查", loadSystem),
      ),
      el(
        "p",
        { class: "muted" },
        "磁盘可用 " +
          (status.free_disk_mb / 1024).toFixed(1) +
          " GB · 单机 / 单管理员 / 单 Worker",
      ),
      el(
        "p",
        { class: "note" },
        "此检查不调用付费模型，也不代表真实供应商、域名 HTTPS 或备份恢复已验收。",
      ),
    ),
    el(
      "div",
      { class: "capability-overview" },
      Object.entries(status.checks).map(([key, ok]) =>
        el(
          "section",
          { class: "panel" },
          el("h3", {}, names[key]?.[0] || key),
          badge(ok ? "succeeded" : "failed"),
          el(
            "p",
            { class: "muted" },
            ok ? "检查通过" : names[key]?.[1] || "请检查配置",
          ),
        ),
      ),
    ),
  );
}
