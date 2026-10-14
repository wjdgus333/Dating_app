const $ = (sel) => document.querySelector(sel);
const fmt = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let OPT = null;
let profiles = [];
let me = null;
let weights = {};
let dealbreakers = [];
let suggestions = [];
let runTimer = null;

const OP_LABEL = { exclude: "제외", require: "만 허용", in: "해당하면", min: "이상", max: "이하" };
const GRADIENTS = [
  ["#f2476b", "#ff8a5c"], ["#7b61ff", "#c86bff"], ["#1fb6a6", "#5ad1a0"], ["#ff9f43", "#ffd166"],
  ["#3a86ff", "#64c4ff"], ["#e056a0", "#f78fb3"], ["#2ec4b6", "#3a86ff"], ["#8e7dff", "#f2476b"],
];

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json();
  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => `• ${d.loc.slice(1).join(".") || "입력"}: ${d.msg.replace("Value error, ", "")}`).join("\n")
      : data.detail;
    throw new Error(detail || res.statusText);
  }
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 1800);
}

// 프로필 사진: 올린 사진 또는 애니메이션 캐릭터. 못 불러오면 이니셜이 보인다.
function photoUrl(p) {
  return `/api/profiles/${p.id}/photo?v=${encodeURIComponent(p.photo || "auto")}`;
}

function avatar(p, rank) {
  const [a, b] = GRADIENTS[p.id % GRADIENTS.length];
  return `<div class="avatar" style="background:linear-gradient(135deg,${a},${b})">${esc((p.name || "?")[0])}
    <img src="${photoUrl(p)}" alt="" loading="lazy" onerror="this.remove()">${rank ? `<span class="rank">${rank}위</span>` : ""}</div>`;
}

// 사진 파일 → 가운데를 정사각형으로 잘라 400px JPEG(data URL)로 줄인다.
async function resizePhoto(file) {
  const img = await createImageBitmap(file);
  const side = Math.min(img.width, img.height);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 400;
  canvas.getContext("2d").drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, 400, 400);
  return canvas.toDataURL("image/jpeg", 0.85);
}

async function uploadPhoto(profileId, file) {
  if (!file.type.startsWith("image/")) throw new Error("사진 파일만 올릴 수 있어요.");
  const data_url = await resizePhoto(file);
  return api(`/api/profiles/${profileId}/photo`, { method: "PUT", body: JSON.stringify({ data_url }) });
}

function replaceProfile(updated) {
  profiles = profiles.map((p) => (p.id === updated.id ? updated : p));
  if (me && me.id === updated.id) me = updated;
}

// 중요도·거르기 조건을 바꾸면 결과를 다시 계산하고 자동 저장한다.
function scheduleRun() {
  clearTimeout(runTimer);
  runTimer = setTimeout(run, 200);
  scheduleSave();
}

// ── 내 프로필 ───────────────────────────────────────────
function renderMe() {
  $("#meSummary").innerHTML = `${avatar({ ...me, name: me.nickname || me.name })}
    <div><b>${esc(me.nickname || me.name)}</b> <span class="meta">${me.age}세 · ${esc(me.city)} ${esc(me.district || "")}</span>
    <div class="meta">${esc(me.occupation)} · ${esc(me.education)}${me.mbti ? " · " + esc(me.mbti) : ""}</div>
    <div class="photo-actions">
      <label class="btn tiny soft">📷 사진 올리기<input type="file" accept="image/*" id="mePhoto" hidden></label>
      <button type="button" class="btn tiny ghost" id="meShuffle">🎲 캐릭터 바꾸기</button>
    </div></div>`;
  $("#mePhoto").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      replaceProfile(await uploadPhoto(me.id, file));
      renderMe();
      run();
      toast("사진을 올렸어요");
    } catch (err) {
      toast(err.message);
    }
  });
  $("#meShuffle").addEventListener("click", async () => {
    replaceProfile(await api(`/api/profiles/${me.id}/avatar`, { method: "POST" }));
    renderMe();
    run();
  });
}

// ── 중요도 ──────────────────────────────────────────────
function renderWeights() {
  const levels = Object.entries(OPT.importance_levels);
  $("#weights").innerHTML = Object.entries(OPT.score_categories)
    .map(([key, c]) => {
      const v = weights[key] ?? OPT.default_weight;
      return `<div class="weight-row">
        <span class="name">${esc(c.label)}<span class="logic">${esc(c.logic)}</span></span>
        <div class="segmented" data-key="${key}">${levels
          .map(([w, label]) => `<button type="button" data-w="${w}" class="lv-${w} ${Number(w) === v ? "on" : ""}">${label}</button>`)
          .join("")}</div></div>`;
    })
    .join("");
  $("#weights").querySelectorAll(".segmented").forEach((seg) =>
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      weights[seg.dataset.key] = Number(btn.dataset.w);
      seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
      scheduleRun();
    })
  );
}

