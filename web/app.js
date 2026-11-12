"use strict";
const $ = (s) => document.querySelector(s);
const state = {
  csrf: "",
  tab: "projects",
  project: null,
  dirty: false,
  draftConflict: null,
  activeScene: 0,
  sceneScroll: 0,
  allScenes: false,
  stage: "storyboard",
  liveJobs: [],
  historySession: null,
  liveEvents: {},
  providers: [],
  assets: new Map(),
  settingsSession: null,
  renderOptions: {
    audio: "silent",
    voice: "zh-CN-XiaoxiaoNeural",
    provider: "",
  },
  projectStream: null,
  projectJobSignature: "",
  syncingProject: false,
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
    throw Object.assign(
      Error(
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail),
      ),
      { status: r.status },
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
  const node = el("button", { type: "button", class: cls }, text);
  node.addEventListener(
    "click",
    safe(async (event) => {
      if (node.disabled) return;
      node.disabled = true;
      try {
        await action(event);
      } finally {
        node.disabled = false;
      }
    }),
  );
  return node;
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
function stopProjectStream() {
  state.projectStream?.close();
  state.projectStream = null;
}
function showLogin() {
  stopProjectStream();
  $("#login").hidden = false;
  $("#app").hidden = true;
}
async function enter() {
  const d = await api("/auth/session");
  state.csrf = d.csrf;
  $("#login").hidden = true;
  $("#app").hidden = false;
  await restoreRoute();
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
  if (!canLeave()) {
    syncCurrentRoute();
    return;
  }
  if (state.settingsSession) await state.settingsSession.pending;
  stopProjectStream();
  state.dirty = false;
  state.tab = tab;
  document.body.dataset.view = tab;
  state.project = null;
  history.replaceState(null, "", "#/" + tab);
  notice("");
  document
    .querySelectorAll("[data-nav]")
    .forEach((n) => n.classList.toggle("active", n.dataset.nav === tab));
  const titles = {
    projects: "我的视频项目",
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
          "data-project-title": (p.title + " " + p.topic).toLowerCase(),
          "data-confirmed": String(p.confirmed),
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
  const search = el("input", {
    type: "search",
    placeholder: "搜索项目名称或讲解要求",
    "aria-label": "搜索项目",
  });
  const count = el("span", { class: "muted", "aria-live": "polite" });
  const filter = select(
    { all: "全部项目", draft: "仅看草稿", confirmed: "已确认分镜" },
    "all",
    applyFilter,
  );
  filter.setAttribute("aria-label", "项目状态筛选");
  function applyFilter() {
    let visible = 0;
    for (const card of grid.children) {
      const matches =
        card.dataset.projectTitle.includes(search.value.trim().toLowerCase()) &&
        (filter.value === "all" ||
          card.dataset.confirmed === String(filter.value === "confirmed"));
      card.hidden = !matches;
      if (matches) visible++;
    }
    count.textContent = visible + " / " + items.length + " 个项目";
    noMatch.hidden = visible > 0 || !items.length;
  }
  const noMatch = empty(
    "没有匹配的项目",
    "试试其他关键词，或切换项目状态筛选。",
  );
  search.addEventListener("input", applyFilter);
  $("#content").replaceChildren(
    el(
      "section",
      { class: "workspace-intro" },
      el(
        "div",
        {},
        el("p", { class: "eyebrow" }, "创作工作台"),
        el("h2", {}, "从想法，到一段讲解视频"),
        el(
          "p",
          { class: "muted" },
          "选择项目继续编辑，或新建项目，用 AI 起草第一份分镜。",
        ),
      ),
      el(
        "div",
        { class: "workspace-stats" },
        el("strong", {}, String(items.length)),
        el("span", {}, "视频项目"),
      ),
    ),
    el(
      "div",
      { class: "project-tools" },
      search,
      filter,
      count,
      button("回收站", showProjectTrash),
    ),
    items.length
      ? grid
      : empty("还没有视频项目", "点击右上角「新建视频」开始创作。"),
    noMatch,
  );
  applyFilter();
}
async function showProjectTrash() {
  const dialog = el(
    "dialog",
    { class: "project-trash-dialog" },
    el("h2", {}, "项目回收站"),
    el(
      "p",
      { class: "note" },
      "恢复后重新显示在项目列表，分镜历史、制作配置和任务结果入口保留。这里不会删除素材或成片，也不会重新执行任务。",
    ),
    el(
      "p",
      { class: "note" },
      "仅支持本次功能启用后移入的项目；此前已永久删除的项目不能自动恢复。",
    ),
  );
  const list = el("div", { class: "trash-list" });
  const status = el("p", { class: "note", "aria-live": "polite" });
  let changed = false;
  async function refresh() {
    status.textContent = "正在读取回收站…";
    try {
      const items = await api("/project-trash");
      if (!dialog.isConnected) return;
      list.replaceChildren(
        ...items.map((project) =>
          el(
            "article",
            { class: "trash-project" },
            el(
              "div",
              {},
              el("h3", {}, project.title),
              el(
                "p",
                { class: "muted" },
                project.scenes.length +
                  " 页 · v" +
                  project.version +
                  " · 移入时间 " +
                  new Date(project.deleted_at * 1000).toLocaleString(),
              ),
            ),
            button("恢复项目", async () => {
              try {
                await api("/project-trash/" + project.id + "/restore", {
                  method: "POST",
                  body: { version: project.version },
                });
                changed = true;
                await refresh();
                status.textContent =
                  "已恢复「" +
                  project.title +
                  "」，关闭回收站即可在项目列表继续编辑。";
              } catch (error) {
                status.textContent =
                  "恢复未完成：" +
                  error.message +
                  "。请刷新回收站核对，未覆盖现有项目。";
              }
            }),
          ),
        ),
      );
      if (!items.length)
        list.append(empty("回收站为空", "移入回收站的项目会显示在这里。"));
      status.textContent =
        "共 " + items.length + " 个项目；当前不提供彻底删除。";
    } catch (error) {
      status.textContent = "读取失败：" + error.message + "，可点击刷新重试。";
    }
  }
  dialog.append(
    status,
    list,
    el(
      "div",
      { class: "actions" },
      button("刷新回收站", refresh),
      button("关闭", () => dialog.close()),
    ),
  );
  dialog.addEventListener(
    "close",
    () => {
      dialog.remove();
      if (changed && state.tab === "projects")
        loadProjects().catch((error) => notice(error.message));
    },
    { once: true },
  );
  document.body.append(dialog);
  dialog.showModal();
  await refresh();
}
async function openProject(id, stage = null) {
  if (!canLeave()) {
    syncCurrentRoute();
    return;
  }
  if (state.settingsSession) await state.settingsSession.pending;
  stopProjectStream();
  const sameProject = state.project?.id === id;
  state.project = await api("/projects/" + id);
  state.draftConflict = null;
  state.dirty = false;
  state.tab = "editor";
  document.body.dataset.view = "editor";
  if (!sameProject) {
    state.activeScene = 0;
    state.sceneScroll = 0;
  }
  state.allScenes = false;
  state.stage = stage || (state.project.scenes.length ? "storyboard" : "brief");
  state.liveJobs = [];
  state.historySession = {
    pid: id,
    jobs: new Map(),
    cursor: undefined,
    loading: false,
  };
  state.liveEvents = {};
  state.providers = await api("/providers");
  const settings = await api("/projects/" + id + "/production-settings");
  state.renderOptions = settings;
  state.settingsSession = {
    id,
    saved: { ...settings },
    pending: Promise.resolve(),
    error: null,
    saving: 0,
  };
  await hydrateAssets();
  renderEditor();
}
// A separate settings revision avoids invalidating in-flight content generation.
function saveProductionSetting(key, value) {
  const session = state.settingsSession;
  state.renderOptions[key] = value;
  session.saving++;
  updateProductionSettingsStatus();
  session.pending = session.pending.then(async () => {
    try {
      if (session.error) throw session.error;
      session.saved = await api(
        "/projects/" + session.id + "/production-settings",
        {
          method: "PUT",
          body: { ...session.saved, [key]: value },
        },
      );
      session.error = null;
    } catch (error) {
      session.error = error;
      if (state.settingsSession === session) {
        notice(
          "制作设置未保存：" + error.message + "。请重新打开项目核对设置。",
        );
      }
    } finally {
      session.saving--;
      if (state.settingsSession === session) updateProductionSettingsStatus();
    }
  });
}
function productionSettingsMessage() {
  const session = state.settingsSession;
  return session?.error
    ? "制作设置保存失败，请重新打开项目核对"
    : session?.saving
      ? "正在保存制作设置…"
      : "制作设置已保存 · 本项目自动记忆";
}
function updateProductionSettingsStatus() {
  document.querySelectorAll(".production-settings-state").forEach((node) => {
    node.textContent = productionSettingsMessage();
  });
}
async function requireSavedProductionSettings() {
  const session = state.settingsSession;
  await session.pending;
  if (session.error)
    throw Error("制作设置未保存，请重新打开项目核对后再提交。");
}
window.addEventListener("beforeunload", (event) => {
  // Draft protection already handled elsewhere; settings saves are normally very short.
  if (state.settingsSession?.error || state.settingsSession?.saving) {
    event.preventDefault();
    event.returnValue = "";
  }
});
function change(fn) {
  fn();
  state.dirty = true;
  const n = $("#save-state");
  if (n) n.textContent = "有未保存修改";
  const readiness = $(".export-summary .note");
  if (readiness)
    readiness.textContent = "有未保存修改，请先保存并重新确认分镜。";
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
function projectDocument(project) {
  return structuredClone(
    Object.fromEntries(
      ["title", "topic", "style", "scenes"].map((key) => [key, project[key]]),
    ),
  );
}
function markDraftConflict(pid) {
  if (state.project?.id !== pid) return;
  state.draftConflict = pid;
  const banner = $("#draft-conflict");
  if (banner) banner.hidden = false;
  notice(
    "服务器已有新版本，当前草稿未被覆盖。请使用「草稿恢复」对比、导出或另存为新项目。",
  );
}
function downloadDraft(project, draft) {
  const url = URL.createObjectURL(
    new Blob(
      [
        JSON.stringify(
          {
            format: "baotuo-project-draft-v1",
            source_project_id: project.id,
            source_version: project.version,
            exported_at: new Date().toISOString(),
            document: draft,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    ),
  );
  const link = el("a", {
    href: url,
    download: "project-draft-" + project.id + "-v" + project.version + ".json",
  });
  documentBodyDownload(link);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function documentBodyDownload(link) {
  document.body.append(link);
  link.click();
  link.remove();
}
async function showDraftRecovery() {
  const project = state.project;
  const draft = projectDocument(project);
  const dialog = el(
    "dialog",
    { class: "draft-recovery-dialog" },
    el("h2", {}, "草稿恢复与版本对比"),
    el(
      "p",
      { class: "note" },
      "左侧是打开此窗口时的草稿快照。不会自动合并或覆盖服务器版本；素材仅保留引用，JSON 不包含素材文件。",
    ),
  );
  const close = () => {
    dialog.close();
    dialog.remove();
  };
  const remote = el(
    "section",
    {},
    el("h3", {}, "服务器版本"),
    el("p", {}, "正在读取…"),
  );
  const columns = el(
    "div",
    { class: "draft-compare" },
    el(
      "section",
      {},
      el("h3", {}, "本地草稿 · 基于 v" + project.version),
      el("pre", { class: "draft-document" }, JSON.stringify(draft, null, 2)),
    ),
    remote,
  );
  const result = el("p", { class: "note", "aria-live": "polite" });
  const saveAs = button("另存为新项目", async () => {
    // Stay on the source draft; no navigation or mutation of the original project.
    let copy;
    try {
      copy = await api("/projects", {
        method: "POST",
        body: { ...draft, title: draft.title.slice(0, 50) + " · 草稿副本" },
      });
    } catch (error) {
      result.textContent =
        "另存未完成：" +
        error.message +
        "。草稿仍保留，可先导出；网络失败时请先检查项目列表，避免重复创建。";
      return;
    }
    result.replaceChildren(
      el("span", {}, "草稿已保存为独立项目，不改变原项目。"),
      button("打开草稿副本", async () => {
        close();
        await openProject(copy.id);
      }),
    );
    saveAs.hidden = true;
  });
  dialog.append(
    columns,
    result,
    el(
      "div",
      { class: "actions" },
      button("导出草稿 JSON", () => downloadDraft(project, draft)),
      saveAs,
      button("关闭", close),
    ),
  );
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
  try {
    const latest = await api("/projects/" + project.id);
    if (!dialog.isConnected) return;
    const server = projectDocument(latest);
    remote.replaceChildren(
      el("h3", {}, "服务器 · v" + latest.version),
      el(
        "p",
        { class: "note" },
        JSON.stringify(draft) === JSON.stringify(server)
          ? "内容相同"
          : "内容有差异，请逐项核对；不会自动合并。",
      ),
      el("pre", { class: "draft-document" }, JSON.stringify(server, null, 2)),
    );
  } catch (error) {
    remote.replaceChildren(
      el("h3", {}, "服务器版本不可用"),
      el(
        "p",
        { class: "danger" },
        error.message + "。仍可导出本地草稿，或尝试另存项目。",
      ),
    );
  }
}
async function saveProject() {
  const p = state.project;
  const document = projectDocument(p);
  let updated;
  try {
    updated = await api("/projects/" + p.id, {
      method: "PUT",
      body: { version: p.version, ...document },
    });
  } catch (error) {
    if ([404, 409].includes(error.status)) {
      markDraftConflict(p.id);
      return;
    }
    throw error;
  }
  if (state.project !== p) return;
  state.draftConflict = null;
  if ($("#draft-conflict")) $("#draft-conflict").hidden = true;
  if (
    JSON.stringify(projectDocument(state.project)) !== JSON.stringify(document)
  ) {
    // The user kept typing during the save; only advance the base, never erase input.
    state.project.version = updated.version;
    state.project.confirmed = false;
    notice("已保存提交时的内容；你随后输入的修改仍未保存。");
    return;
  }
  state.project = updated;
  state.dirty = false;
  state.draftConflict = null;
  renderEditor();
  notice("已保存 v" + updated.version + "；如需制作，请确认分镜。");
}
function renderEditor() {
  const previousOutline = $(".scene-outline");
  if (
    previousOutline?.clientWidth &&
    previousOutline.dataset.projectId === state.project.id
  )
    state.sceneScroll = previousOutline.scrollLeft;
  const p = state.project;
  state.activeScene = Math.max(
    0,
    Math.min(state.activeScene, p.scenes.length - 1),
  );
  $("#heading").textContent = p.title;
  $("#crumb").textContent = "视频项目 / 分镜编辑";
  $("#new-project").hidden = true;
  document
    .querySelectorAll("[data-nav]")
    .forEach((n) => n.classList.toggle("active", n.dataset.nav === "projects"));
  const scenes = el("div", { class: "scene-list" });
  const outline = el(
    "div",
    {
      class: "scene-outline",
      "data-project-id": p.id,
      onscroll: (e) => {
        state.sceneScroll = e.currentTarget.scrollLeft;
      },
    },
    el("span", { class: "muted" }, p.scenes.length + " 页分镜"),
  );
  p.scenes.forEach((s, i) => {
    outline.append(
      button(
        String(i + 1).padStart(2, "0") + " " + s.title,
        () => {
          state.activeScene = i;
          if (state.allScenes)
            $("#scene-" + i).scrollIntoView({
              behavior: "smooth",
              block: "start",
            });
          for (const card of scenes.querySelectorAll(".scene"))
            card.hidden = !state.allScenes && card.id !== "scene-" + i;
          for (const [index, tab] of [
            ...outline.querySelectorAll(".outline-link"),
          ].entries()) {
            tab.classList.toggle("selected", index === i);
            tab.setAttribute("aria-pressed", String(index === i));
          }
        },
        "outline-link" + (i === state.activeScene ? " selected" : ""),
      ),
    );
    const card = el(
      "section",
      { class: "scene", id: "scene-" + i },
      el(
        "div",
        { class: "scene-heading" },
        el("span", { class: "scene-number" }, String(i + 1).padStart(2, "0")),
        input(
          s.title,
          (v) => {
            s.title = v;
            outline.children[i + 1].textContent =
              String(i + 1).padStart(2, "0") + " " + v;
          },
          50,
        ),
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
              state.activeScene = i - 1;
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
              state.activeScene = i + 1;
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
    card.hidden = !state.allScenes && i !== state.activeScene;
    scenes.append(card);
  });
  if (!p.scenes.length)
    scenes.append(
      empty("先写下故事的第一幕", "添加一页分镜，或切换「AI 分镜」生成初稿。"),
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
        state.activeScene = p.scenes.length - 1;
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
    (v) => saveProductionSetting("provider", v),
  );
  if (state.renderOptions.provider && !provider.value) {
    provider.prepend(
      el("option", { value: "" }, "已保存的服务不可用，请重新选择"),
    );
    provider.value = "";
  }
  const audio = select(
    {
      silent: "静音预览 · 无需联网",
      uploaded: "上传配音 · 逐页 WAV",
      edge: "Edge 在线配音",
    },
    state.renderOptions.audio,
    (v) => {
      saveProductionSetting("audio", v);
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
    (v) => saveProductionSetting("voice", v),
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
    { class: "settings-group", open: "" },
    el("summary", {}, "AI 分镜"),
    field("模型服务", provider),
    el(
      "p",
      { class: "note production-settings-state", "aria-live": "polite" },
      productionSettingsMessage(),
    ),
    button(
      "生成分镜",
      async () => {
        if (state.dirty) throw Error("请先保存修改");
        await requireSavedProductionSettings();
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
        await announceSubmission();
      },
      "wide",
    ),
    el(
      "p",
      { class: "note" },
      "生成成功后自动应用为新草稿，并给出检查建议；版本冲突时保留结果，不覆盖新稿。",
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
    el(
      "p",
      { class: "note production-settings-state", "aria-live": "polite" },
      productionSettingsMessage(),
    ),
    button(
      "提交制作任务 →",
      async () => {
        if (state.dirty) throw Error("请先保存修改");
        await requireSavedProductionSettings();
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
        await announceSubmission();
      },
      "primary wide",
    ),
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

        button("历史版本", history),
        button("草稿恢复", showDraftRecovery),
        button(
          "删除项目",
          async () => {
            if (
              !confirm(
                "将「" +
                  p.title +
                  "」移入回收站？项目、编辑历史、制作配置和成片会保留，可在项目列表的回收站恢复。有活动任务时不能移入。" +
                  (state.dirty
                    ? "当前未保存修改不会进入回收站，请先通过草稿恢复导出或另存。"
                    : ""),
              )
            )
              return;
            await api("/projects/" + p.id, {
              method: "DELETE",
              body: { version: p.version, confirm: true },
            });
            state.dirty = false;
            await navigate("projects");
            notice("项目已移入回收站，可从项目列表恢复；历史和成片已保留。");
          },
          "quiet danger",
        ),

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
    el(
      "div",
      { class: "workflow-strip" },
      el("span", { class: !p.scenes.length ? "current" : "" }, "01 编写分镜"),
      el(
        "span",
        { class: p.scenes.length && !p.confirmed ? "current" : "" },
        "02 保存与确认",
      ),
      el("span", { class: p.confirmed ? "current" : "" }, "03 配音与导出"),
    ),
    el(
      "div",
      { class: "scene-switcher" },
      outline,
      button(state.allScenes ? "逐页编辑" : "查看全部", () => {
        state.allScenes = !state.allScenes;
        renderEditor();
      }),
    ),
    el("div", { class: "editor-grid" }, scenes),
    el(
      "section",
      { id: "project-tasks", class: "project-tasks" },
      el(
        "div",
        { class: "panel-title" },
        el("h2", {}, "项目制作任务"),
        el(
          "small",
          { id: "stream-state", "aria-live": "polite" },
          "连接实时日志…",
        ),
      ),
      el(
        "p",
        { class: "muted" },
        "生成进度、阶段日志与成片都留在项目中。日志实时更新，不代表模型逐字输出。",
      ),
      el("div", { id: "project-job-list" }),
      el(
        "div",
        { class: "task-history-tools" },
        el(
          "p",
          { id: "task-history-status", class: "note", "aria-live": "polite" },
          "实时显示最近任务，历史记录可继续加载。",
        ),
        button("加载更早任务", loadOlderProjectJobs, "history-more"),
      ),
    ),
  );
  mountStudio(p, scenes, outline, settings, ai, exportGroup);
  if (state.historySession?.pid === p.id) {
    renderJobs(mergedProjectJobs(), $("#project-job-list"));
    updateHistoryControls();
  }
  startProjectStream(p.id);
}
async function hydrateAssets(project = state.project) {
  const ids = [
    ...new Set(
      project.scenes.flatMap((s) => [s.image_id, s.audio_id]).filter(Boolean),
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
        await announceSubmission();
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
      "本次会调用外部服务，可能产生费用。结果会安全应用到对应页面；分镜内容或目标素材被修改时只保留结果，不覆盖新稿。",
    ),
    error,
    el("div", { class: "actions" }, button("取消", close), submit),
  );
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  document.body.append(dialog);
  dialog.showModal();
}

function mergedProjectJobs() {
  const session = state.historySession;
  if (!session) return state.liveJobs;
  return [...session.jobs.values()].sort(
    (a, b) => b.created - a.created || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0),
  );
}
function updateHistoryControls() {
  const session = state.historySession;
  if (!session) return;
  const more = $(".history-more");
  if (more) {
    more.disabled = session.loading || session.cursor === null;
    more.hidden = session.cursor === null;
    more.textContent = session.loading
      ? "正在加载…"
      : session.cursor === null
        ? "已加载全部历史"
        : "加载更早任务";
  }
  const status = $("#task-history-status");
  if (status)
    status.textContent =
      "已加载 " +
      session.jobs.size +
      " 条任务。" +
      (session.cursor === null ? "已加载全部历史。" : "") +
      "实时区域仅展示最近日志；完整记录可按任务查看或下载。";
}
async function loadOlderProjectJobs() {
  const session = state.historySession;
  if (!session || session.loading || session.cursor === null) return;
  session.loading = true;
  updateHistoryControls();
  try {
    const before = session.cursor
      ? "&before=" + encodeURIComponent(session.cursor)
      : "";
    const page = await api(
      "/projects/" + session.pid + "/job-history?limit=50" + before,
    );
    if (
      state.historySession !== session ||
      state.project?.id !== session.pid ||
      state.tab !== "editor"
    )
      return;
    for (const job of page.items) {
      const current = session.jobs.get(job.id);
      if (!current || job.updated > current.updated)
        session.jobs.set(job.id, job);
    }
    session.cursor = page.next_cursor;
    renderJobs(mergedProjectJobs(), $("#project-job-list"));
  } finally {
    session.loading = false;
    if (state.historySession === session) updateHistoryControls();
  }
}
function formatJobEvents(events) {
  return events
    .map(
      (e) => new Date(e.created * 1000).toLocaleTimeString() + " " + e.message,
    )
    .join("\n");
}
async function showJobLogPage(jid, card) {
  let panel = card.querySelector(".manual-log-panel");
  if (panel) {
    panel.hidden = !panel.hidden;
    return;
  }
  const log = el("pre", {
    class: "manual-log",
    "aria-label": "任务完整日志（分页）",
  });
  const status = el("p", { class: "note", "aria-live": "polite" });
  let after = 0;
  let count = 0;
  const more = button("加载后续日志", async () => {
    try {
      const events = await api("/jobs/" + jid + "/events?after=" + after);
      const top = log.scrollTop;
      if (events.length) {
        log.append(
          document.createTextNode(
            (count ? "\n" : "") + formatJobEvents(events),
          ),
        );
        after = events[events.length - 1].id;
        count += events.length;
      }
      log.scrollTop = top;
      status.textContent =
        "已读取 " +
        count +
        " 条日志。" +
        (events.length === 200
          ? "还有后续日志可继续加载。"
          : "已到当前末尾；运行中任务可稍后刷新。 ");
      more.textContent =
        events.length === 200 ? "加载后续日志" : "刷新后续日志";
    } catch (error) {
      status.textContent =
        "日志读取失败：" + error.message + "；可重试，不会重新执行任务。";
    }
  });
  panel = el(
    "section",
    { class: "manual-log-panel" },
    el(
      "p",
      { class: "note" },
      "按时间正序，每次读取最多200条。下载包含请求开始时的全部日志（UTC时间）。",
    ),
    log,
    status,
    more,
  );
  card.append(panel);
  more.click();
}
function renderJobs(items, target) {
  let list = target.querySelector(".job-list");
  if (!list) {
    list = el("div", { class: "job-list" });
    target.replaceChildren(
      el(
        "p",
        { class: "note" },
        "任务由独立 Worker 执行，关闭网页不会停止。失败或中断不会自动重试外部付费请求。",
      ),
      list,
    );
  }
  const existing = new Map(
    [...list.children].map((node) => [node.dataset.jobId, node]),
  );
  const ids = new Set(items.map((job) => job.id));
  for (const node of [...list.children]) {
    if (!ids.has(node.dataset.jobId)) node.remove();
  }
  let previous = null;
  function place(card) {
    const next = previous ? previous.nextSibling : list.firstChild;
    // Never detach an unchanged player: even re-appending can reset playback.
    if (next !== card) list.insertBefore(card, next);
    previous = card;
  }
  for (const j of items) {
    const signature = JSON.stringify(j);
    const old = existing.get(j.id);
    if (old?.jobSignature === signature) {
      place(old);
      continue;
    }
    const p = j.snapshot.project;
    const card = el(
      "section",
      { class: "job", "data-job-id": j.id },
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
      button("查看日志", () => showJobLogPage(j.id, card)),
      el(
        "a",
        {
          href: "/api/jobs/" + j.id + "/logs.txt",
          download: "job-" + j.id + "-logs.txt",
        },
        "下载完整日志",
      ),
    );
    if (["queued", "running"].includes(j.status))
      actions.append(
        button(
          j.cancel_requested ? "正在取消…" : "取消任务",
          async () => {
            await api("/jobs/" + j.id + "/cancel", { method: "POST" });
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
        }),
      );
    if (j.kind === "storyboard" && j.status === "succeeded") {
      actions.append(
        button("查看生成分镜", () => {
          let view = card.querySelector(".storyboard-result");
          if (!view) {
            view = el("pre", { class: "storyboard-result" });
            card.append(view);
          }
          view.textContent = j.result.scenes
            .map(
              (s, i) =>
                `${i + 1}. ${s.title}\n${s.narration}\n画面：${s.points.join(" / ")}`,
            )
            .join("\n\n");
        }),
        j.result?.application
          ? el("span", { hidden: "" })
          : button(
              "应用到项目",
              async () => {
                if (!confirm("将替换该版本的分镜；已被修改的项目会拒绝应用。"))
                  return;
                if (state.dirty)
                  throw Error("请先保存或放弃当前编辑，再应用生成结果");
                await api("/jobs/" + j.id + "/apply", {
                  method: "POST",
                  body: { version: p.version },
                });
                await openProject(
                  j.project_id,
                  j.kind === "storyboard" ? "storyboard" : "media",
                );
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
        j.result?.application
          ? el("span", { hidden: "" })
          : button(
              "应用到本页",
              async () => {
                if (
                  !confirm("将替换本页选中的素材并产生新草稿版本，是否继续？")
                )
                  return;
                if (state.dirty)
                  throw Error("请先保存或放弃当前编辑，再应用生成结果");
                await api("/jobs/" + j.id + "/apply", {
                  method: "POST",
                  body: { version: p.version },
                });
                await openProject(
                  j.project_id,
                  j.kind === "storyboard" ? "storyboard" : "media",
                );
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
    if (j.result?.application)
      card.append(
        el(
          "p",
          {
            class:
              j.result.application.status === "applied" ? "note" : "danger",
          },
          j.result.application.message,
        ),
      );
    if (j.result?.review)
      card.append(
        el(
          "section",
          { class: "review-advice" },
          el("h4", {}, "检查建议 · 非人工审核结论"),
          el("p", { class: "muted" }, j.result.review.scope),
          el(
            "ul",
            {},
            j.result.review.suggestions.map((text) => el("li", {}, text)),
          ),
        ),
      );
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
    card.append(
      el(
        "pre",
        { class: "live-log", "aria-label": "任务实时日志" },
        Object.hasOwn(state.liveEvents, j.id)
          ? formatJobEvents(state.liveEvents[j.id]) ||
              "暂无日志，等待 Worker 处理。"
          : "此任务不在实时日志窗口内，请点击「查看日志」或「下载完整日志」。",
      ),
    );
    card.jobSignature = signature;
    if (old) {
      for (const selector of [
        ".manual-log-panel",
        ".storyboard-result",
        ".live-log",
      ]) {
        const node = old.querySelector(selector);
        if (node) {
          card.querySelector(selector)?.remove();
          card.append(node);
        }
      }
      old.replaceWith(card);
    }
    place(card);
  }
  target.querySelector(":scope > .empty")?.remove();
  if (!items.length)
    target.append(
      empty(
        "本项目还没有制作记录",
        "从创作要求生成分镜，或确认分镜后前往导出视频。",
      ),
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

function startProjectStream(pid) {
  stopProjectStream();
  state.projectJobSignature = "";
  const source = new EventSource("/api/projects/" + pid + "/events");
  state.projectStream = source;
  source.onopen = () => {
    if (source === state.projectStream && $("#stream-state"))
      $("#stream-state").textContent = "● 实时连接";
  };
  source.onerror = () => {
    if (source === state.projectStream && $("#stream-state"))
      $("#stream-state").textContent = "连接中断，正在重连…";
  };
  source.addEventListener("removed", () => {
    if (source !== state.projectStream) return;
    stopProjectStream();
    notice(
      "此项目已在其他页面移入回收站。未保存内容可通过「项目管理 → 草稿恢复」导出；项目可在列表的回收站恢复。",
    );
  });
  source.addEventListener("snapshot", (event) => {
    if (
      source !== state.projectStream ||
      state.project?.id !== pid ||
      state.tab !== "editor"
    )
      return;
    const data = JSON.parse(event.data);
    state.liveJobs = data.jobs;
    state.liveEvents = data.events;
    const session = state.historySession;
    if (session?.pid === pid) {
      for (const job of data.jobs) {
        const current = session.jobs.get(job.id);
        if (
          !current ||
          !current.updated ||
          !job.updated ||
          job.updated >= current.updated
        )
          session.jobs.set(job.id, job);
      }
      if (session.cursor === undefined)
        session.cursor =
          data.jobs.length === 100 ? data.jobs[data.jobs.length - 1].id : null;
    }
    updateHistoryControls();
    updateTaskDock();
    syncAutoAppliedProject(pid, data.jobs).catch((e) => notice(e.message));
    const target = $("#project-job-list");
    if (!target) return;
    const combined = mergedProjectJobs();
    const signature = JSON.stringify(combined);
    if (signature !== state.projectJobSignature) {
      renderJobs(combined, target);
      state.projectJobSignature = signature;
    }
    for (const card of target.querySelectorAll("[data-job-id]")) {
      const log = card.querySelector(".live-log");
      if (!Object.hasOwn(data.events, card.dataset.jobId)) {
        if (!log.textContent)
          log.textContent =
            "此任务不在实时日志窗口内，请点击「查看日志」或「下载完整日志」。";
        continue;
      }
      const text =
        (data.events[card.dataset.jobId] || [])
          .map(
            (e) =>
              new Date(e.created * 1000).toLocaleTimeString() +
              "  " +
              e.message,
          )
          .join("\n") || "暂无日志，等待 Worker 处理。";
      if (log.textContent !== text) {
        const atBottom =
          log.scrollHeight - log.scrollTop - log.clientHeight < 32;
        log.textContent = text;
        if (atBottom) log.scrollTop = log.scrollHeight;
      }
    }
  });
}
async function showProjectTasks() {
  setStudioStage("results");
}

const studioStages = {
  brief: ["创作要求", "主题、风格与 AI 初稿"],
  storyboard: ["分镜编排", "逐页打磨口播与画面"],
  media: ["图片与配音", "选择素材或按页生成"],
  export: ["导出视频", "确认音轨，提交渲染"],
  results: ["任务与结果", "实时日志、应用与下载"],
};
async function restoreRoute() {
  const parts = location.hash.replace(/^#\//, "").split("/");
  if (parts[0] === "project" && parts[1]) {
    try {
      await openProject(parts[1], studioStages[parts[2]] ? parts[2] : null);
    } catch (e) {
      await navigate("projects");
      notice(e.message);
    }
  } else
    await navigate(
      ["projects", "assets", "providers", "runtimes", "system"].includes(
        parts[0],
      )
        ? parts[0]
        : "projects",
    );
}
window.addEventListener("hashchange", () => {
  if (
    state.project &&
    location.hash.startsWith("#/project/" + state.project.id + "/")
  ) {
    const stage = location.hash.split("/")[3];
    if (studioStages[stage]) setStudioStage(stage);
  } else safe(restoreRoute)();
});
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
function mountStudio(p, scenes, outline, settings, ai, exportGroup) {
  const content = $("#content");
  const toolbar = content.querySelector(".editor-toolbar");
  const tools = toolbar.querySelector(".actions");
  tools.classList.add("project-tools-menu");
  const menu = el(
    "details",
    { class: "project-menu" },
    el("summary", {}, "项目管理"),
    tools,
  );
  toolbar.prepend(menu);
  const results = $("#project-tasks");
  const switcher = content.querySelector(".scene-switcher");
  const pane = el("div", { class: "studio-pane" });
  const stageHead = el(
    "div",
    { class: "stage-heading" },
    el("p", { class: "eyebrow", id: "stage-kicker" }),
    el("h2", { id: "stage-name" }),
    el("p", { id: "stage-description", class: "muted" }),
  );
  settings.append(
    button("下一步：编排分镜 →", () => setStudioStage("storyboard"), "wide"),
  );
  settings.open = true;
  ai.open = true;
  settings.hidden = false;
  ai.hidden = false;
  exportGroup.hidden = false;
  const brief = el(
    "section",
    { class: "studio-stage brief-stage", "data-stage": "brief" },
    settings,
    ai,
  );
  const editing = el(
    "section",
    { class: "studio-stage", "data-stage": "editing" },
    switcher,
    scenes,
  );
  const summary = el(
    "div",
    { class: "export-summary" },
    el("span", { class: "eyebrow" }, "制作清单"),
    el("h3", {}, p.scenes.length + " 页讲解 · " + (styles[p.style] || p.style)),
    el(
      "p",
      {},
      "图片 " +
        p.scenes.filter((s) => s.image_id).length +
        " / " +
        p.scenes.length +
        " 页 · 配音 " +
        p.scenes.filter((s) => s.audio_id).length +
        " / " +
        p.scenes.length +
        " 页",
    ),
    el(
      "p",
      { class: "note" },
      p.confirmed && !state.dirty
        ? "当前版本已确认，可选择音轨并制作。生成不会自动消耗其他模型额度。"
        : "请先保存并确认分镜，再提交视频制作。",
    ),
    button("返回分镜检查", () => setStudioStage("storyboard")),
  );
  const exporting = el(
    "section",
    { class: "studio-stage export-stage", "data-stage": "export" },
    summary,
    exportGroup,
  );
  results.classList.add("studio-stage");
  results.dataset.stage = "results";
  const steps = el(
    "nav",
    { class: "studio-steps", "aria-label": "项目制作阶段" },
    ...Object.entries(studioStages).map(([key, [title, hint]], i) =>
      el(
        "button",
        {
          type: "button",
          "data-stage-link": key,
          onclick: () => setStudioStage(key),
        },
        el("span", { class: "step-index" }, String(i + 1).padStart(2, "0")),
        el("span", {}, el("strong", {}, title), el("small", {}, hint)),
      ),
    ),
  );
  const rail = el(
    "div",
    { class: "studio-rail" },
    button("← 全部项目", () => navigate("projects"), "quiet"),
    el(
      "div",
      { class: "rail-project" },
      el("span", { class: "eyebrow" }, "当前项目"),
      el("h3", {}, p.title),
      el(
        "small",
        { class: "muted" },
        "v" + p.version + " · " + p.scenes.length + " 页分镜",
      ),
    ),
    steps,
    el(
      "p",
      { class: "rail-note" },
      "生成结果自动应用，检查建议供你审核。版本冲突时保留结果；历史版本可以恢复。",
    ),
  );
  const draftBanner = el(
    "section",
    { id: "draft-conflict", class: "draft-conflict", role: "status" },
    el(
      "div",
      {},
      el("strong", {}, "服务器已有新版本 · 本地草稿已保留"),
      el("p", {}, "先对比、导出或另存，再决定如何继续编辑。"),
    ),
    button("对比与保留草稿", showDraftRecovery),
  );
  draftBanner.hidden = state.draftConflict !== p.id;
  pane.append(
    toolbar,
    draftBanner,
    stageHead,
    brief,
    editing,
    exporting,
    results,
  );
  const dock = el(
    "div",
    { class: "studio-dock", id: "studio-dock", "aria-label": "当前任务" },
    el("span", { class: "dock-indicator", id: "dock-indicator" }),
    el(
      "div",
      { class: "dock-copy" },
      el("strong", { id: "dock-title" }, "准备好开始创作"),
      el("small", { id: "dock-message" }, "提交生成后，可在这里跟踪进度。"),
    ),
    button("日志与结果", showProjectTasks),
    button(
      "取消任务",
      async () => {
        const j = state.liveJobs.find((j) =>
          ["queued", "running"].includes(j.status),
        );
        if (j && confirm("取消当前任务？已发送的远端请求可能仍计费。"))
          await api("/jobs/" + j.id + "/cancel", { method: "POST" });
      },
      "danger dock-cancel",
    ),
  );
  content.replaceChildren(
    el("div", { class: "studio-shell" }, rail, pane),
    dock,
  );
  setStudioStage(state.stage);
  restoreSceneScroll();
  updateTaskDock();
}
function setStudioStage(stage) {
  if (!studioStages[stage] || !$(".studio-shell")) return;
  state.stage = stage;
  document.body.dataset.stage = stage;
  history.replaceState(null, "", "#/project/" + state.project.id + "/" + stage);
  $("#crumb").textContent = "视频项目 / " + studioStages[stage][0];
  $("#stage-kicker").textContent =
    "STEP 0" + (Object.keys(studioStages).indexOf(stage) + 1);
  $("#stage-name").textContent = studioStages[stage][0];
  $("#stage-description").textContent = studioStages[stage][1];
  for (const node of document.querySelectorAll(".studio-stage"))
    node.hidden =
      node.dataset.stage !== stage &&
      !(
        node.dataset.stage === "editing" &&
        ["storyboard", "media"].includes(stage)
      );
  for (const node of document.querySelectorAll("[data-stage-link]"))
    node.setAttribute(
      "aria-current",
      node.dataset.stageLink === stage ? "step" : "false",
    );
  $("#stage-name").setAttribute("tabindex", "-1");
  restoreSceneScroll();
}
async function announceSubmission() {
  notice(
    "任务已提交。你可以继续查看当前页面，底部任务条会实时更新；完成后点击「日志与结果」审阅。",
  );
  $("#dock-title").textContent = "任务已提交";
  $("#dock-message").textContent = "等待 Worker 领取，正在同步状态…";
}
function updateTaskDock() {
  if (!$("#dock-title")) return;
  const job =
    state.liveJobs.find((j) => ["queued", "running"].includes(j.status)) ||
    state.liveJobs[0];
  $(".dock-cancel").hidden =
    !job || !["queued", "running"].includes(job.status);
  if (!job) return;
  $("#dock-indicator").dataset.status = job.status;
  $("#dock-title").textContent =
    ({
      storyboard: "AI 分镜",
      image: "图片生成",
      speech: "语音合成",
      render: "视频制作",
    }[job.kind] || job.kind) +
    " · " +
    (labels[job.status] || job.status);
  const logs = state.liveEvents[job.id] || [];
  $("#dock-message").textContent =
    job.error || logs.at(-1)?.message || "等待 Worker 处理";
}

function syncCurrentRoute() {
  history.replaceState(
    null,
    "",
    state.tab === "editor" && state.project
      ? "#/project/" + state.project.id + "/" + state.stage
      : "#/" + state.tab,
  );
}

async function syncAutoAppliedProject(pid, jobs) {
  const version = Math.max(
    0,
    ...jobs
      .filter((j) => j.result?.application?.status === "applied")
      .map((j) => j.result.application.version),
  );
  if (
    !state.project ||
    state.project.id !== pid ||
    state.project.version >= version ||
    state.syncingProject
  )
    return;
  if (state.dirty) {
    markDraftConflict(pid);
    return;
  }
  state.syncingProject = true;
  const previousVersion = state.project.version;
  try {
    const updated = await api("/projects/" + pid);
    if (
      state.project?.id !== pid ||
      state.tab !== "editor" ||
      state.dirty ||
      state.project.version !== previousVersion
    )
      return;
    await hydrateAssets(updated);
    if (
      state.project?.id !== pid ||
      state.tab !== "editor" ||
      state.dirty ||
      state.project.version !== previousVersion
    )
      return;
    // Commit to the visible editor only after all awaits and conflict checks.
    state.project = updated;
    renderEditor();
    notice(
      "生成结果已自动应用为 v" +
        updated.version +
        "；可在任务与结果中查看检查建议，历史版本可恢复。",
    );
  } finally {
    state.syncingProject = false;
  }
}

function restoreSceneScroll() {
  const outline = $(".scene-outline");
  if (!outline?.clientWidth) return;
  outline.scrollLeft = state.sceneScroll;
  const active = outline.querySelectorAll(".outline-link")[state.activeScene];
  if (active) {
    const viewport = outline.getBoundingClientRect();
    const rect = active.getBoundingClientRect();
    if (rect.left < viewport.left)
      outline.scrollLeft -= viewport.left - rect.left;
    else if (rect.right > viewport.right)
      outline.scrollLeft += rect.right - viewport.right;
  }
  state.sceneScroll = outline.scrollLeft;
}
