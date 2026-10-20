/*
 * 웹 버전(GitHub Pages)용 "브라우저 안의 서버".
 *
 * GitHub Pages는 Python 서버를 돌릴 수 없어서, matcher/ 의 매칭 엔진을 그대로 JavaScript로 옮겨
 * 화면(app.js)이 부르는 /api/... 요청을 브라우저 안에서 처리한다.
 *   - 결과는 Python 버전과 같다 (같은 규칙·같은 해시·같은 난수를 쓴다).
 *   - 데이터는 이 브라우저(localStorage)에 저장된다. 방문자마다 자기 데이터가 따로 생긴다.
 *   - 선택지·점수 항목 같은 설정은 scripts/build_pages.py가 Python 설정에서 web-data.json으로 뽑아 준다.
 *
 * Python 쪽 로직을 바꾸면 이 파일도 같이 바꾸고, scripts/build_pages.py로 docs/를 다시 만든다.
 */
(() => {
  const BASE = document.currentScript.src.replace(/static\/local-api\.js.*$/, "");
  const KEY = { profiles: "dm.profiles", social: "dm.social", backup: "dm.backup", photo: (id) => `dm.photo.${id}` };
  let CFG = null;
  let SAMPLE = null;
  let profiles = [];
  let social = { likes: [], messages: {} };

  // ── 작은 도구 ───────────────────────────────────────────
  const g = (n) => String(parseFloat(Number(n).toPrecision(6))); // Python의 {:g}
  const signedInt = (n) => (n >= 0 ? `+${n}` : `${n}`); // Python의 {:+d}
  const signedG = (n) => (n >= 0 ? `+${g(n)}` : g(n)); // Python의 {:+g}
  const pct = (x) => `${Math.round(x * 100)}%`; // Python의 {:.0%}
  const round = (x, d) => Math.round(x * 10 ** d) / 10 ** d;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const sum = (arr) => arr.reduce((a, b) => a + b, 0);
  const fail = (msg) => {
    throw new Error(msg);
  };
  const nowIso = () => {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };

  // ── 저장 (localStorage, 막혀 있으면 메모리에서만 동작) ─────
  function load(key) {
    try {
      const v = localStorage.getItem(key);
      return v ? JSON.parse(v) : null;
    } catch {
      return null;
    }
  }
  // 사진(data URL)은 JSON이 아니라 문자열 그대로 저장한다.
  function loadRaw(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function save(key, value) {
    try {
      localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value));
    } catch (e) {
      if (e && e.name === "QuotaExceededError") fail("브라우저 저장 공간이 가득 찼어요. 데이터를 백업 파일로 받은 뒤 사진을 줄여 주세요.");
    }
  }
  function remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {}
  }
  const saveProfiles = () => save(KEY.profiles, profiles);
  const saveSocial = () => save(KEY.social, social);
  const getProfile = (id) => profiles.find((p) => p.id === Number(id)) || null;
  const displayName = (p) => p.nickname || p.name;

  // ── 프로필 기본값 · 예전 데이터 정리 ─────────────────────
  const PROFILE_DEFAULTS = {
    nickname: null, district: null, height: null, company: null, verified: false, smoking: null, drinking: null,
    religion: null, exercise: null, mbti: null, interests: [], contact_frequency: null, date_style: null,
    relationship_goal: null, photo: null, bio: "", prompts: {},
  };
  const PREF_DEFAULTS = () => ({ target_genders: [], dealbreakers: [], dealbreaker_text: "", weights: {}, bonus_rules: [], blocked_ids: [] });

  function normalizeProfile(p) {
    const out = { ...PROFILE_DEFAULTS, ...p };
    out.preferences = { ...PREF_DEFAULTS(), ...(p.preferences || {}) };
    const prefs = out.preferences;
    // 코드가 바뀌어 없어진 항목·값은 정리 (Python store.repair 와 같은 원칙: 프로필 자체는 지키고 맞지 않는 값만 뺀다)
    prefs.weights = Object.fromEntries(Object.entries(prefs.weights).filter(([k, v]) => k in CFG.SCORE_CATEGORIES && Number.isFinite(v)));
    prefs.dealbreakers = prefs.dealbreakers.filter((d) => safe(() => validateDealbreaker(d)));
    prefs.bonus_rules = prefs.bonus_rules.filter((r) => safe(() => validateBonus(r)));
    out.interests = (out.interests || []).filter((t) => CFG.INTERESTS.includes(t)).slice(0, CFG.MAX_INTERESTS);
    return out;
  }
  function safe(fn) {
    try {
      fn();
      return true;
    } catch {
      return false;
    }
  }

  // ── 설명 문장 (Python models.describe 와 같음) ─────────────
  function dbDescribe(d) {
    const label = CFG.DEALBREAKER_FIELDS[d.field][0];
    if (d.op === "min") return `${label} ${d.value} 이상`;
    if (d.op === "max") return `${label} ${d.value} 이하`;
    const values = d.value.join(", ");
    if (d.field === "interests") return d.op === "require" ? `관심사에 ${values} 중 하나 이상 필수` : `관심사에 ${values} 있으면 제외`;
    return d.op === "require" ? `${label}: ${values}만 허용` : `${label}: ${values} 제외`;
  }
  function bonusDescribe(r) {
    const label = CFG.BONUS_FIELDS[r.field][0];
    let cond;
    if (r.op === "min") cond = `${label} ${r.value} 이상`;
    else if (r.op === "max") cond = `${label} ${r.value} 이하`;
    else if (r.field === "interests") cond = `관심사에 ${r.value.join(", ")}`;
    else cond = `${label} ${r.value.join(", ")}`;
    return `${cond} → ${signedInt(r.points)}점`;
  }

  // ── 입력값 검사 (Python pydantic 검증의 핵심만) ─────────────
  function validateDealbreaker(d) {
    if (!(d.field in CFG.DEALBREAKER_FIELDS)) fail(`절대조건으로 쓸 수 없는 항목입니다: ${d.field}`);
    if (!CFG.DEALBREAKER_FIELDS[d.field][1].includes(d.op)) fail(`'${d.field}'에 쓸 수 없는 조건입니다.`);
    if (d.op === "require" || d.op === "exclude") {
      if (typeof d.value === "string") d.value = [d.value];
      if (!Array.isArray(d.value) || !d.value.length) fail("값을 하나 이상 골라 주세요.");
      const bad = d.value.filter((v) => !CFG.DEALBREAKER_CHOICES[d.field].includes(v));
      if (bad.length) fail(`'${d.field}'에 없는 값입니다: ${bad}`);
    } else if (d.field === "education") {
      if (!CFG.EDUCATION.includes(d.value)) fail("학력 값이 올바르지 않습니다.");
    } else if (!Number.isInteger(d.value)) fail("이상/이하 조건에는 숫자가 필요합니다.");
    return { field: d.field, op: d.op, value: d.value };
  }
  function validateBonus(r) {
    if (!(r.field in CFG.BONUS_FIELDS)) fail(`추가 점수에 쓸 수 없는 항목입니다: ${r.field}`);
    if (!CFG.BONUS_FIELDS[r.field][1].includes(r.op)) fail(`'${r.field}'에 쓸 수 없는 조건입니다.`);
    if (!CFG.BONUS_POINTS.includes(Math.abs(r.points))) fail(`추가 점수·감점은 ±${CFG.BONUS_POINTS} 중 하나여야 합니다.`);
    if (r.op === "in") {
      if (typeof r.value === "string") r.value = [r.value];
      if (!Array.isArray(r.value) || !r.value.length) fail("값을 하나 이상 골라 주세요.");
      const bad = r.value.filter((v) => !CFG.DEALBREAKER_CHOICES[r.field].includes(v));
      if (bad.length) fail(`'${r.field}'에 없는 값입니다: ${bad}`);
    } else if (r.field === "education") {
      if (!CFG.EDUCATION.includes(r.value)) fail("학력 값이 올바르지 않습니다.");
    } else if (!Number.isInteger(r.value)) fail("이상/이하 조건에는 숫자가 필요합니다.");
    return { field: r.field, op: r.op, value: r.value, points: r.points };
  }
  function validatePreferences(p) {
    const prefs = { ...PREF_DEFAULTS(), ...(p || {}) };
    for (const [k, w] of Object.entries(prefs.weights)) {
      if (!(k in CFG.SCORE_CATEGORIES)) fail(`알 수 없는 점수 항목입니다: ${k}`);
      if (!(w >= 0 && w <= CFG.MAX_WEIGHT)) fail(`중요도는 0~${CFG.MAX_WEIGHT} 사이여야 합니다.`);
    }
    prefs.dealbreakers = prefs.dealbreakers.map(validateDealbreaker);
    prefs.bonus_rules = prefs.bonus_rules.map(validateBonus);
    if (prefs.bonus_rules.length > CFG.MAX_BONUS_RULES) fail(`추가 점수·감점 규칙은 ${CFG.MAX_BONUS_RULES}개까지예요.`);
    if ((prefs.dealbreaker_text || "").length > 500) fail("문장은 500자까지 적을 수 있어요.");
    return prefs;
  }
  function validateNewProfile(b) {
    const errors = [];
    const need = (k, label) => {
      if (b[k] === undefined || b[k] === null || String(b[k]).trim() === "") errors.push(`• ${label}: 필수 항목이에요`);
    };
    need("name", "이름");
    need("gender", "성별");
    need("education", "최종학력");
    need("occupation", "직업");
    need("age", "나이");
    need("city", "시·도");
    if (b.gender && !CFG.GENDERS.includes(b.gender)) errors.push("• 성별: 올바르지 않은 값");
    if (b.education && !CFG.EDUCATION.includes(b.education)) errors.push("• 최종학력: 올바르지 않은 값");
    if (b.age !== undefined && !(Number.isInteger(b.age) && b.age >= 19 && b.age <= 80)) errors.push("• 나이: 19~80 사이 숫자");
    if (b.city && !(b.city in CFG.REGIONS)) errors.push("• 시·도: 올바르지 않은 값");
    if (b.district && b.city in CFG.REGIONS && !CFG.REGIONS[b.city].includes(b.district)) errors.push("• 구/시: 시·도에 없는 값");
    if (b.height !== undefined && b.height !== null && !(b.height >= 130 && b.height <= 220)) errors.push("• 키: 130~220");
    if (b.mbti && !/^[EI][NS][TF][JP]$/i.test(b.mbti)) errors.push("• MBTI: 형식이 올바르지 않습니다 (예: ENFP)");
    if ((b.interests || []).length > CFG.MAX_INTERESTS) errors.push(`• 관심사: 최대 ${CFG.MAX_INTERESTS}개`);
    if (errors.length) fail(errors.join("\n"));
    return normalizeProfile({
      ...b,
      name: String(b.name).trim(),
      occupation: String(b.occupation).trim(),
      mbti: b.mbti ? b.mbti.toUpperCase() : null,
      preferences: validatePreferences(b.preferences),
    });
  }

  // ── ① 거르기 (filters.py) ──────────────────────────────────
  function checkDealbreaker(rule, other) {
    const label = CFG.DEALBREAKER_FIELDS[rule.field][0];
    const value = other[rule.field] ?? null;
    if (rule.field === "interests") {
      const hit = [...new Set(value || [])].filter((v) => rule.value.includes(v)).sort();
      if (rule.op === "exclude") return hit.length ? `관심사에 ${hit.join(", ")} 있음 (조건: ${dbDescribe(rule)})` : null;
      return hit.length ? null : `관심사에 ${rule.value.join(", ")} 없음 (조건: ${dbDescribe(rule)})`;
    }
    if (value === null) return `${label} 정보 미입력 (조건: ${dbDescribe(rule)})`;
    let ok;
    if (rule.op === "min" || rule.op === "max") {
      if (rule.field === "education") {
        const a = CFG.EDUCATION.indexOf(value);
        const b = CFG.EDUCATION.indexOf(rule.value);
        ok = rule.op === "min" ? a >= b : a <= b;
      } else ok = rule.op === "min" ? value >= rule.value : value <= rule.value;
    } else if (rule.op === "require") ok = rule.value.includes(value);
    else ok = !rule.value.includes(value);
    return ok ? null : `${label} '${value}' (조건: ${dbDescribe(rule)})`;
  }
  const oneWay = (viewer, other) => viewer.preferences.dealbreakers.map((r) => checkDealbreaker(r, other)).filter(Boolean);
  function filterCheck(me, other) {
    if (me.id === other.id) return { passed: false, reasons: ["본인"], outOfScope: true };
    const scope = [];
    const mt = me.preferences.target_genders;
    const ot = other.preferences.target_genders;
    if (mt.length && !mt.includes(other.gender)) scope.push("내가 원하는 성별이 아님");
    if (ot.length && !ot.includes(me.gender)) scope.push("상대가 원하는 성별이 아님");
    if (me.preferences.blocked_ids.includes(other.id) || other.preferences.blocked_ids.includes(me.id)) scope.push("차단한/차단된 사용자");
    if (scope.length) return { passed: false, reasons: scope, outOfScope: true };
    const reasons = [
      ...oneWay(me, other).map((r) => `[내 조건] ${r}`),
      ...oneWay(other, me).map((r) => `[상대 조건] 내가 상대의 조건에 맞지 않음 — ${r}`),
    ];
    return { passed: !reasons.length, reasons, outOfScope: false };
  }

  // ── 임베딩 (embedding.py: 글자 2~3개 조각 해싱) ─────────────
  const encoder = new TextEncoder();
  function fnv1a(text) {
    let h = 0x811c9dc5;
    for (const b of encoder.encode(text)) {
      h ^= b;
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h >>> 0;
  }
  const ALNUM = /[\p{L}\p{N}]/u;
  function embedText(text) {
    const grams = new Map();
    for (const raw of text.toLowerCase().split(/\s+/)) {
      const word = [...raw].filter((ch) => ALNUM.test(ch)).join("");
      if (!word) continue;
      const padded = [...`<${word}>`];
      for (const n of [2, 3]) {
        for (let i = 0; i <= padded.length - n; i++) {
          const gram = padded.slice(i, i + n).join("");
          grams.set(gram, (grams.get(gram) || 0) + 1);
        }
      }
    }
    const vec = new Float64Array(2048);
    for (const [gram, count] of grams) vec[fnv1a(gram) % 2048] += 1 + Math.log(count);
    const norm = Math.sqrt(vec.reduce((a, x) => a + x * x, 0));
    if (norm) for (let i = 0; i < vec.length; i++) vec[i] /= norm;
    return vec;
  }
  const embedCache = new Map();
  function embed(text) {
    if (!embedCache.has(text)) embedCache.set(text, embedText(text));
    return embedCache.get(text);
  }
  function cosine(a, b) {
    let s = 0;
    for (let i = 0; i < a.length; i++) s += a[i] * b[i];
    return s;
  }

  // ── 항목별 겹침 (similarity.py) ───────────────────────────
  function overlap(a, b) {
    const common = [...new Set(a)].filter((x) => b.includes(x));
    if (!common.length) return [0, "겹치는 관심사 없음"];
    return [common.length, `${common.length}개 겹침 (${common.join(", ")})`];
  }
  const exact = (a, b) => (a === b ? [1, `둘 다 '${a}'`] : [0, `'${a}' vs '${b}'`]);
  function region(ca, da, cb, db) {
    if (ca !== cb) return [0, `${ca} vs ${cb}`];
    if (da && da === db) return [1, `같은 동네 (${ca} ${da})`];
    return [1, `둘 다 ${ca}`];
  }
  function ageGap(a, b) {
    const gap = Math.abs(a - b);
    const label = gap === 0 ? "동갑" : `${gap}살 차이`;
    return gap <= CFG.AGE_MATCH_YEARS ? [1, label] : [0, `${label} (${CFG.AGE_MATCH_YEARS}살 초과)`];
  }
  function textMatch(sim) {
    sim = Math.max(0, Math.min(1, sim));
    const th = CFG.BIO_MATCH_THRESHOLD;
    return sim >= th ? [1, `자기소개 유사도 ${pct(sim)} (기준 ${pct(th)} 이상)`] : [0, `자기소개 유사도 ${pct(sim)} (기준 ${pct(th)} 미만)`];
  }

  // ── ③ 점수 (scoring.py · bonus.py) ─────────────────────────
  const effectiveWeights = (prefs) =>
    Object.fromEntries(Object.keys(CFG.SCORE_CATEGORIES).map((k) => [k, prefs.weights[k] ?? CFG.DEFAULT_WEIGHT]));
  const bioText = (p) => `${p.bio} ${Object.values(p.prompts).join(" ")}`.trim();

  function matches(me, other) {
    const result = {};
    const skipped = [];
    for (const [key, [label, kind]] of Object.entries(CFG.SCORE_CATEGORIES)) {
      if (kind === "count") {
        if (!me.interests.length || !other.interests.length) {
          skipped.push(label);
          continue;
        }
        result[key] = overlap(me.interests, other.interests);
      } else if (kind === "text") {
        const a = bioText(me);
        const b = bioText(other);
        if (!a || !b) {
          skipped.push(label);
          continue;
        }
        result[key] = textMatch(cosine(embed(a), embed(b)));
      } else if (kind === "region") result[key] = region(me.city, me.district, other.city, other.district);
      else if (kind === "age") result[key] = ageGap(me.age, other.age);
      else {
        const a = me[key] ?? null;
        const b = other[key] ?? null;
        if (a === null || b === null) {
          skipped.push(label);
          continue;
        }
        result[key] = exact(a, b);
      }
    }
    return [result, skipped];
  }

  function bonusCheck(rule, other) {
    const value = other[rule.field] ?? null;
    if (value === null || (Array.isArray(value) && !value.length)) return null;
    const label = CFG.BONUS_FIELDS[rule.field][0];
    if (rule.field === "interests") {
      const hit = rule.value.filter((t) => value.includes(t));
      return hit.length ? `관심사에 ${hit.join(", ")} 있음` : null;
    }
    if (rule.op === "in") return rule.value.includes(value) ? `${label} '${value}'` : null;
    let ok;
    if (rule.field === "education") ok = CFG.EDUCATION.indexOf(value) >= CFG.EDUCATION.indexOf(rule.value);
    else ok = rule.op === "min" ? value >= rule.value : value <= rule.value;
    return ok ? `${label} ${value}` : null;
  }

  function score(me, other, mutual = false, myWeights = null) {
    const myW = myWeights || effectiveWeights(me.preferences);
    const theirW = effectiveWeights(other.preferences);
    const [found, skipped] = matches(me, other);
    const categories = [];
    for (const [key, [n, detail]] of Object.entries(found)) {
      const mine = myW[key] * n;
      const theirs = theirW[key] * n;
      categories.push({
        key, label: CFG.SCORE_CATEGORIES[key][0], matches: n, detail, weight: myW[key], points: mine,
        contribution: mutual ? (mine + theirs) / 2 : mine, their_weight: theirW[key], their_points: theirs,
      });
    }
    me.preferences.bonus_rules.forEach((rule, i) => {
      const reason = bonusCheck(rule, other);
      if (reason)
        categories.push({
          key: `bonus:${i}`, label: rule.points < 0 ? "감점" : "추가 점수", matches: 1, detail: `${reason} (${bonusDescribe(rule)})`,
          weight: rule.points, points: rule.points, contribution: mutual ? rule.points / 2 : rule.points, their_weight: 0, their_points: 0,
        });
    });
    if (mutual)
      other.preferences.bonus_rules.forEach((rule, i) => {
        const reason = bonusCheck(rule, me);
        if (reason)
          categories.push({
            key: `their_bonus:${i}`, label: rule.points < 0 ? "상대의 감점" : "상대의 추가 점수", matches: 1,
            detail: `상대 기준: 나의 ${reason} (${bonusDescribe(rule)})`, weight: 0, points: 0, contribution: rule.points / 2,
            their_weight: rule.points, their_points: rule.points,
          });
      });
    const myScore = sum(categories.map((c) => c.points));
    const theirScore = sum(categories.map((c) => c.their_points));
    return { total: mutual ? (myScore + theirScore) / 2 : myScore, my_score: myScore, their_score: theirScore, categories, skipped };
  }

  // ── ④ 설명 (explain.py) ────────────────────────────────────
  const byDesc = (f) => (a, b) => f(b) - f(a);
  function highlights(s, limit = 3) {
    return s.categories
      .filter((c) => c.matches && c.contribution > 0)
      .sort(byDesc((c) => c.contribution))
      .slice(0, limit)
      .map((c) => `${c.label}: ${c.detail} (+${g(c.points)}점)`);
  }
  function weakPoints(s, limit = 2) {
    const penalties = s.categories.filter((c) => c.points < 0).map((c) => `감점: ${c.detail} (${g(c.points)}점)`);
    const bad = s.categories.filter((c) => !c.matches && c.weight >= CFG.DEFAULT_WEIGHT).sort(byDesc((c) => c.weight));
    return [...penalties, ...bad.slice(0, Math.max(0, limit - penalties.length)).map((c) => `${c.label}: ${c.detail}`)];
  }
  function compare(first, second) {
    const a = Object.fromEntries(first.categories.map((c) => [c.key, c]));
    const b = Object.fromEntries(second.categories.map((c) => [c.key, c]));
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
    const items = keys.map((key) => {
      const ca = a[key];
      const cb = b[key];
      const diff = (ca ? ca.contribution : 0) - (cb ? cb.contribution : 0);
      const weight = (ca || cb).weight;
      const isBonus = key.includes("bonus:");
      let note = "";
      if (isBonus) note = "";
      else if (diff > 0 && weight > CFG.DEFAULT_WEIGHT)
        note = `회원님이 ${weight}점(기본 ${CFG.DEFAULT_WEIGHT}점)으로 중요하게 설정해서 차이가 ${g(weight / CFG.DEFAULT_WEIGHT)}배로 커졌어요`;
      else if (diff < 0 && weight < CFG.DEFAULT_WEIGHT) note = `회원님 설정이 ${weight}점이라 영향이 작았어요`;
      return {
        key, label: (ca || cb).label, diff: round(diff, 1),
        first: ca ? ca.detail : isBonus ? "해당 없음" : "정보 없음",
        second: cb ? cb.detail : isBonus ? "해당 없음" : "정보 없음",
        note,
      };
    });
    items.sort(byDesc((x) => x.diff));
    return {
      gap: round(first.total - second.total, 1),
      ahead: items.filter((i) => i.diff > 0.05).slice(0, 3),
      behind: [...items].reverse().filter((i) => i.diff < -0.05).slice(0, 2),
    };
  }
  function whyFirst(firstName, first, secondName, second) {
    if (!second) return [`거르기를 통과한 사람이 ${firstName}님 한 명뿐이라 1위가 되었어요.`];
    const cmp = compare(first, second);
    const lines =
      cmp.gap === 0
        ? [`${firstName}님과 2위 ${secondName}님이 ${g(first.total)}점 동점이라, 인증 회원 → 나이 차이가 적은 순으로 1위가 됐어요.`]
        : [`${firstName}님 ${g(first.total)}점 vs 2위 ${secondName}님 ${g(second.total)}점 → ${g(cmp.gap)}점 차이로 1위예요.`];
    if (cmp.ahead.length) {
      lines.push("1위가 앞선 항목:");
      for (const i of cmp.ahead) lines.push(`  · ${i.label} +${g(i.diff)}점 — 1위 [${i.first}] / 2위 [${i.second}]${i.note ? ` ← ${i.note}` : ""}`);
    }
    if (cmp.behind.length) {
      lines.push("2위가 앞선 항목 (그래도 1위를 뒤집지는 못했어요):");
      for (const i of cmp.behind) lines.push(`  · ${i.label} ${g(i.diff)}점 — 1위 [${i.first}] / 2위 [${i.second}]${i.note ? ` ← ${i.note}` : ""}`);
    }
    return lines;
  }
  function scoreFormula(s) {
    const parts = s.categories
      .filter((c) => c.points && c.matches)
      .map((c) => (c.key.includes("bonus:") ? `${c.label} ${signedG(c.points)}` : `${c.label} ${c.weight}×${c.matches}`));
    return `${parts.join(" + ").replaceAll("+ -", "- ") || "겹치는 항목 없음"} = ${g(s.my_score)}점`;
  }

  // ── ② 후보 추리기 (retrieve.py) ───────────────────────────
  function profileText(p) {
    const parts = [p.bio, Object.values(p.prompts).join(" "), p.interests.join(" ")];
    if (p.date_style) parts.push(p.date_style);
    if (p.relationship_goal) parts.push(p.relationship_goal);
    return parts.filter(Boolean).join(" ").trim() || p.occupation;
  }
  function retrieve(me, pool, topK) {
    const mine = embed(profileText(me));
    const sims = Object.fromEntries(pool.map((p) => [p.id, cosine(mine, embed(profileText(p)))]));
    if (pool.length <= topK) return [pool, sims, false];
    return [[...pool].sort(byDesc((p) => sims[p.id])).slice(0, topK), sims, true];
  }

  // ── 추천 파이프라인 (pipeline.py) ─────────────────────────
  const brief = (p) => ({
    id: p.id, name: displayName(p), gender: p.gender, age: p.age, region: `${p.city} ${p.district || ""}`.trim(),
    occupation: p.occupation, education: p.education, verified: p.verified, interests: p.interests, bio: p.bio,
    mbti: p.mbti, photo: p.photo,
  });
  function rank(me, candidates, mutual, weights) {
    const scored = candidates.map((p) => [p, score(me, p, mutual, weights)]);
    scored.sort(
      (x, y) =>
        -round(x[1].total, 6) - -round(y[1].total, 6) ||
        Number(!x[0].verified) - Number(!y[0].verified) ||
        Math.abs(x[0].age - me.age) - Math.abs(y[0].age - me.age)
    );
    return scored;
  }

  function recommend(me, everyone, preferences, mutual = false, topN = CFG.DEFAULT_TOP_N, topK = CFG.CANDIDATE_TOP_K) {
    if (preferences) me = { ...me, preferences };
    const weights = effectiveWeights(me.preferences);
    const trace = [];

    const passed = [];
    const eliminated = [];
    let outOfScope = 0;
    const reasonCounter = new Map();
    for (const other of everyone) {
      const r = filterCheck(me, other);
      if (r.passed) passed.push(other);
      else if (r.outOfScope) outOfScope += other.id !== me.id ? 1 : 0;
      else {
        eliminated.push([other, r.reasons]);
        for (const reason of r.reasons) {
          const k = reason.split(" '")[0].split(" 정보")[0];
          reasonCounter.set(k, (reasonCounter.get(k) || 0) + 1);
        }
      }
    }
    const totalOthers = everyone.length - 1;
    trace.push(`① 거르기: 전체 ${totalOthers}명 중 대상 아님(성별·차단) ${outOfScope}명, 절대조건 탈락 ${eliminated.length}명 → ${passed.length}명 통과`);
    if (me.preferences.dealbreakers.length) trace.push("   내 절대조건: " + me.preferences.dealbreakers.map(dbDescribe).join(" / "));

    const eliminatedView = eliminated
      .map(([other, reasons]) => ({ ...brief(other), would_be_score: round(score(me, other, mutual, weights).total, 1), reasons }))
      .sort(byDesc((x) => x.would_be_score));

    const [candidates, embSims, used] = passed.length ? retrieve(me, passed, topK) : [[], {}, false];
    trace.push(
      used
        ? `② 후보 추리기: ${passed.length}명 중 프로필 글이 가장 비슷한 ${candidates.length}명만 정밀 채점 (임베딩)`
        : `② 후보 추리기: ${passed.length}명 ≤ ${topK}명이라 생략하고 전원 정밀 채점`
    );

    const scored = rank(me, candidates, mutual, weights);
    const changed = Object.entries(weights).filter(([, v]) => v !== CFG.DEFAULT_WEIGHT);
    const weightTxt = changed.map(([k, v]) => `${CFG.SCORE_CATEGORIES[k][0]} ${v}점`).join(", ") || "모두 보통";
    trace.push(`③ 점수: 겹치는 항목마다 중요도만큼 더하기, 관심사는 겹친 개수 × 중요도 (변경: ${weightTxt})`);
    const plus = me.preferences.bonus_rules.filter((r) => r.points > 0).map(bonusDescribe);
    const minus = me.preferences.bonus_rules.filter((r) => r.points < 0).map(bonusDescribe);
    if (plus.length) trace.push("   추가 점수: " + plus.join(" / "));
    if (minus.length) trace.push("   감점: " + minus.join(" / "));
    if (mutual) trace.push("   쌍방 모드: (내 기준 점수 + 상대 기준 점수) ÷ 2");

    const defaultWeights = Object.fromEntries(Object.keys(CFG.SCORE_CATEGORIES).map((k) => [k, CFG.DEFAULT_WEIGHT]));
    const baseline = changed.length ? rank(me, candidates, mutual, defaultWeights) : scored;
    const baselineRank = Object.fromEntries(baseline.map(([p], i) => [p.id, i + 1]));

    const ranking = scored.slice(0, topN).map(([p, s], idx) => {
      const isRule = (c) => c.key.includes("bonus:");
      const bonusPart = sum(s.categories.filter((c) => isRule(c) && c.contribution > 0).map((c) => c.contribution));
      const penaltyPart = sum(s.categories.filter((c) => isRule(c) && c.contribution < 0).map((c) => c.contribution));
      return {
        ...brief(p),
        rank: idx + 1,
        score: round(s.total, 1),
        base_score: round(s.total - bonusPart - penaltyPart, 1),
        bonus_score: round(bonusPart, 1),
        penalty_score: round(penaltyPart, 1),
        bonus_checks: me.preferences.bonus_rules.map((r) => {
          const reason = bonusCheck(r, p);
          return { text: bonusDescribe(r), points: r.points, hit: reason !== null, reason: reason || "해당 없음" };
        }),
        my_score: round(s.my_score, 1),
        their_score: round(s.their_score, 1),
        rank_with_default_weights: baselineRank[p.id],
        profile_similarity: round(embSims[p.id] || 0, 3),
        formula: scoreFormula(s),
        breakdown: [...s.categories].sort(byDesc((c) => c.contribution)).map((c) => ({
          key: c.key, label: c.label,
          logic: c.key in CFG.SCORE_CATEGORIES ? CFG.SCORE_CATEGORIES[c.key][2] : "해당하면 ±점수",
          weight: c.weight, matches: c.matches, points: round(c.points, 2), contribution: round(c.contribution, 2),
          their_weight: c.their_weight, detail: c.detail,
        })),
        skipped: s.skipped,
        highlights: highlights(s),
        weak_points: weakPoints(s),
        llm_summary: null,
      };
    });

    let why = [];
    let whyDetail = null;
    if (scored.length) {
      const [firstP, firstS] = scored[0];
      const [secondP, secondS] = scored[1] || [null, null];
      why = whyFirst(displayName(firstP), firstS, secondP && displayName(secondP), secondS);
      whyDetail = {
        first: { name: displayName(firstP), score: round(firstS.total, 1) },
        second: secondP ? { name: displayName(secondP), score: round(secondS.total, 1) } : null,
        ...(secondS ? compare(firstS, secondS) : { gap: null, ahead: [], behind: [] }),
        weight_note: null,
      };
      if (changed.length) {
        const baseFirst = baseline[0][0];
        const note =
          baseFirst.id === firstP.id
            ? `중요도를 모두 보통(${CFG.DEFAULT_WEIGHT}점)으로 둬도 1위는 같아요.`
            : `중요도를 모두 보통(${CFG.DEFAULT_WEIGHT}점)으로 뒀다면 1위는 ${displayName(baseFirst)}님이었어요. 회원님이 바꾼 중요도(${weightTxt}) 때문에 순위가 바뀌었어요.`;
        why.push(note);
        whyDetail.weight_note = note;
      }
      trace.push(`④ 설명: 1위 ${displayName(firstP)}님 (${g(firstS.total)}점)`);
    } else trace.push("④ 결과: 조건을 모두 통과한 사람이 없어요. 절대조건을 조금 완화해 보세요.");

    return {
      me: brief(me),
      settings: {
        mutual, weights,
        dealbreakers: me.preferences.dealbreakers.map((d) => ({ ...d, text: dbDescribe(d) })),
        top_k: topK, top_n: topN,
      },
      funnel: {
        total: totalOthers, out_of_scope: outOfScope, eliminated: eliminated.length, passed_filter: passed.length,
        candidates: candidates.length, retrieval_used: used,
        eliminated_reasons: Object.fromEntries([...reasonCounter].sort((a, b) => b[1] - a[1])),
      },
      trace, why_first: why, why_detail: whyDetail, ranking, eliminated: eliminatedView,
    };
  }

  // ── 문장 → 거르기 조건 (textrules.py) ─────────────────────
  function parseRules(text) {
    const T = CFG.TEXTRULES;
    const rules = [];
    const unmatched = [];
    const has = (s, words) => words.some((w) => (s.toLowerCase() + " ").includes(w));
    const add = (field, op, value, source) => {
      const r = rules.find((x) => x.field === field && x.op === op);
      if (r) {
        if (Array.isArray(value)) {
          const order = CFG.DEALBREAKER_CHOICES[field];
          r.value = [...new Set([...r.value, ...value])].sort((a, b) => order.indexOf(a) - order.indexOf(b));
        } else r.value = value;
        return;
      }
      rules.push({ field, op, value, source });
    };
    const size = () => [rules.length, sum(rules.map((r) => (Array.isArray(r.value) ? r.value.length : 1)))].join(",");
    const sentences = text.split(/[.\n!?;,]|그리고|그리구/).map((s) => s.trim()).filter(Boolean);
    for (const s of sentences) {
      const before = size();
      const negative = has(s, T.NEGATIVE);
      const require = has(s, T.REQUIRE);
      if (s.includes("비흡연") || (/(담배|흡연)/.test(s) && (negative || /안\s?(피|펴)/.test(s)))) add("smoking", "require", ["비흡연"], s);
      if (s.includes("술") || s.includes("음주")) {
        if (/(안|못)\s?마시/.test(s) && require) add("drinking", "require", ["안 마심"], s);
        else if (/(자주|많이|매일|좋아하는|즐기는)/.test(s) && negative) add("drinking", "exclude", ["자주"], s);
        else if (negative) add("drinking", "require", ["안 마심"], s);
      }
      for (const [word, religion] of Object.entries(T.RELIGION_WORDS)) {
        if (s.includes(word)) {
          if (negative) add("religion", "exclude", [religion], s);
          else if (require) add("religion", "require", [religion], s);
        }
      }
      const tags = CFG.INTERESTS.filter((t) => s.includes(t));
      if (tags.length) {
        if (negative) add("interests", "exclude", tags, s);
        else if (require) add("interests", "require", tags, s);
      }
      const m = /(\d{2})\s?[~\-]\s?(\d{2})\s?(살|세)/.exec(s);
      if (m) {
        add("age", "min", Number(m[1]), s);
        add("age", "max", Number(m[2]), s);
      } else {
        for (const [, num, , dir] of s.matchAll(/(\d{2})\s?(살|세)\s?(이상|이하|넘|미만|까지|부터)/g))
          add("age", dir === "이상" || dir === "부터" ? "min" : "max", Number(num), s);
      }
      for (const [, num, dir] of s.matchAll(/키\D{0,4}(\d{3})\s?(?:cm)?\s?(이상|이하)/g)) add("height", dir === "이상" ? "min" : "max", Number(num), s);
      if (size() === before) unmatched.push(s);
    }
    for (const r of rules) r.text = dbDescribe(r);
    return { rules, unmatched };
  }

  // ── 좋아요 · 매칭 · 채팅 (social.py) ──────────────────────
  const pairKey = (a, b) => `${Math.min(a, b)}-${Math.max(a, b)}`;
  const findLike = (from, to) => social.likes.find((l) => l.from === from && l.to === to) || null;
  const isMatch = (a, b) => !!findLike(a, b) && !!findLike(b, a);
  function addMessage(from, to, text, at) {
    const msg = { from, to, text, at: at || nowIso(), read: false };
    (social.messages[pairKey(from, to)] ||= []).push(msg);
    return msg;
  }
  function like(from, to, message) {
    if (from === to) fail("자기 자신에게는 좋아요를 보낼 수 없어요.");
    message = (message || "").trim().slice(0, 500);
    if (findLike(from, to)) fail("이미 좋아요를 보냈어요.");
    social.likes.push({ from, to, message, at: nowIso() });
    const matched = isMatch(from, to);
    if (matched)
      [findLike(to, from), findLike(from, to)]
        .sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))
        .forEach((l) => l.message && addMessage(l.from, l.to, l.message, l.at));
    saveSocial();
    return { matched };
  }
  const unreadCount = (viewer, other) => (social.messages[pairKey(viewer, other)] || []).filter((m) => m.to === viewer && !m.read).length;
  const lastMessage = (a, b) => {
    const msgs = social.messages[pairKey(a, b)] || [];
    return msgs.length ? msgs[msgs.length - 1] : null;
  };
  const card = (p) => ({ id: p.id, name: displayName(p), age: p.age, region: `${p.city} ${p.district || ""}`.trim(), occupation: p.occupation, photo: p.photo });

  // ── 캐릭터 프로필 사진 (avatar.py 와 같은 그림) ─────────────
  function mulberry(seed) {
    let a = fnv1a(seed);
    const random = () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    return { random, choice: (items) => items[Math.floor(random() * items.length)] };
  }
  function hairBack(style, c) {
    if (style === "long") return `<path d="M24 58 Q22 22 60 20 Q98 22 96 58 L100 112 Q60 122 20 112 Z" fill="${c}"/>`;
    if (style === "bob") return `<path d="M26 56 Q24 22 60 20 Q96 22 94 56 L96 88 Q86 96 76 90 L44 90 Q34 96 24 88 Z" fill="${c}"/>`;
    if (style === "ponytail") return `<path d="M88 40 Q112 52 104 92 Q100 100 94 92 Q100 64 84 50 Z" fill="${c}"/>`;
    if (style === "bun") return `<circle cx="60" cy="18" r="13" fill="${c}"/>`;
    return "";
  }
  function hairFront(style, c) {
    if (["long", "bob", "ponytail", "bun"].includes(style))
      return `<path d="M30 54 Q28 24 60 22 Q92 24 90 54 Q84 40 72 36 Q66 46 52 44 Q44 50 36 46 Q32 50 30 54 Z" fill="${c}"/>`;
    if (style === "spiky")
      return `<path d="M30 52 L28 34 L38 38 L40 22 L50 32 L58 16 L64 30 L74 18 L78 34 L90 28 L90 52 Q80 40 60 40 Q40 40 30 52 Z" fill="${c}"/>`;
    if (style === "side") return `<path d="M30 54 Q26 24 60 22 Q94 24 90 50 Q74 34 46 38 Q36 42 30 54 Z" fill="${c}"/>`;
    if (style === "curly")
      return (
        [[34, 40], [44, 30], [56, 26], [68, 26], [80, 30], [88, 40]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="9" fill="${c}"/>`).join("") +
        `<path d="M28 50 Q30 34 60 32 Q90 34 92 50 Q76 42 60 42 Q44 42 28 50 Z" fill="${c}"/>`
      );
    return `<path d="M32 50 Q30 26 60 24 Q90 26 88 50 Q74 40 60 40 Q46 40 32 50 Z" fill="${c}" opacity=".9"/>`;
  }
  function eyesSvg(kind, color) {
    if (kind === "happy")
      return (
        '<path d="M42 64 Q47 58 52 64" stroke="#2B2321" stroke-width="2.6" fill="none" stroke-linecap="round"/>' +
        '<path d="M68 64 Q73 58 78 64" stroke="#2B2321" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
      );
    if (kind === "dot") return '<circle cx="47" cy="63" r="3.4" fill="#2B2321"/><circle cx="73" cy="63" r="3.4" fill="#2B2321"/>';
    return [47, 73]
      .map(
        (cx) =>
          `<ellipse cx="${cx}" cy="63" rx="6" ry="7.5" fill="#fff"/><ellipse cx="${cx}" cy="64" rx="4.6" ry="6" fill="${color}"/>` +
          `<ellipse cx="${cx}" cy="65" rx="2.4" ry="3.2" fill="#1d1414"/><circle cx="${g(cx + 1.8)}" cy="61" r="1.8" fill="#fff"/>` +
          `<path d="M${g(cx - 6.5)} 57 Q${cx} 54 ${g(cx + 6.5)} 57" stroke="#2B2321" stroke-width="2" fill="none" stroke-linecap="round"/>`
      )
      .join("");
  }
  function mouthSvg(kind) {
    if (kind === "open") return '<path d="M53 78 Q60 88 67 78 Z" fill="#B5414F"/><path d="M55 79 Q60 82 65 79" fill="#fff"/>';
    if (kind === "small") return '<ellipse cx="60" cy="80" rx="3" ry="2.4" fill="#C2505E"/>';
    if (kind === "cat") return '<path d="M53 78 Q56.5 82 60 78 Q63.5 82 67 78" stroke="#8A3B44" stroke-width="2" fill="none" stroke-linecap="round"/>';
    return '<path d="M52 77 Q60 85 68 77" stroke="#8A3B44" stroke-width="2.4" fill="none" stroke-linecap="round"/>';
  }
  function avatarSvg(seed, gender) {
    const A = CFG.AVATAR;
    const r = mulberry(seed);
    const bg = r.choice(A.BACKGROUNDS);
    const skin = r.choice(A.SKINS);
    const hair = r.random() < 0.15 ? r.choice(A.ANIME_HAIR) : r.choice(A.HAIR);
    const style =
      gender === "남성"
        ? r.choice(["spiky", "side", "curly", "buzz", "side", "spiky"])
        : gender === "여성"
          ? r.choice(["long", "bob", "ponytail", "bun", "long", "curly"])
          : r.choice(["spiky", "side", "curly", "long", "bob", "ponytail"]);
    const eyes = r.choice(["anime", "anime", "anime", "happy", "dot"]);
    const mouth = r.choice(["smile", "smile", "open", "small", "cat"]);
    const shirt = r.choice(A.SHIRTS);
    const blush = r.random() < 0.6;
    const glasses = r.random() < 0.2;
    const earrings = gender === "여성" && r.random() < 0.35;
    const parts = [
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">',
      `<rect width="120" height="120" fill="${bg}"/>`,
      hairBack(style, hair),
      `<rect x="52" y="86" width="16" height="14" fill="${skin}"/>`,
      `<path d="M22 120 Q24 98 52 96 L68 96 Q96 98 98 120 Z" fill="${shirt}"/>`,
      `<path d="M52 96 L60 106 L68 96" fill="${skin}"/>`,
      `<ellipse cx="31" cy="64" rx="5" ry="7" fill="${skin}"/><ellipse cx="89" cy="64" rx="5" ry="7" fill="${skin}"/>`,
      `<ellipse cx="60" cy="60" rx="29" ry="31" fill="${skin}"/>`,
    ];
    if (earrings) parts.push('<circle cx="31" cy="73" r="2.6" fill="#F5C542"/><circle cx="89" cy="73" r="2.6" fill="#F5C542"/>');
    parts.push(eyesSvg(eyes, r.choice(A.EYES)));
    if (blush)
      parts.push('<ellipse cx="40" cy="74" rx="5.5" ry="3" fill="#FF8FA3" opacity=".45"/><ellipse cx="80" cy="74" rx="5.5" ry="3" fill="#FF8FA3" opacity=".45"/>');
    parts.push(mouthSvg(mouth));
    if (glasses)
      parts.push('<g fill="none" stroke="#2B2321" stroke-width="2"><circle cx="47" cy="64" r="9"/><circle cx="73" cy="64" r="9"/><path d="M56 64 L64 64"/></g>');
    parts.push(hairFront(style, hair));
    parts.push("</svg>");
    return parts.join("");
  }
  function photoUrl(p) {
    if (p.photo === "upload") {
      const data = loadRaw(KEY.photo(p.id));
      if (data) return data;
    }
    const seed = p.photo && p.photo.startsWith("avatar:") ? p.photo.slice(7) : `${p.id}-${p.name}`;
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(avatarSvg(seed, p.gender));
  }

  // ── 요청 처리 (app/main.py 의 API와 같은 주소·응답) ─────────
  const routes = [
    ["GET", /^\/api\/options$/, () => CFG.OPTIONS],
    ["GET", /^\/api\/profiles$/, () => profiles],
    ["GET", /^\/api\/profiles\/(\d+)$/, (m) => getProfile(m[1]) || fail("프로필을 찾을 수 없습니다.")],
    [
      "POST", /^\/api\/profiles$/,
      (m, body) => {
        const p = validateNewProfile(body);
        p.id = Math.max(0, ...profiles.map((x) => x.id)) + 1;
        profiles.push(p);
        saveProfiles();
        return p;
      },
    ],
    [
      "PUT", /^\/api\/profiles\/(\d+)\/preferences$/,
      (m, body) => {
        const p = getProfile(m[1]) || fail("프로필을 찾을 수 없습니다.");
        p.preferences = validatePreferences(body);
        saveProfiles();
        return p;
      },
    ],
    [
      "POST", /^\/api\/recommend$/,
      (m, body) => {
        const me = getProfile(body.user_id) || fail("프로필을 찾을 수 없습니다.");
        const prefs = body.preferences ? validatePreferences(clone(body.preferences)) : null;
        return recommend(me, profiles, prefs, !!body.mutual, body.top_n || CFG.DEFAULT_TOP_N, body.top_k || CFG.CANDIDATE_TOP_K);
      },
    ],
    ["POST", /^\/api\/dealbreakers\/parse$/, (m, body) => parseRules(String(body.text || "").slice(0, 500))],
    [
      "POST", /^\/api\/likes$/,
      (m, body) => {
        const me = getProfile(body.from_id) || fail("프로필을 찾을 수 없습니다.");
        const other = getProfile(body.to_id) || fail("프로필을 찾을 수 없습니다.");
        if (me.preferences.blocked_ids.includes(other.id) || other.preferences.blocked_ids.includes(me.id)) fail("차단된 사용자예요.");
        return like(me.id, other.id, body.message);
      },
    ],
    [
      "GET", /^\/api\/users\/(\d+)\/inbox$/,
      (m) => {
        const uid = Number(m[1]);
        const received = social.likes
          .filter((l) => l.to === uid && !findLike(uid, l.from) && getProfile(l.from))
          .map((l) => ({ ...card(getProfile(l.from)), message: l.message, at: l.at }));
        const matchesList = social.likes
          .filter((l) => l.from === uid && findLike(l.to, uid) && getProfile(l.to))
          .map((l) => ({ ...card(getProfile(l.to)), last: lastMessage(uid, l.to), unread: unreadCount(uid, l.to) }))
          .sort((a, b) => ((b.last ? b.last.at : "") > (a.last ? a.last.at : "") ? 1 : (b.last ? b.last.at : "") < (a.last ? a.last.at : "") ? -1 : 0));
        return { received, matches: matchesList, sent: social.likes.filter((l) => l.from === uid).map((l) => l.to) };
      },
    ],
    [
      "GET", /^\/api\/chats\/(\d+)\/(\d+)$/,
      (m) => {
        const viewer = Number(m[1]);
        const other = getProfile(m[2]) || fail("프로필을 찾을 수 없습니다.");
        if (!isMatch(viewer, other.id)) fail("매칭된 사람과의 대화만 볼 수 있어요.");
        const msgs = social.messages[pairKey(viewer, other.id)] || [];
        let changed = false;
        for (const msg of msgs)
          if (msg.to === viewer && !msg.read) {
            msg.read = true;
            changed = true;
          }
        if (changed) saveSocial();
        return { with: card(other), messages: msgs };
      },
    ],
    [
      "POST", /^\/api\/chats\/(\d+)$/,
      (m, body) => {
        const to = Number(m[1]);
        const text = String(body.text || "").trim();
        if (!text) fail("메시지를 입력해 주세요.");
        if (text.length > 500) fail("메시지는 500자까지 보낼 수 있어요.");
        if (!isMatch(body.sender_id, to)) fail("서로 좋아요를 눌러 매칭된 사람에게만 메시지를 보낼 수 있어요.");
        const msg = addMessage(body.sender_id, to, text);
        saveSocial();
        return msg;
      },
    ],
    [
      "POST", /^\/api\/block$/,
      (m, body) => {
        const me = getProfile(body.user_id) || fail("프로필을 찾을 수 없습니다.");
        const t = Number(body.target_id);
        me.preferences.blocked_ids = [...new Set([...me.preferences.blocked_ids, t])].sort((a, b) => a - b);
        social.likes = social.likes.filter((l) => !((l.from === me.id && l.to === t) || (l.from === t && l.to === me.id)));
        delete social.messages[pairKey(me.id, t)];
        saveProfiles();
        saveSocial();
        return me;
      },
    ],
    [
      "PUT", /^\/api\/profiles\/(\d+)\/photo$/,
      (m, body) => {
        const p = getProfile(m[1]) || fail("프로필을 찾을 수 없습니다.");
        const url = String(body.data_url || "");
        if (!/^data:image\/(jpeg|png|webp);base64,/.test(url)) fail("JPG, PNG, WEBP 사진만 올릴 수 있어요.");
        if (url.length > 4 * 1024 * 1024) fail("사진이 너무 커요.");
        save(KEY.photo(p.id), url);
        p.photo = "upload";
        saveProfiles();
        return p;
      },
    ],
    [
      "POST", /^\/api\/profiles\/(\d+)\/avatar$/,
      (m) => {
        const p = getProfile(m[1]) || fail("프로필을 찾을 수 없습니다.");
        remove(KEY.photo(p.id));
        p.photo = `avatar:${Math.floor(Math.random() * 2 ** 40).toString(16)}`;
        saveProfiles();
        return p;
      },
    ],
    [
      "GET", /^\/api\/data-status$/,
      () => ({ data_dir: "이 브라우저", profiles: profiles.length, backups: load(KEY.backup) ? 1 : 0, repair_notes: [], quarantined: false, web: true }),
    ],
    [
      "POST", /^\/api\/reset$/,
      () => {
        save(KEY.backup, { profiles, social, at: nowIso() }); // 되돌리기 전 마지막 상태 1개 보관
        profiles.forEach((p) => remove(KEY.photo(p.id)));
        profiles = clone(SAMPLE.profiles).map(normalizeProfile);
        social = clone(SAMPLE.social);
        saveProfiles();
        saveSocial();
        return { ok: true, count: profiles.length, backups: ["이 브라우저에 마지막 상태 1개"] };
      },
    ],
    ["POST", /^\/api\/shutdown$/, () => fail("웹 버전은 끌 서버가 없어요. 창을 닫으면 돼요.")],
  ];

  async function handle(path, options = {}) {
    await ready;
    const method = (options.method || "GET").toUpperCase();
    const body = options.body ? JSON.parse(options.body) : {};
    const clean = path.split("?")[0];
    for (const [m, re, fn] of routes) {
      const match = m === method && re.exec(clean);
      if (match) return clone(fn(match, body)); // 화면이 저장 데이터를 직접 고치지 못하게 복사본을 준다
    }
    fail(`지원하지 않는 요청: ${method} ${clean}`);
  }

  // ── 백업 파일 내보내기 / 불러오기 ──────────────────────────
  function exportData() {
    const photos = Object.fromEntries(profiles.filter((p) => p.photo === "upload").map((p) => [p.id, loadRaw(KEY.photo(p.id))]));
    return JSON.stringify({ app: "dating-matcher", version: 1, exported_at: nowIso(), profiles, social, photos });
  }
  function importData(text) {
    const data = JSON.parse(text);
    if (data.app !== "dating-matcher" || !Array.isArray(data.profiles)) fail("이 앱의 백업 파일이 아니에요.");
    save(KEY.backup, { profiles, social, at: nowIso() });
    profiles = data.profiles.map(normalizeProfile);
    social = { likes: [], messages: {}, ...(data.social || {}) };
    for (const [id, url] of Object.entries(data.photos || {})) if (url) save(KEY.photo(id), url);
    saveProfiles();
    saveSocial();
    return profiles.length;
  }

  // ── 시작: 설정·샘플 불러오고, 이 브라우저에 저장된 데이터가 있으면 그걸 쓴다 ──
  const ready = (async () => {
    const res = await fetch(`${BASE}static/web-data.json`);
    const data = await res.json();
    CFG = data.config;
    SAMPLE = { profiles: data.sample_profiles, social: data.sample_social };
    const stored = load(KEY.profiles);
    profiles = (stored && stored.length ? stored : clone(SAMPLE.profiles)).map(normalizeProfile);
    social = { likes: [], messages: {}, ...(load(KEY.social) || clone(SAMPLE.social)) };
    if (!stored) {
      saveProfiles();
      saveSocial();
    }
  })();

  window.LOCAL_API = { handle, photoUrl, exportData, importData, ready, _engine: { recommend, score, fnv1a, mulberry, avatarSvg, parseRules } };
})();