// ── 거르기 ──────────────────────────────────────────────
function describeRule(d) {
  const label = OPT.dealbreaker_fields[d.field].label;
  const v = Array.isArray(d.value) ? d.value.join(", ") : d.value;
  if (d.field === "interests") return d.op === "exclude" ? `관심사에 ${v} 있으면 제외` : `관심사에 ${v} 중 하나 필수`;
  return `${label}: ${v} ${OP_LABEL[d.op]}`;
}

function renderRules() {
  $("#dealbreakers").innerHTML = dealbreakers.length
    ? dealbreakers
        .map((d, i) => `<span class="chip rule">${esc(describeRule(d))}<button type="button" data-i="${i}" aria-label="삭제">✕</button></span>`)
        .join("")
    : `<span class="empty">아직 거르는 조건이 없어요.</span>`;
  $("#dealbreakers").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      dealbreakers.splice(Number(b.dataset.i), 1);
      renderRules();
      scheduleRun();
    })
  );
}

function addRule(rule) {
  // 같은 항목·같은 방식의 조건은 하나로 합친다.
  const same = dealbreakers.find((d) => d.field === rule.field && d.op === rule.op);
  if (same && Array.isArray(same.value)) same.value = [...new Set([...same.value, ...rule.value])];
  else if (same) same.value = rule.value;
  else dealbreakers.push({ field: rule.field, op: rule.op, value: rule.value });
  renderRules();
  scheduleRun();
}

// 항목 고르기 → 조건(제외/이상 …) → 값 칩 → 추가. 거르기와 추가 점수가 같이 쓴다.
// prefix: 요소 id 앞부분 (db → dbField, dbOp, dbValueWrap, dbAdd)
function setupRuleBuilder(prefix, fields, onAdd) {
  const el = (name) => $(`#${prefix}${name}`);
  let op = null;

  function render() {
    const field = el("Field").value;
    const ops = fields[field].ops;
    if (!ops.includes(op)) op = ops[0];
    el("Op").innerHTML = ops
      .map((o) => `<button type="button" data-op="${o}" class="${o === op ? "on" : ""}">${OP_LABEL[o]}</button>`)
      .join("");
    const choices = fields[field].choices;
    const wrap = el("ValueWrap");
    if ((op === "min" || op === "max") && field !== "education") {
      wrap.innerHTML = `<input class="select number-input" type="number" value="${field === "age" ? 25 : 165}">`;
    } else if (op === "min" || op === "max") {
      wrap.innerHTML = choices.map((c, i) => `<span class="chip ${i === 2 ? "on" : ""}" data-v="${esc(c)}" data-single>${esc(c)}</span>`).join("");
    } else {
      wrap.innerHTML = choices.map((c) => `<span class="chip" data-v="${esc(c)}">${esc(c)}</span>`).join("");
    }
  }

  el("Field").innerHTML = Object.entries(fields)
    .map(([k, v]) => `<option value="${k}">${v.label}</option>`)
    .join("");
  el("Field").addEventListener("change", render);
  el("Op").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    op = b.dataset.op;
    render();
  });
  el("ValueWrap").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    if (chip.hasAttribute("data-single")) el("ValueWrap").querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
    chip.classList.toggle("on");
  });
  el("Add").addEventListener("click", () => {
    const field = el("Field").value;
    const num = el("ValueWrap").querySelector(".number-input");
    let value;
    if (num) value = Number(num.value);
    else {
      const picked = [...el("ValueWrap").querySelectorAll(".chip.on")].map((c) => c.dataset.v);
      if (!picked.length) return toast("값을 하나 이상 골라 주세요");
      value = op === "min" || op === "max" ? picked[0] : picked;
    }
    onAdd({ field, op, value });
    el("ValueWrap").querySelectorAll(".chip.on:not([data-single])").forEach((c) => c.classList.remove("on"));
  });
  render();
}

function setupBuilder() {
  setupRuleBuilder("db", OPT.dealbreaker_fields, addRule);
}

// ── 추가 점수 · 감점 ────────────────────────────────────
// 둘 다 bonusRules 한 목록에 저장한다. 감점은 points가 음수.
let bonusRules = [];
const pickedPoints = { bn: 10, pn: 10 };

function describeBonus(r) {
  const label = OPT.bonus_fields[r.field].label;
  const v = Array.isArray(r.value) ? r.value.join(", ") : r.value;
  const cond = r.op === "min" ? `${label} ${v} 이상` : r.op === "max" ? `${label} ${v} 이하` : r.field === "interests" ? `관심사에 ${v}` : `${label} ${v}`;
  return `${cond} → ${r.points > 0 ? "+" : "−"}${Math.abs(r.points)}`;
}

function renderBonus() {
  const render = (targetId, isPenalty, empty) => {
    const items = bonusRules.map((r, i) => [r, i]).filter(([r]) => (r.points < 0) === isPenalty);
    $(targetId).innerHTML = items.length
      ? items
          .map(([r, i]) => `<span class="chip rule ${isPenalty ? "penalty" : "bonus"}">${esc(describeBonus(r))}<button type="button" data-i="${i}" aria-label="삭제">✕</button></span>`)
          .join("")
      : `<span class="empty">${empty}</span>`;
    $(targetId).querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => {
        bonusRules.splice(Number(b.dataset.i), 1);
        renderBonus();
        scheduleRun();
      })
    );
  };
  render("#bonusRules", false, "아직 추가 점수 규칙이 없어요.");
  render("#penaltyRules", true, "아직 감점 규칙이 없어요.");
}

