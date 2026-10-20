/*
 * Pyodide 버전 연결부: 브라우저에 Python을 띄우고, 화면(app.js)의 /api/... 요청을 Python 함수로 넘긴다.
 *
 * - Python 실행기(Pyodide)는 처음 열 때 인터넷(jsDelivr)에서 받아 온다. 그 뒤로는 브라우저가 캐시한다.
 * - matcher/ 와 web/pyodide_api.py 소스는 이 페이지 안(window.PY_BUNDLE)에 들어 있다 → index.html 하나로 동작.
 * - 데이터는 Python의 가상 파일(profiles.json, social.json)에 저장되고, 요청마다 localStorage 로 옮겨 적는다.
 *   버전 1(JS 엔진)과 같은 github.io 주소를 쓰더라도 섞이지 않게 저장 이름 앞에 "dmpy."를 붙인다.
 */
(() => {
  const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
  const ROOT = "/home/pyodide/app";
  const DATA = `${ROOT}/data`;
  const KEY = { profiles: "dmpy.profiles", social: "dmpy.social", photo: (id) => `dmpy.photo.${id}` };
  const FILES = { profiles: `${DATA}/profiles.json`, social: `${DATA}/social.json` };

  let py = null;
  let api = null;
  const lastSaved = {};
  const avatarCache = new Map();

  // ── 저장 (localStorage가 막혀 있으면 이번 방문 동안만 유지) ──
  const get = (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  };
  const set = (k, v) => {
    try {
      localStorage.setItem(k, v);
    } catch (e) {
      if (e && e.name === "QuotaExceededError") throw new Error("브라우저 저장 공간이 가득 찼어요. 백업 파일을 받은 뒤 사진을 줄여 주세요.");
    }
  };
  const del = (k) => {
    try {
      localStorage.removeItem(k);
    } catch {}
  };

  // Python 파일 → localStorage (바뀐 경우만)
  function sync() {
    for (const [name, path] of Object.entries(FILES)) {
      const text = py.FS.readFile(path, { encoding: "utf8" });
      if (text !== lastSaved[name]) {
        set(KEY[name], text);
        lastSaved[name] = text;
      }
    }
  }

  // ── 로딩 화면 ──────────────────────────────────────────
  function showLoading() {
    const el = document.createElement("div");
    el.id = "pyLoading";
    el.style.cssText =
      "position:fixed;inset:0;z-index:50;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;" +
      "background:var(--bg,#f6f4f8);color:var(--text,#1d1b22);font-family:inherit;text-align:center;padding:24px";
    el.innerHTML = `
      <div style="width:64px;height:64px;border-radius:22px;display:grid;place-items:center;font-size:1.8rem;color:#fff;
        background:linear-gradient(135deg,#f2476b,#ff8a5c);animation:pyPulse 1.2s ease-in-out infinite">♥</div>
      <b style="font-size:1.1rem">Python 엔진을 준비하고 있어요</b>
      <span id="pyLoadingStep" style="color:var(--sub,#6e6a78);font-size:.9rem">Python 실행기 내려받는 중… (처음 한 번 5~15초)</span>
      <style>@keyframes pyPulse{50%{transform:scale(1.12)}}</style>`;
    document.body.appendChild(el);
    return (text) => {
      const step = document.getElementById("pyLoadingStep");
      if (step) step.textContent = text;
    };
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("Python 실행기를 내려받지 못했어요. 인터넷 연결을 확인하고 새로고침해 주세요."));
      document.head.appendChild(s);
    });
  }

  const ready = (async () => {
    const step = showLoading();
    try {
      await loadScript(`${PYODIDE_URL}pyodide.js`);
      py = await window.loadPyodide({ indexURL: PYODIDE_URL });
      step("pydantic 불러오는 중…");
      await py.loadPackage("pydantic");

      step("매칭 엔진(Python 코드) 올리는 중…");
      for (const [path, content] of Object.entries(window.PY_BUNDLE.files)) {
        const full = `${ROOT}/${path}`;
        py.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
        py.FS.writeFile(full, content);
      }
      // 이 브라우저에 저장해 둔 데이터가 있으면 이어서 쓴다 (없으면 Python이 샘플로 시작)
      for (const [name, path] of Object.entries(FILES)) {
        const saved = get(KEY[name]);
        if (saved) py.FS.writeFile(path, saved);
      }
      py.runPython(`import sys, os\nsys.path.insert(0, "${ROOT}")\nos.chdir("${ROOT}")`);
      api = py.pyimport("web.pyodide_api");
      api.start();
      sync();
      document.getElementById("pyLoading")?.remove();
    } catch (e) {
      step(`문제가 생겼어요: ${e.message || e}`);
      throw e;
    }
  })();

  // ── 화면(app.js)이 부르는 입구 ─────────────────────────────
  async function handle(path, options = {}) {
    await ready;
    const method = (options.method || "GET").toUpperCase();
    const res = JSON.parse(api.handle(method, path, options.body || ""));
    sync();
    if (!res.ok) throw new Error(res.error);

    // 사진은 Python 대신 localStorage에 보관 (Python은 photo="upload" 표시만 한다)
    const photo = /^\/api\/profiles\/(\d+)\/(photo|avatar)$/.exec(path);
    if (photo && method === "PUT") set(KEY.photo(photo[1]), JSON.parse(options.body).data_url);
    if (photo && photo[2] === "avatar") del(KEY.photo(photo[1]));
    if (path === "/api/reset")
      Object.keys(localStorage)
        .filter((k) => k.startsWith("dmpy.photo."))
        .forEach(del);
    return res.data;
  }

  function photoUrl(p) {
    if (p.photo === "upload") {
      const data = get(KEY.photo(p.id));
      if (data) return data;
    }
    if (!api) return "";
    const seed = p.photo && p.photo.startsWith("avatar:") ? p.photo.slice(7) : `${p.id}-${p.name}`;
    const key = `${seed}|${p.gender}`;
    if (!avatarCache.has(key)) avatarCache.set(key, "data:image/svg+xml;charset=utf-8," + encodeURIComponent(api.avatar(seed, p.gender)));
    return avatarCache.get(key);
  }

  // ── 백업 파일 받기 / 불러오기 ───────────────────────────
  function exportData() {
    const profiles = JSON.parse(py.FS.readFile(FILES.profiles, { encoding: "utf8" }));
    const social = JSON.parse(py.FS.readFile(FILES.social, { encoding: "utf8" }));
    const photos = Object.fromEntries(profiles.filter((p) => p.photo === "upload").map((p) => [p.id, get(KEY.photo(p.id))]));
    return JSON.stringify({ app: "dating-matcher", version: 1, engine: "python", profiles, social, photos });
  }
  function importData(text) {
    const data = JSON.parse(text);
    if (data.app !== "dating-matcher" || !Array.isArray(data.profiles)) throw new Error("이 앱의 백업 파일이 아니에요.");
    py.FS.writeFile(FILES.profiles, JSON.stringify(data.profiles));
    py.FS.writeFile(FILES.social, JSON.stringify({ likes: [], messages: {}, ...(data.social || {}) }));
    api.start(); // Python이 다시 읽으면서 예전 형식 데이터도 정리한다 (store.repair)
    sync();
    for (const [id, url] of Object.entries(data.photos || {})) if (url) set(KEY.photo(id), url);
    return JSON.parse(py.FS.readFile(FILES.profiles, { encoding: "utf8" })).length;
  }

  window.LOCAL_API = { handle, photoUrl, exportData, importData, ready, engine: "python" };
})();
