/* Offline DOM surface only: production app.js executes unchanged. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync("site/app.js", "utf8");
const NOW = Date.parse("2026-10-01T12:00:00Z"), HOUR = 3600000;

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.value = ""; }
  set textContent(value) { this.value = String(value); this.children = []; }
  get textContent() { return this.value + this.children.map(c => typeof c === "string" ? c : c.textContent).join(""); }
  set innerHTML(value) { throw new Error("Data must never use innerHTML: " + value); }
  get firstChild() { return this.children[0]; }
  appendChild(child) { this.children.push(child); return child; }
  append(child) { this.appendChild(child); }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(key, fn) { this.events[key] = fn; }
  focus() {}
}
function storage() {
  const data = new Map();
  return { getItem: key => data.get(key) || null, setItem: (key, value) => data.set(key, value) };
}
function stream(extra = {}) {
  return Object.assign({ video_id: "abcdefghi12", title: "Broadcast", channel: "OpenAI", status: "ended",
    start_at: null, end_at: null, time_text: "Streamed 1d ago", time_precision: "relative", status_source: "channel_streams" }, extra);
}
async function page(item, options = {}) {
  const nodes = new Map(), local = options.local || storage(), session = options.session || storage();
  const document = { createElement: tag => new Element(tag), createTextNode: text => String(text),
    getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Element("div")); return nodes.get(id); },
    querySelectorAll: () => [] };
  class Clock extends Date { static now() { return NOW; } }
  const data = { generated_at: new Date(NOW - (options.snapshotAge || 0)).toISOString(), live: [item] };
  if (Object.hasOwn(options, "generatedAt")) data.generated_at = options.generatedAt;
  vm.runInNewContext(source, { document, window: { localStorage: local, sessionStorage: session }, Date: Clock,
    Intl, URL, Set, fetch: async () => ({ ok: true, json: async () => data }), setInterval() {} });
  await new Promise(resolve => setImmediate(resolve));
  assert.notEqual(nodes.get("lede").textContent, "Chưa mở được bản tin.");
  return { nodes, local, session, text: id => nodes.get(id).textContent };
}
function tags(el) { return (el.className === "new" ? 1 : 0) + el.children.reduce((n, c) => n + (typeof c === "string" ? 0 : tags(c)), 0); }

test("ended fallback displays Vietnamese relative text without fabricated timestamp", async () => {
  const item = stream(), p = await page(item);
  assert.match(p.text("streams"), /Đã phát 1 ngày trước/);
  assert.equal(item.end_at, null);
  assert.equal(item.start_at, null);
  assert.equal(tags(p.nodes.get("streams")), 0); // 1d means [24h, 48h), outside first-visit 24h.
});
test("whole relative bucket and snapshot age must fit first-visit window", async () => {
  for (const [label, age, expected] of [["Streamed 2 hours ago", 0, 1], ["Streamed 23h ago", 0, 1],
    ["Streamed 1 minute ago", 0, 1], ["Streamed 30s ago", 0, 1],
    ["Streamed 23h ago", 1, 0], ["Streamed 2h ago", 22 * HOUR, 0], ["Streamed 2h ago", -HOUR, 0],
    ["Streamed recently", 0, 0], ["Streamed 99999999999999999h ago", 0, 0]]) {
    const p = await page(stream({ time_text: label }), { snapshotAge: age });
    assert.equal(tags(p.nodes.get("streams")), expected, label + " snapshot age " + age);
  }
  for (const generatedAt of [null, "invalid"]) {
    const p = await page(stream({ time_text: "Streamed 2h ago" }), { generatedAt });
    assert.equal(tags(p.nodes.get("streams")), 0, "Missing snapshot cannot prove freshness");
  }
});
test("captured timezone-free upcoming text appears in stage and lede", async () => {
  const fixture = fs.readFileSync("tests/fixtures/youtube-runner-streams-upcoming.html", "utf8");
  const captured = fixture.match(/Scheduled for [^"<>]+/)[0];
  const item = stream({ status: "upcoming", time_text: captured, time_precision: "unknown" });
  const p = await page(item);
  for (const id of ["now-live", "lede-sub"]) {
    assert.match(p.text(id), /Dự kiến phát: 10\/1\/26, 6:53\s+chiều/);
    assert.match(p.text(id), /chưa rõ múi giờ/);
    assert.doesNotMatch(p.text(id), /chưa rõ giờ|Scheduled for|giờ Việt Nam/);
  }
  assert.equal(item.start_at, null);
});
test("unknown text stays conservative and schedule payload is plain text", async () => {
  const unknown = await page(stream({ time_text: "something unknown" }));
  assert.match(unknown.text("streams"), /Đã kết thúc/);
  const missing = await page(stream({ status: "upcoming", time_text: "not a schedule" }));
  assert.match(missing.text("now-live"), /chưa rõ giờ/);
  assert.match(missing.text("lede-sub"), /chưa rõ giờ/);
  const payload = "<img src=x onerror=alert(1)>";
  const p = await page(stream({ status: "upcoming", time_text: "Scheduled for " + payload }));
  assert.match(p.text("now-live"), /Dự kiến phát:/);
  assert.ok(p.text("now-live").includes(payload));
});
test("exact times still take precedence and seen state survives mark/reload", async () => {
  const item = stream({ start_at: "2026-10-01T10:00:00Z", end_at: "2026-10-01T11:00:00Z" });
  const p = await page(item);
  assert.match(p.text("streams"), /Kết thúc 1 giờ trước.*dài 1 giờ/);
  assert.equal(tags(p.nodes.get("streams")), 1);
  p.nodes.get("mark-read").events.click();
  assert.equal(tags(p.nodes.get("streams")), 0);
  const again = await page(item, p);
  assert.equal(tags(again.nodes.get("streams")), 0);
  const next = await page(item, { local: p.local });
  assert.equal(tags(next.nodes.get("streams")), 0);
});
test("exact upcoming and live clocks retain Vietnam time behavior", async () => {
  const upcoming = await page(stream({ status: "upcoming", start_at: "2026-10-01T13:00:00Z" }));
  assert.match(upcoming.text("now-live"), /20:00 tối naycòn 1 giờ/);
  assert.match(upcoming.text("lede-sub"), /sắp phát trực tiếp, còn 1 giờ/);
  assert.doesNotMatch(upcoming.text("now-live"), /chưa rõ múi giờ|Dự kiến phát/);
  const live = await page(stream({ status: "live", start_at: "2026-10-01T11:00:00Z" }));
  assert.match(live.text("now-live"), /bắt đầu 1 giờ trước/);
  assert.match(live.text("lede-sub"), /đang phát trực tiếp/);
});
test("relative seen persistence retains pinned session and status keys", async () => {
  const item = stream({ time_text: "Streamed 2h ago" }), p = await page(item);
  assert.equal(tags(p.nodes.get("streams")), 1);
  const reload = await page(item, p);
  assert.equal(tags(reload.nodes.get("streams")), 1);
  p.nodes.get("mark-read").events.click();
  assert.equal(tags((await page(item, p)).nodes.get("streams")), 0);
  assert.equal(tags((await page(item, { local: p.local })).nodes.get("streams")), 0);
  const changed = await page(stream({ status: "live" }), { local: p.local });
  assert.equal(tags(changed.nodes.get("now-live")), 1);
});