// prefix 'bn' = 추가 점수(+), 'pn' = 감점(−)
function setupScoreRule(prefix, sign) {
  const pointsEl = $(`#${prefix}Points`);
  pointsEl.innerHTML = OPT.bonus_points
    .map((p) => `<button type="button" data-p="${p}" class="${p === pickedPoints[prefix] ? "on" : ""}">${sign > 0 ? "+" : "−"}${p}</button>`)
    .join("");
  pointsEl.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    pickedPoints[prefix] = Number(b.dataset.p);
    pointsEl.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
  });
  setupRuleBuilder(prefix, OPT.bonus_fields, (rule) => {
    const points = sign * pickedPoints[prefix];
    // 같은 항목·조건·점수면 값만 합친다.
    const same = bonusRules.find((r) => r.field === rule.field && r.op === rule.op && r.points === points && Array.isArray(r.value));
    if (same && Array.isArray(rule.value)) same.value = [...new Set([...same.value, ...rule.value])];
    else bonusRules.push({ ...rule, points });
    renderBonus();
    scheduleRun();
  });
}

function setupBonus() {
  setupScoreRule("bn", +1);
  setupScoreRule("pn", -1);
}

async function parseText() {
  const text = $("#dbText").value.trim();
  if (!text) return toast("문장을 먼저 적어 주세요");
  const res = await api("/api/dealbreakers/parse", { method: "POST", body: JSON.stringify({ text }) });
  suggestions = res.rules;
  const rows = suggestions
    .map(
      (r, i) => `<div class="suggest-row"><div><b>${esc(r.text)}</b><span class="src">“${esc(r.source)}”</span></div>
        <button type="button" class="btn tiny soft" data-i="${i}">추가</button></div>`
    )
    .join("");
  const unmatched = res.unmatched.length
    ? `<div class="unmatched">이해하지 못한 문장: ${res.unmatched.map((u) => `“${esc(u)}”`).join(", ")} — 아래 ‘직접 고르기’로 추가해 주세요.</div>`
    : "";
  $("#dbSuggest").innerHTML = suggestions.length || unmatched
    ? `<div class="suggest">${rows || '<span class="empty">찾은 조건이 없어요.</span>'}${
        suggestions.length > 1 ? '<button type="button" class="btn tiny primary" data-all>모두 추가</button>' : ""
      }${unmatched}</div>`
    : "";
}

function setupSuggest() {
  $("#dbParse").addEventListener("click", () => parseText().catch((e) => toast(e.message)));
  $("#dbSuggest").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-all")) {
      suggestions.forEach(addRule);
      $("#dbSuggest").innerHTML = "";
      toast(`조건 ${suggestions.length}개를 추가했어요`);
    } else {
      addRule(suggestions[Number(b.dataset.i)]);
      b.closest(".suggest-row").remove();
    }
  });
}

// ── 결과 ────────────────────────────────────────────────
function renderFlow(r) {
  const f = r.funnel;
  const steps = [
    ["전체", f.total],
    ["① 거르기 통과", f.passed_filter],
    ["② 후보", f.candidates],
    ["③ 추천", r.ranking.length],
  ];
  return `<section class="card">
    <div class="card-title"><h2>어떻게 골랐나요?</h2><span class="hint">${f.retrieval_used ? "임베딩으로 후보를 줄였어요" : "인원이 적어 전원 채점"}</span></div>
    <div class="flow">${steps
      .map(([n, v], i) => `<div class="flow-step ${i === 3 ? "last" : ""}"><div class="n">${n}</div><div class="v">${v}<small>명</small></div></div>`)
      .join("")}</div>
    <ul class="flow-notes">${r.trace.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
  </section>`;
}

function renderWhy(r) {
  const w = r.why_detail;
  if (!w) return "";
  if (!w.second) return `<section class="card"><div class="why-head">${esc(r.why_first[0])}</div></section>`;
  const item = (i, up) => `<li class="why-item">
      <span class="delta ${up ? "up" : "down"}">${up ? "+" : ""}${fmt(i.diff)}</span>
      <div><b>${esc(i.label)}</b> <span class="vs">1위 ${esc(i.first)} · 2위 ${esc(i.second)}</span>
      ${i.note ? `<span class="note">${esc(i.note)}</span>` : ""}</div></li>`;
  return `<section class="card">
    <div class="card-title"><h2>왜 ${esc(w.first.name)}님이 1위인가요?</h2></div>
    <div class="why-head">${esc(w.first.name)} ${fmt(w.first.score)}점 vs ${esc(w.second.name)} ${fmt(w.second.score)}점 — ${
      w.gap ? `${fmt(w.gap)}점 차이` : "동점 (인증 회원 → 나이 차이가 적은 순)"
    }</div>
    <ul class="why-list">${w.ahead.map((i) => item(i, true)).join("")}${w.behind.map((i) => item(i, false)).join("")}</ul>
    ${w.weight_note ? `<div class="callout">${esc(w.weight_note)}</div>` : ""}
  </section>`;
}

