/**
 * Snag AI — a tiny Cloudflare Worker that does Snag's AI checks in the cloud.
 *
 * Photo checks: Cloudflare's own free vision model (Llama 4 Scout, no outside key), with
 * Google Gemini as the backup when Cloudflare's free daily allowance is used up.
 * Chat questions: Groq first (fast, generous free tier), then the same models as above.
 *
 * Keys are Worker secrets (set with `wrangler secret put`), never in the page or the repo.
 */

const CF_VISION_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct";
const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent";
// Order matters (measured 2026-11-18): Gemini lite models give the best prices and answer in
// seconds; Cloudflare's model handles volume once Gemini's free quota is spent; the full
// Gemini Flash models are often overloaded on the free tier, so they go last.
const GEMINI_LITE = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"];
const GEMINI_FULL = ["gemini-3.8-flash", "gemini-3.5-flash"];
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"];
const ALLOWED_ORIGINS = ["https://elitanz.github.io"];
const MAX_BODY = 12 * 1024 * 1024;
const MAX_IMAGES = 3;
const MAX_PROMPT = 20000;
const PER_CALL_TIMEOUT_MS = 25000;

class UpstreamError extends Error {
  constructor(code, status) { super(code); this.code = code; this.status = status; }
}

function corsHeaders(origin) {
  const ok = ALLOWED_ORIGINS.includes(origin) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin || "");
  return ok ? { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400", Vary: "Origin" } : null;
}

function json(status, obj, cors) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...(cors || {}) } });
}

async function fetchJson(url, init) {
  let resp;
  try {
    resp = await fetch(url, { ...init, signal: AbortSignal.timeout(PER_CALL_TIMEOUT_MS) });
  } catch (e) {
    throw new UpstreamError(e && e.name === "TimeoutError" ? "timeout" : "network", 504);
  }
  if (!resp.ok) throw new UpstreamError(resp.status === 429 ? "rate_limited" : "upstream", resp.status);
  try { return await resp.json(); } catch (e) { throw new UpstreamError("upstream", 502); }
}

function parseJsonText(text) {
  let t = String(text || "").trim();
  if (t.startsWith("```")) t = t.replace(/^```[a-z]*\n?/i, "").replace(/```\s*$/, "");
  try { return JSON.parse(t); } catch (e) {
    const a = t.indexOf("{"), b = t.lastIndexOf("}");
    if (a >= 0 && b > a) return JSON.parse(t.slice(a, b + 1));
    throw e;
  }
}

/* ---------- providers ---------- */

async function cloudflareAI(env, messages, maxTokens) {
  if (!env.AI) throw new UpstreamError("no_binding", 500);
  let out;
  try {
    out = await env.AI.run(CF_VISION_MODEL, { messages, max_tokens: maxTokens, temperature: 0.4 });
  } catch (e) {
    // Free daily allowance used up, model busy, or a bad request: let the caller fall back.
    throw new UpstreamError("upstream", 503);
  }
  const text = typeof out?.response === "string" ? out.response : (out?.response ? JSON.stringify(out.response) : "");
  if (!text.trim()) throw new UpstreamError("empty", 502);
  return text;
}

async function gemini(env, contents, wantJson, models) {
  if (!env.GEMINI_KEY) throw new UpstreamError("no_key", 500);
  const generationConfig = { temperature: 0.4, ...(wantJson ? { responseMimeType: "application/json" } : {}) };
  let last = new UpstreamError("upstream", 502);
  for (const model of models) {
    try {
      const d = await fetchJson(GEMINI_URL.replace("{model}", model), {
        method: "POST", headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_KEY },
        body: JSON.stringify({ contents, generationConfig }),
      });
      const parts = d?.candidates?.[0]?.content?.parts || [];
      const text = parts.filter(p => !p.thought).map(p => p.text || "").join("").trim();
      if (text) return { text, model };
      last = new UpstreamError("empty", 502);
    } catch (e) {
      last = e;   // quota spent, busy, timed out or retired: try the next model
    }
  }
  throw last;
}

async function groq(env, messages) {
  if (!env.GROQ_KEY) throw new UpstreamError("no_key", 500);
  let last = new UpstreamError("upstream", 502);
  for (const model of GROQ_MODELS) {
    try {
      const d = await fetchJson(GROQ_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + env.GROQ_KEY, "User-Agent": "snag-worker/1.0" },
        body: JSON.stringify({ model, messages, temperature: 0.4 }),
      });
      const text = (d?.choices?.[0]?.message?.content || "").trim();
      if (text) return { text, model };
    } catch (e) { last = e; }
  }
  throw last;
}