// 다시 계산해도 열어 둔 '점수 계산 보기'는 열린 채로, 점수가 바뀌면 변화량을 잠깐 보여 준다.
let prevScores = {};
let openDetails = new Set();

function breakdownRow(b, mutual) {
  const isBonus = b.key.includes("bonus:");
  return `<div class="bd-row ${b.matches ? "hit" : "miss"} ${isBonus ? "bonus" : ""}">
    <span class="lbl">${esc(b.label)}<small>${isBonus ? "추가 점수 규칙" : `중요도 ${b.weight}${mutual ? ` · 상대 ${b.their_weight}` : ""}`}</small></span>
    <span class="detail">${esc(b.detail)}${b.key === "interests" && b.matches ? ` → ${b.weight}점 × ${b.matches}개` : ""}</span>
    <span class="num">${b.contribution ? (b.contribution > 0 ? "+" : "−") + fmt(Math.abs(b.contribution)) : "0"}</span></div>`;
}

function renderPerson(x, mutual) {
  const mine = new Set(me.interests);
  const chips = x.interests.map((t) => `<span class="chip ${mine.has(t) ? "shared" : ""}">${esc(t)}</span>`).join("");
  const baseRows = x.breakdown.filter((b) => !b.key.includes("bonus:")).map((b) => breakdownRow(b, mutual)).join("");
  const theirBonus = x.breakdown.filter((b) => b.key.startsWith("their_bonus:")).map((b) => breakdownRow(b, mutual)).join("");
  const checkRows = (checks) =>
    checks
      .map((c) => {
        const pts = mutual ? c.points / 2 : c.points;
        return `<div class="bd-row ${c.points < 0 ? "penalty" : "bonus"} ${c.hit ? "hit" : "miss"}">
          <span class="lbl">${c.hit ? "✓ 해당" : "✕ 미해당"}<small>${c.points > 0 ? "+" : "−"}${Math.abs(c.points)}점 규칙</small></span>
          <span class="detail">${esc(c.text)}<br><span class="sub">${esc(c.reason)}</span></span>
          <span class="num">${c.hit ? (pts > 0 ? "+" : "−") + fmt(Math.abs(pts)) : "0"}</span></div>`;
      })
      .join("");
  const bonusRows = checkRows(x.bonus_checks.filter((c) => c.points > 0));
  const penaltyRows = checkRows(x.bonus_checks.filter((c) => c.points < 0));
  const hitBonus = x.bonus_checks.filter((c) => c.hit);
  const prev = prevScores[x.id];
  const delta = prev === undefined ? 0 : x.score - prev;
  const deltaTag = delta ? `<span class="delta-tag ${delta > 0 ? "up" : "down"}">${delta > 0 ? "↑ +" : "↓ −"}${fmt(Math.abs(delta))}</span>` : "";

  return `<article class="person">
    ${avatar(x, x.rank)}
    <div class="body">
      <h3>${esc(x.name)} ${x.verified ? '<span class="badge">인증</span>' : ""}</h3>
      <div class="meta">${x.age}세 · ${esc(x.region)} · ${esc(x.occupation)} · ${esc(x.education)}</div>
      ${x.rank_with_default_weights !== x.rank ? `<span class="moved">중요도가 모두 보통이었다면 ${x.rank_with_default_weights}위</span>` : ""}
      <div class="chips">${chips}</div>
      ${hitBonus.length ? `<div class="chips bonus-hits">${hitBonus
        .map((c) => (c.points > 0 ? `<span class="chip bonus-hit">★ ${esc(c.text)}</span>` : `<span class="chip penalty-hit">▼ ${esc(c.text)}</span>`))
        .join("")}</div>` : ""}
      <ul class="points">${x.highlights.map((h) => `<li class="good">${esc(h)}</li>`).join("")}${x.weak_points
        .map((w) => `<li class="bad">${esc(w)}</li>`)
        .join("")}</ul>
      ${x.llm_summary ? `<div class="llm">💬 ${esc(x.llm_summary)}</div>` : ""}
      ${likeButton(x)}
      ${mutual ? `<div class="meta" style="margin-top:8px">내 기준 ${x.my_score}점 · 상대 기준 ${x.their_score}점 → 평균</div>` : ""}
      <details class="more" data-id="${x.id}" ${openDetails.has(x.id) ? "open" : ""}><summary>점수 계산 보기</summary>
        <p class="formula">${esc(x.formula)}</p>
        <div class="bd-section"><span>중요도 점수</span><b>${fmt(x.base_score)}점</b></div>
        <div class="bd">${baseRows}</div>
        <div class="bd-section bonus"><span>추가 점수</span><b>+${fmt(x.bonus_score)}점</b></div>
        <div class="bd">${bonusRows || (theirBonus ? "" : '<p class="skipped">추가 점수 규칙이 없어요. 왼쪽 ‘추가 점수’에서 넣을 수 있어요.</p>')}${theirBonus}</div>
        <div class="bd-section penalty"><span>감점</span><b>${x.penalty_score ? "−" + fmt(-x.penalty_score) : "0"}점</b></div>
        <div class="bd">${penaltyRows || '<p class="skipped">감점 규칙이 없어요. 왼쪽 ‘감점’에서 넣을 수 있어요.</p>'}</div>
        <div class="bd-total"><span>합계</span><b>${fmt(x.base_score)} + ${fmt(x.bonus_score)} − ${fmt(-x.penalty_score)} = ${fmt(x.score)}점</b></div>
        ${x.skipped.length ? `<p class="skipped">정보가 없어 계산에서 뺀 항목: ${esc(x.skipped.join(", "))}</p>` : ""}
      </details>
    </div>
    <div class="score-badge ${delta ? "changed" : ""}"><b>${fmt(x.score)}</b><small>점</small>
      ${x.bonus_score || x.penalty_score ? `<span class="split">${fmt(x.base_score)}${x.bonus_score ? ` + <em>${fmt(x.bonus_score)}</em>` : ""}${
        x.penalty_score ? ` − <em>${fmt(-x.penalty_score)}</em>` : ""
      }</span>` : ""}
      ${deltaTag}</div>
  </article>`;
}

function renderResult(r) {
  const ranking = r.ranking.length
    ? r.ranking.map((x) => renderPerson(x, r.settings.mutual)).join("")
    : `<p class="empty">조건을 모두 통과한 사람이 없어요. 거르기 조건을 조금 줄여 보세요.</p>`;
  const out = r.eliminated.length
    ? `<section class="card"><div class="card-title"><h2>거르기로 탈락</h2><span class="hint">점수가 높아도 조건에 걸리면 제외</span></div>
        ${r.eliminated
          .map(
            (e) => `<div class="out"><div><b>${esc(e.name)}</b> <span class="meta">${e.age}세 · ${esc(e.region)}</span>
              ${e.reasons.map((x) => `<div class="reason">✕ ${esc(x)}</div>`).join("")}</div>
              <div class="would">점수였다면<b>${e.would_be_score}</b></div></div>`
          )
          .join("")}</section>`
    : "";
  $("#result").innerHTML = `${renderFlow(r)}${renderWhy(r)}
    <section class="card"><div class="card-title"><h2>추천 순위</h2><span class="hint">분홍 태그는 겹치는 관심사 · ★ 추가 점수 · ▼ 감점</span></div>${ranking}</section>
    ${out}`;
  $("#result").querySelectorAll("details.more").forEach((d) =>
    d.addEventListener("toggle", () => (d.open ? openDetails.add(Number(d.dataset.id)) : openDetails.delete(Number(d.dataset.id))))
  );
  prevScores = Object.fromEntries(r.ranking.map((x) => [x.id, x.score]));
}

function currentPreferences() {
  return { ...me.preferences, weights: { ...weights }, dealbreakers, bonus_rules: bonusRules, dealbreaker_text: $("#dbText").value };
}

async function run() {
  $("#result").classList.add("loading");
  try {
    const result = await api("/api/recommend", {
      method: "POST",
      body: JSON.stringify({
        user_id: me.id,
        preferences: currentPreferences(),
        mutual: $("#mutual").checked,
        use_llm: $("#useLlm").checked,
      }),
    });
    renderResult(result);
  } catch (e) {
    $("#result").innerHTML = `<section class="card error">${esc(e.message)}</section>`;
  } finally {
    $("#result").classList.remove("loading");
  }
}

// ── 좋아요 · 채팅 ───────────────────────────────────────
let inboxData = { received: [], matches: [], sent: [] };
let likeTarget = null;
let chatWith = null;
let chatTimer = null;

function likeButton(x) {
  if (inboxData.matches.some((m) => m.id === x.id))
    return `<button class="btn soft like-btn" data-chat="${x.id}">💬 채팅하기</button>`;
  if (inboxData.sent.includes(x.id)) return `<button class="btn like-btn sent" disabled>♥ 좋아요 보냄</button>`;
  const likedMe = inboxData.received.some((r) => r.id === x.id);
  return `<button class="btn primary like-btn" data-like="${x.id}" data-name="${esc(x.name)}">♥ 좋아요${likedMe ? " (나를 좋아해요!)" : ""}</button>`;
}

async function loadInbox() {
  inboxData = await api(`/api/users/${me.id}/inbox`);
  const unread = inboxData.matches.reduce((s, m) => s + m.unread, 0) + inboxData.received.length;
  $("#chatBadge").hidden = !unread;
  $("#chatBadge").textContent = unread;
  renderInbox();
}