/* ---------- request handlers ---------- */

function validImages(images) {
  return Array.isArray(images) && images.length <= MAX_IMAGES &&
    images.every(i => typeof i === "string" && i.length > 0 && i.length < 4 * 1024 * 1024 && /^[A-Za-z0-9+/=]+$/.test(i.slice(0, 4096)));
}

async function handleCheck(env, body) {
  const { prompt } = body;
  const images = body.images || [];
  if (typeof prompt !== "string" || !prompt || prompt.length > MAX_PROMPT || !validImages(images)) {
    return { status: 400, data: { ok: false, code: "bad_request" } };
  }
  const parts = [{ text: prompt }, ...images.map(b64 => ({ inlineData: { mimeType: "image/jpeg", data: b64 } }))];
  const viaGemini = async models => {
    const { text, model } = await gemini(env, [{ role: "user", parts }], true, models);
    return { status: 200, data: { ok: true, json: parseJsonText(text), model } };
  };
  // 1) Gemini lite: best prices, fast
  try { return await viaGemini(GEMINI_LITE); } catch (e) { /* next */ }
  // 2) Cloudflare's own vision model: no outside key, generous free daily allowance
  try {
    const jsonOnly = prompt + "\n\nReturn only the JSON object, with no other text.";
    const content = [{ type: "text", text: jsonOnly }, ...images.map(b64 => ({ type: "image_url", image_url: { url: "data:image/jpeg;base64," + b64 } }))];
    const text = await cloudflareAI(env, [{ role: "user", content }], 1800);
    return { status: 200, data: { ok: true, json: parseJsonText(text), model: CF_VISION_MODEL } };
  } catch (e) { /* next */ }
  // 3) Full Gemini Flash models (often busy on the free tier)
  try { return await viaGemini(GEMINI_FULL); } catch (e) {
    throw e instanceof UpstreamError ? e : new UpstreamError("bad_json", 502);
  }
}

async function handleText(env, body) {
  const msgs = body.messages;
  if (!Array.isArray(msgs) || !msgs.length || msgs.length > 40 ||
      !msgs.every(m => (m?.role === "user" || m?.role === "assistant") && typeof m.content === "string" && m.content.length <= MAX_PROMPT)) {
    return { status: 400, data: { ok: false, code: "bad_request" } };
  }
  const clean = msgs.map(m => ({ role: m.role, content: m.content }));
  try { const r = await groq(env, clean); return { status: 200, data: { ok: true, ...r } }; } catch (e) { /* next */ }
  try { const text = await cloudflareAI(env, clean, 700); return { status: 200, data: { ok: true, text, model: CF_VISION_MODEL } }; } catch (e) { /* next */ }
  const contents = clean.map(m => ({ role: m.role === "assistant" ? "model" : "user", parts: [{ text: m.content }] }));
  const r = await gemini(env, contents, false, [...GEMINI_LITE, ...GEMINI_FULL]);
  return { status: 200, data: { ok: true, ...r } };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request.headers.get("Origin"));
    if (request.method === "OPTIONS") return cors ? new Response(null, { status: 204, headers: cors }) : new Response(null, { status: 403 });
    if ((url.pathname === "/status" || url.pathname === "/ai/status") && request.method === "GET") return json(200, { ok: true, provider: "cloudflare" }, cors);
    if (url.pathname !== "/ai" || request.method !== "POST") return json(404, { ok: false, code: "not_found" }, cors);
    if (!cors) return json(403, { ok: false, code: "forbidden" });
    const length = Number(request.headers.get("Content-Length") || 0);
    if (length > MAX_BODY) return json(413, { ok: false, code: "too_large" }, cors);
    let body;
    try { body = await request.json(); } catch (e) { return json(400, { ok: false, code: "bad_request" }, cors); }
    try {
      const { status, data } = body?.kind === "json" ? await handleCheck(env, body)
        : body?.kind === "text" ? await handleText(env, body)
        : { status: 400, data: { ok: false, code: "bad_request" } };
      return json(status, data, cors);
    } catch (e) {
      const code = e instanceof UpstreamError ? (e.code === "network" ? "upstream" : e.code) : "upstream";
      console.log("AI request failed:", code, e && e.status);
      return json(code === "rate_limited" ? 429 : 502, { ok: false, code }, cors);
    }
  },
};