function renderInbox() {
  $("#received").innerHTML = inboxData.received.length
    ? inboxData.received
        .map(
          (r) => `<div class="received-item"><div class="list-item" style="padding:0;cursor:default">${avatar(r)}
            <div class="grow"><b>${esc(r.name)}</b><div class="meta">${r.age}세 · ${esc(r.region)} · ${esc(r.occupation)}</div></div></div>
            ${r.message ? `<div class="msg">“${esc(r.message)}”</div>` : ""}
            <button class="btn tiny primary" data-like="${r.id}" data-name="${esc(r.name)}">♥ 좋아요 돌려주기</button></div>`
        )
        .join("")
    : `<span class="empty">아직 받은 좋아요가 없어요.</span>`;
  $("#matches").innerHTML = inboxData.matches.length
    ? inboxData.matches
        .map(
          (m) => `<div class="list-item ${chatWith === m.id ? "active" : ""}" data-chat="${m.id}">${avatar(m)}
            <div class="grow"><b>${esc(m.name)}</b><div class="preview">${m.last ? esc(m.last.text) : "매칭됐어요! 먼저 인사해 보세요"}</div></div>
            ${m.unread ? `<span class="unread">${m.unread}</span>` : ""}</div>`
        )
        .join("")
    : `<span class="empty">아직 매칭된 사람이 없어요.</span>`;
}

function openLikeModal(id, name) {
  likeTarget = Number(id);
  $("#likeTitle").textContent = `${name}님에게 좋아요 보내기`;
  $("#likeMessage").value = "";
  $("#likeModal").hidden = false;
  $("#likeMessage").focus();
}

async function sendLike() {
  try {
    const res = await api("/api/likes", {
      method: "POST",
      body: JSON.stringify({ from_id: me.id, to_id: likeTarget, message: $("#likeMessage").value }),
    });
    $("#likeModal").hidden = true;
    toast(res.matched ? "🎉 매칭됐어요! 채팅 탭에서 대화해 보세요" : "좋아요를 보냈어요");
    await loadInbox();
    run();
    if (res.matched && !$("#view-chat").hidden) openChat(likeTarget);
  } catch (e) {
    toast(e.message);
  }
}

async function openChat(otherId) {
  chatWith = Number(otherId);
  showTab("chat");
  await refreshChat(true);
  clearInterval(chatTimer);
  chatTimer = setInterval(() => refreshChat(false), 3000); // 상대 메시지를 3초마다 확인
}

async function refreshChat(scroll) {
  if (!chatWith || $("#view-chat").hidden) return;
  const data = await api(`/api/chats/${me.id}/${chatWith}`);
  const body = data.messages
    .map((m) => {
      const mine = m.from === me.id;
      const time = m.at.slice(5, 16).replace("T", " ");
      return `<div class="bubble ${mine ? "mine" : "theirs"}">${esc(m.text)}</div><div class="bubble-time ${mine ? "mine" : ""}">${time}</div>`;
    })
    .join("");
  const room = $("#chatRoom");
  const prevBody = room.querySelector(".chat-body");
  const atBottom = prevBody && prevBody.scrollHeight - prevBody.scrollTop - prevBody.clientHeight < 40;
  const draft = room.querySelector("textarea")?.value ?? "";
  room.innerHTML = `
    <div class="chat-head">${avatar(data.with)}
      <div class="grow"><b>${esc(data.with.name)}</b><div class="meta">${data.with.age}세 · ${esc(data.with.region)} · ${esc(data.with.occupation)}</div></div>
      <button class="btn tiny ghost" id="blockBtn">차단</button></div>
    <div class="chat-body">${body || '<div class="chat-empty">매칭됐어요! 먼저 인사해 보세요 👋</div>'}</div>
    <form class="chat-input" id="chatForm"><textarea rows="1" maxlength="500" placeholder="메시지 입력 (Enter 전송, Shift+Enter 줄바꿈)"></textarea>
      <button class="btn primary">전송</button></form>`;
  const ta = room.querySelector("textarea");
  ta.value = draft;
  const newBody = room.querySelector(".chat-body");
  if (scroll || atBottom) newBody.scrollTop = newBody.scrollHeight;
  if (scroll) ta.focus();
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      room.querySelector("#chatForm").requestSubmit();
    }
  });
  room.querySelector("#chatForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text) return;
    try {
      await api(`/api/chats/${chatWith}`, { method: "POST", body: JSON.stringify({ sender_id: me.id, text }) });
      ta.value = "";
      await refreshChat(true);
      loadInbox();
    } catch (err) {
      toast(err.message);
    }
  });
  room.querySelector("#blockBtn").addEventListener("click", async () => {
    if (!confirm(`${data.with.name}님을 차단할까요? 대화가 지워지고 서로 추천에서도 빠져요.`)) return;
    const updated = await api("/api/block", { method: "POST", body: JSON.stringify({ user_id: me.id, target_id: chatWith }) });
    profiles = profiles.map((p) => (p.id === updated.id ? updated : p));
    me = updated;
    chatWith = null;
    room.innerHTML = '<div class="chat-empty">차단했어요.</div>';
    await loadInbox();
    run();
  });
  if (data.messages.some((m) => m.to === me.id)) loadInbox(); // 읽음 처리 반영
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("#view-match").hidden = name !== "match";
  $("#view-chat").hidden = name !== "chat";
  $("#view-signup").hidden = name !== "signup";
  if (name !== "chat") clearInterval(chatTimer);
  if (name === "chat") loadInbox();
}

function setupSocial() {
  // 추천 카드 · 받은 좋아요 · 매칭 목록의 버튼은 모두 여기서 처리
  document.addEventListener("click", (e) => {
    const like = e.target.closest("[data-like]");
    if (like) return openLikeModal(like.dataset.like, like.dataset.name);
    const chat = e.target.closest("[data-chat]");
    if (chat) return openChat(chat.dataset.chat);
  });
  $("#likeCancel").addEventListener("click", () => ($("#likeModal").hidden = true));
  $("#likeSend").addEventListener("click", sendLike);
  $("#likeModal").addEventListener("click", (e) => {
    if (e.target.id === "likeModal") $("#likeModal").hidden = true;
  });
}

async function selectUser(id) {
  me = profiles.find((p) => p.id === Number(id));
  rememberUser(me.id);
  prevScores = {}; // 사용자를 바꾸면 점수 변화 표시는 새로 시작
  openDetails = new Set();
  clearTimeout(saveTimer); // 이전 사용자의 저장 대기분이 새 사용자에게 저장되지 않게
  $("#saveStatus").textContent = "설정을 바꾸면 자동으로 저장돼요";
  chatWith = null;
  clearInterval(chatTimer);
  $("#chatRoom").innerHTML = '<div class="chat-empty">왼쪽에서 매칭된 사람을 골라 대화를 시작해 보세요.</div>';
  await loadInbox();
  $("#user").value = me.id;
  $("#chatUser").value = me.id;
  weights = { ...me.preferences.weights };
  dealbreakers = structuredClone(me.preferences.dealbreakers);
  bonusRules = structuredClone(me.preferences.bonus_rules || []);
  $("#dbText").value = me.preferences.dealbreaker_text || "";
  $("#dbSuggest").innerHTML = "";
  renderMe();
  renderWeights();
  renderRules();
  renderBonus();
  run();
}

async function loadProfiles(selectId) {
  profiles = await api("/api/profiles");
  const options = profiles
    .map((p) => `<option value="${p.id}">${p.nickname || p.name} · ${p.gender} ${p.age}세</option>`)
    .join("");
  $("#user").innerHTML = options;
  $("#chatUser").innerHTML = options;
  await selectUser(profiles.some((p) => p.id === selectId) ? selectId : profiles[0].id);
}

// ── 프로필 등록 ─────────────────────────────────────────
function renderSignup() {
  const sel = (name, list, required) =>
    `<select name="${name}" ${required ? "required" : ""}><option value="">선택</option>${list
      .map((x) => `<option>${esc(x)}</option>`)
      .join("")}</select>`;
  const R = '<b class="req">*</b>';
  $("#signup").innerHTML = `
    <div class="group-title">기본 정보</div>
    <label>이름 ${R}<input name="name" required maxlength="20"></label>
    <label>성별 ${R}${sel("gender", OPT.genders, true)}</label>
    <label>나이 ${R}<input name="age" type="number" min="19" max="80" required></label>
    <label>키<input name="height" type="number" min="130" max="220"></label>
    <label>시·도 ${R}${sel("city", Object.keys(OPT.regions), true)}</label>
    <label>구/시<select name="district"><option value="">선택</option></select></label>
    <div class="group-title">학력 · 직업</div>
    <label>최종학력 ${R}${sel("education", OPT.education, true)}</label>
    <label>직업 ${R}<input name="occupation" required maxlength="30"></label>
    <div class="group-title">라이프스타일</div>
    <label>흡연${sel("smoking", OPT.smoking)}</label>
    <label>음주${sel("drinking", OPT.drinking)}</label>
    <label>종교${sel("religion", OPT.religion)}</label>
    <label>운동 빈도${sel("exercise", OPT.exercise)}</label>
    <label>MBTI<input name="mbti" maxlength="4" placeholder="ENFP"></label>
    <label>연락 빈도${sel("contact_frequency", OPT.contact_frequency)}</label>
    <label>데이트 스타일${sel("date_style", OPT.date_style)}</label>
    <label>원하는 관계${sel("relationship_goal", OPT.relationship_goal)}</label>
    <label>만나고 싶은 성별${sel("target", OPT.genders)}</label>
    <div class="group-title">관심사 <span class="hint">최대 10개</span></div>
    <div class="full chips pick" id="signupInterests">${OPT.interests
      .map((t) => `<span class="chip" data-v="${t}">${t}</span>`)
      .join("")}</div>
    <div class="group-title">프로필 사진 <span class="hint">안 올리면 애니메이션 캐릭터가 자동으로 들어가요</span></div>
    <div class="full photo-pick">
      <div class="photo-preview" id="signupPreview">🙂</div>
      <label class="btn soft">📷 사진 고르기<input type="file" accept="image/*" id="signupPhoto" hidden></label>
    </div>
    <div class="group-title">자기소개</div>
    <label class="full"><textarea name="bio" rows="4" maxlength="1000" placeholder="주말엔 주로 무엇을 하나요? 어떤 데이트를 좋아하나요?"></textarea></label>
    <div class="full"><button class="btn primary">등록하기</button></div>`;
  const form = $("#signup");
  form.city.addEventListener("change", () => {
    form.district.innerHTML =
      '<option value="">선택</option>' + (OPT.regions[form.city.value] || []).map((d) => `<option>${d}</option>`).join("");
  });
  $("#signupInterests").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    if (!chip.classList.contains("on") && $("#signupInterests").querySelectorAll(".on").length >= 10)
      return toast("관심사는 최대 10개까지 고를 수 있어요");
    chip.classList.toggle("on");
  });
  let signupFile = null;
  $("#signupPhoto").addEventListener("change", async (e) => {
    signupFile = e.target.files[0] || null;
    $("#signupPreview").innerHTML = signupFile ? `<img src="${await resizePhoto(signupFile)}" alt="">` : "🙂";
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    fd.delete("photo");
    const body = {
      interests: [...$("#signupInterests").querySelectorAll(".on")].map((c) => c.dataset.v),
      preferences: {},
    };
    for (const [k, v] of fd.entries()) {
      if (k === "target" || v === "") continue;
      body[k] = ["age", "height"].includes(k) ? Number(v) : v;
    }
    if (fd.get("target")) body.preferences.target_genders = [fd.get("target")];
    try {
      let created = await api("/api/profiles", { method: "POST", body: JSON.stringify(body) });
      if (signupFile) created = await uploadPhoto(created.id, signupFile);
      signupFile = null;
      $("#signupPreview").innerHTML = "🙂";
      $("#signupMsg").innerHTML = `<span class="ok">${esc(created.name)}님 등록 완료! 추천 탭에서 확인해 보세요.</span>`;
      form.reset();
      $("#signupInterests").querySelectorAll(".on").forEach((c) => c.classList.remove("on"));
      await loadProfiles(created.id);
    } catch (err) {
      $("#signupMsg").innerHTML = `<span class="error">${esc(err.message)}</span>`;
    }
  });
}

// ── 시작 ────────────────────────────────────────────────
async function init() {
  OPT = await api("/api/options");

  setupSocial();
  $("#quit").addEventListener("click", async () => {
    if (!confirm("서버를 종료할까요? 다시 쓰려면 터미널에서 다시 실행해야 해요.")) return;
    try {
      await api("/api/shutdown", { method: "POST" });
    } catch (e) {
      return toast(e.message);
    }
    clearInterval(chatTimer);
    document.querySelectorAll("header, main").forEach((el) => (el.hidden = true));
    $("#byeScreen").hidden = false;
  });
  document.querySelectorAll(".tab").forEach((tab) =>
    tab.addEventListener("click", () => showTab(tab.dataset.tab))
  );
  $("#user").addEventListener("change", (e) => selectUser(e.target.value));
  $("#chatUser").addEventListener("change", (e) => selectUser(e.target.value));
  $("#mutual").addEventListener("change", run);
  $("#useLlm").addEventListener("change", run);
  $("#dbText").addEventListener("input", scheduleSave);
  $("#reset").addEventListener("click", async () => {
    if (!confirm("등록한 프로필·설정·채팅을 지우고 가상 프로필 20명으로 되돌릴까요?\n(지우기 전에 data/backups 폴더에 자동으로 백업해요)")) return;
    const res = await api("/api/reset", { method: "POST" });
    await loadProfiles(1);
    loadDataStatus();
    toast(`되돌렸어요. 백업: ${res.backups.join(", ") || "없음"}`);
  });

  setupBuilder();
  setupBonus();
  setupSuggest();
  renderSignup();
  await loadProfiles(lastUserId());
  loadDataStatus();
}

// ── 자동 저장 · 데이터 상태 ─────────────────────────────
let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  $("#saveStatus").textContent = "저장 중…";
  saveTimer = setTimeout(savePreferences, 600);
}

async function savePreferences() {
  try {
    const updated = await api(`/api/profiles/${me.id}/preferences`, { method: "PUT", body: JSON.stringify(currentPreferences()) });
    profiles = profiles.map((p) => (p.id === updated.id ? updated : p));
    me = updated;
    $("#saveStatus").textContent = "✓ 자동 저장됨";
  } catch (e) {
    $("#saveStatus").textContent = "저장 실패: " + e.message;
  }
}

async function loadDataStatus() {
  const s = await api("/api/data-status");
  $("#dataStatus").textContent = `저장 위치: ${s.data_dir} · 백업 ${s.backups}개`;
  if (s.repair_notes.length) toast(`예전 데이터 ${s.repair_notes.length}건을 새 형식에 맞게 정리했어요 (원본은 백업됨)`);
}

// 이 브라우저에서 마지막으로 고른 사용자를 기억 (없거나 막혀 있으면 1번)
function lastUserId() {
  try {
    return Number(localStorage.getItem("matchUserId")) || undefined;
  } catch {
    return undefined;
  }
}
function rememberUser(id) {
  try {
    localStorage.setItem("matchUserId", String(id));
  } catch {}
}

init();
