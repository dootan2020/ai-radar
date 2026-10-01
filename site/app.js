/* Bản tin sáng: renders data/radar.json. No framework, no build. */
(function () {
  "use strict";

  var TZ = "Asia/Ho_Chi_Minh";
  var LAST_KEY = "radar.lastVisit";
  var SEEN_KEY = "radar.seen";
  var SESSION_KEY = "radar.session";
  var SEEN_CAP = 4000;
  var HOUR = 3600e3;
  var DAY = 24 * HOUR;
  /* An unseen item older than this is backfill (a new source, a re-crawl), not news. */
  var NEW_MAX_AGE = 7 * DAY;
  var FEED_MIN = 6;
  var FEED_FIRST_MAX = 20;
  var FEED_STEP = 15;
  var SIDE_SHORT = 5;
  var SIDE_STEP = 10;

  var LABS = {
    anthropic: "Anthropic", openai: "OpenAI", google: "Google", xai: "xAI", deepseek: "DeepSeek",
    meta: "Meta", mistral: "Mistral", qwen: "Qwen", nvidia: "NVIDIA", microsoft: "Microsoft",
    huggingface: "Hugging Face"
  };
  var LAB_ORDER = Object.keys(LABS);
  var MAJOR = { anthropic: 1, openai: 1, google: 1, xai: 1, deepseek: 1, meta: 1, mistral: 1, qwen: 1 };
  var KIND = { model: "Mô hình", product: "Sản phẩm", research: "Nghiên cứu" };
  var KIND_WEIGHT = { model: 3, product: 2, research: 1 };
  var HF_TYPE = { model: "Mô hình", space: "Space", dataset: "Bộ dữ liệu" };
  var WEEKDAY = ["Chủ nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];

  var state = {
    data: null, now: Date.now(), baseline: null, seen: null, lab: null,
    feedLimit: null, limits: { gh: SIDE_SHORT, hf: SIDE_SHORT, releases: SIDE_SHORT }
  };

  /* ---------- storage (never trusted to exist) ---------- */
  function read(store, key) {
    try { return store.getItem(key); } catch (e) { return null; }
  }
  function write(store, key, value) {
    try { store.setItem(key, value); } catch (e) { /* private mode or full: page still works */ }
  }
  function parse(json) {
    try { return JSON.parse(json); } catch (e) { return null; }
  }

  /* Stable keys for "has he seen this". A stream is keyed with its status, so upcoming -> live is news again. */
  function keyUpdate(u) { return "u:" + (u.id || u.url); }
  function keyRelease(r) { return "hf:" + r.id; }
  function keyStream(s) { return "yt:" + s.video_id + ":" + s.status; }
  function allKeys(d) {
    return d.updates.map(keyUpdate).concat(d.hf_releases.map(keyRelease), d.live.map(keyStream));
  }

  /*
   * One session keeps one baseline: the seen-set and last-visit time as they were when the session began.
   * Reloads inside the session keep the same "Mới" marks. Everything shown is added to the stored seen-set
   * at once, so the next session starts after it.
   */
  function establishBaseline(d) {
    var pinned = parse(read(window.sessionStorage, SESSION_KEY));
    var base;
    if (pinned && typeof pinned === "object") {
      base = { baseline: pinned.baseline || null, seen: Array.isArray(pinned.seen) ? pinned.seen : null };
    } else {
      var last = Number(read(window.localStorage, LAST_KEY)) || null;
      var seen = parse(read(window.localStorage, SEEN_KEY));
      base = { baseline: last, seen: Array.isArray(seen) ? seen : null };
      write(window.sessionStorage, SESSION_KEY, JSON.stringify(base));
      write(window.localStorage, LAST_KEY, String(Date.now()));
    }
    remember(d, parse(read(window.localStorage, SEEN_KEY)));
    state.baseline = base.baseline;
    state.seen = base.seen ? new Set(base.seen) : null;
  }
  function remember(d, previous) {
    var keys = allKeys(d), set = new Set(keys);
    (Array.isArray(previous) ? previous : []).forEach(function (k) { if (set.size < SEEN_CAP) set.add(k); });
    write(window.localStorage, SEEN_KEY, JSON.stringify(Array.from(set)));
  }
  function markAllRead() {
    var d = state.data, now = Date.now(), keys = allKeys(d);
    write(window.localStorage, LAST_KEY, String(now));
    remember(d, parse(read(window.localStorage, SEEN_KEY)));
    write(window.sessionStorage, SESSION_KEY, JSON.stringify({ baseline: now, seen: keys }));
    state.baseline = now;
    state.seen = new Set(keys);
  }

  /* ---------- time, always Vietnam time ---------- */
  var partsFmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short"
  });
  var WD = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  function vn(ms) {
    var o = {};
    partsFmt.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = p.value; });
    return { y: +o.year, m: +o.month, d: +o.day, hh: o.hour, mm: o.minute, h: +o.hour, wd: WD[o.weekday], key: o.year + "-" + o.month + "-" + o.day };
  }
  function dayDiff(a, b) {
    var pa = vn(a), pb = vn(b);
    return Math.round((Date.UTC(pb.y, pb.m - 1, pb.d) - Date.UTC(pa.y, pa.m - 1, pa.d)) / DAY);
  }
  function isDateOnly(iso) { return /T00:00:00(\.0+)?Z$/.test(iso); }
  function shortDate(p, withYear) { return p.d + "/" + p.m + (withYear ? "/" + p.y : ""); }
  function partOfDay(h) { return h < 11 ? "sáng" : h < 13 ? "trưa" : h < 18 ? "chiều" : "tối"; }

  /* "22:40 tối qua", "07:10 sáng nay", "thứ hai 28/9" */
  function whenPhrase(ms) {
    var p = vn(ms), diff = dayDiff(ms, state.now), t = p.hh + ":" + p.mm;
    if (diff === 0) return t + " " + partOfDay(p.h) + " nay";
    if (diff === 1) return p.h >= 18 ? t + " tối qua" : t + " " + partOfDay(p.h) + " hôm qua";
    return WEEKDAY[p.wd].toLowerCase() + " " + shortDate(p, p.y !== vn(state.now).y);
  }
  function relTime(iso) {
    var ms = Date.parse(iso), p = vn(ms), nowP = vn(state.now), diff = dayDiff(ms, state.now);
    if (isDateOnly(iso)) {
      if (diff === 0) return "hôm nay";
      if (diff === 1) return "hôm qua";
      return shortDate(p, p.y !== nowP.y);
    }
    var ago = state.now - ms;
    if (ago < 0) return p.hh + ":" + p.mm + ", " + shortDate(p);
    if (ago < 60e3) return "vừa xong";
    if (ago < HOUR) return Math.floor(ago / 60e3) + " phút trước";
    if (ago < DAY) return Math.floor(ago / HOUR) + " giờ trước";
    return shortDate(p, p.y !== nowP.y) + ", " + p.hh + ":" + p.mm;
  }
  function fullTime(iso) {
    var p = vn(Date.parse(iso));
    return isDateOnly(iso) ? WEEKDAY[p.wd] + ", " + shortDate(p, true) : p.hh + ":" + p.mm + ", " + WEEKDAY[p.wd] + " " + shortDate(p, true) + " (giờ Việt Nam)";
  }
  function dayLabel(ms) {
    var diff = dayDiff(ms, state.now), p = vn(ms);
    if (diff === 0) return "Hôm nay";
    if (diff === 1) return "Hôm qua";
    return WEEKDAY[p.wd] + ", " + shortDate(p, p.y !== vn(state.now).y);
  }
  function duration(a, b) {
    var mins = Math.round((Date.parse(b) - Date.parse(a)) / 60e3);
    if (!(mins > 0)) return null;
    var h = Math.floor(mins / 60), m = mins % 60;
    return h ? h + " giờ" + (m ? " " + m + " phút" : "") : m + " phút";
  }
  function countdown(iso) {
    var ms = Date.parse(iso) - state.now;
    if (ms <= 0) return "sắp bắt đầu";
    if (ms < HOUR) return "còn " + Math.ceil(ms / 60e3) + " phút";
    if (ms < DAY) return "còn " + Math.round(ms / HOUR) + " giờ";
    return "còn " + Math.round(ms / DAY) + " ngày";
  }
  var nf = new Intl.NumberFormat("vi-VN");
  function n(x) { return nf.format(x); }

  /* ---------- DOM helper: text only, never innerHTML with data ---------- */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined || c === false) continue;
      if (Array.isArray(c)) c.forEach(function (x) { if (x) el.appendChild(typeof x === "string" ? document.createTextNode(x) : x); });
      else el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return el;
  }
  function $(id) { return document.getElementById(id); }
  /* Element.append() would print "null"; this skips empty slots. */
  function add(el) {
    for (var i = 1; i < arguments.length; i++) {
      var c = arguments[i];
      if (c !== null && c !== undefined && c !== false && c !== "") el.append(c);
    }
    return el;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function empty(text) { return h("p", { class: "empty", text: text }); }
  function safeUrl(u) { return /^https:\/\//.test(u || "") ? u : null; }
  function labName(id) { return LABS[id] || id || ""; }
  function byDateDesc(field) {
    return function (a, b) { return Date.parse(b[field]) - Date.parse(a[field]); };
  }

  /* ---------- what counts as new ---------- */
  function windowStart() { return state.baseline !== null ? state.baseline : state.now - DAY; }
  /* Unseen id wins when we have a seen-set; before that, fall back to time since last visit (or 24h on a first visit). */
  function isNewAt(key, iso) {
    var ms = Date.parse(iso);
    if (state.seen) return !state.seen.has(key) && state.now - ms < NEW_MAX_AGE;
    return ms > windowStart();
  }
  function isNewUpdate(u) { return isNewAt(keyUpdate(u), u.published_at); }
  function isNewRelease(r) { return isNewAt(keyRelease(r), r.created_at); }
  function isNewStream(s) {
    if (state.seen) return !state.seen.has(keyStream(s));
    if (s.status !== "ended") return true;
    return !!s.end_at && Date.parse(s.end_at) > windowStart();
  }
  function firstVisit() { return state.seen === null && state.baseline === null; }

  function meta(parts) {
    return h("p", { class: "meta" }, parts.filter(Boolean));
  }
  function timeEl(iso) {
    return h("time", { datetime: iso, title: fullTime(iso), text: relTime(iso) });
  }
  function newTag() { return h("span", { class: "new", text: "Mới" }); }

  /* ---------- lead: the single most important recent launch ---------- */
  /* Only a model, product or research item can lead. With none new, look back 48h; with none there, no lead. */
  function pickLead(updates) {
    var ranked = function (pool) {
      return pool.filter(function (u) { return KIND_WEIGHT[u.kind]; }).sort(function (a, b) {
        return (KIND_WEIGHT[b.kind] - KIND_WEIGHT[a.kind]) || ((MAJOR[b.lab] ? 1 : 0) - (MAJOR[a.lab] ? 1 : 0)) ||
          Date.parse(b.published_at) - Date.parse(a.published_at);
      })[0] || null;
    };
    var lead = ranked(updates.filter(isNewUpdate));
    if (lead) return { item: lead, fresh: true };
    lead = ranked(updates.filter(function (u) { return state.now - Date.parse(u.published_at) < 2 * DAY; }));
    return lead ? { item: lead, fresh: false } : null;
  }

  function renderToday() {
    var p = vn(Date.now());
    $("today").textContent = WEEKDAY[p.wd] + ", " + p.d + " tháng " + p.m + ", " + p.y;
  }

  /* ---------- masthead sentence ---------- */
  function renderLede(d) {
    renderToday();
    var newUpdates = d.updates.filter(isNewUpdate);
    var newModels = d.hf_releases.filter(isNewRelease);
    var lede = clear($("lede"));
    var total = newUpdates.length + newModels.length;

    if (firstVisit()) {
      add(lede, total ? "24 giờ qua có " : "24 giờ qua chưa có tin nào mới", total ? h("em", { text: total + " tin mới" }) : "", ".");
    } else if (total) {
      add(lede, h("em", { text: total + " tin mới" }), state.baseline !== null ? " kể từ " + whenPhrase(state.baseline) + "." : " kể từ lần trước anh xem.");
    } else {
      add(lede, "Chưa có gì mới kể từ " + (state.baseline !== null ? whenPhrase(state.baseline) : "lần trước anh xem") + ".");
    }

    var bits = [];
    if (newUpdates.length) {
      var byLab = {};
      newUpdates.forEach(function (u) { byLab[u.lab] = (byLab[u.lab] || 0) + 1; });
      var labs = Object.keys(byLab).sort(function (a, b) { return byLab[b] - byLab[a]; })
        .map(function (l) { return labName(l) + " " + byLab[l]; });
      bits.push("Tin từ " + labs.join(", ") + ".");
    }
    if (newModels.length) bits.push(newModels.length + " mô hình mở mới trên Hugging Face.");
    var live = d.live.filter(function (s) { return s.status === "live"; });
    var up = d.live.filter(function (s) { return s.status === "upcoming"; });
    var replays = d.live.filter(function (s) { return s.status === "ended" && isNewStream(s); });
    if (live.length) bits.push(live[0].channel + " đang phát trực tiếp.");
    else if (up.length) bits.push(up[0].channel + " sắp phát trực tiếp, " + (up[0].start_at ? countdown(up[0].start_at) : "chưa rõ giờ") + ".");
    else if (replays.length) bits.push("Có bản xem lại buổi phát của " + replays[0].channel + ".");
    var down = d.sources.filter(function (s) { return !s.ok; });
    if (down.length > 2) bits.push("Lần này không đọc được " + down.length + " nguồn, danh sách ở cuối trang.");
    else if (down.length) bits.push("Lần này không đọc được " + down.map(function (s) { return s.name; }).join(", ") + ".");
    if (firstVisit()) bits.push("Từ lần sau, bản tin chỉ đánh dấu những gì anh chưa xem.");

    var sub = $("lede-sub");
    sub.textContent = bits.join(" ");
    sub.hidden = !bits.length;
    $("lede-actions").hidden = !(!firstVisit() && total);
  }

  /* ---------- notices ---------- */
  function renderNotice(d) {
    var el = $("notice"), age = state.now - Date.parse(d.generated_at);
    if (age > 18 * HOUR) {
      el.textContent = "Dữ liệu được cập nhật lần cuối " + whenPhrase(Date.parse(d.generated_at)) + ", có thể đã cũ.";
      el.hidden = false;
    } else el.hidden = true;
  }

  /* ---------- streams ---------- */
  function player(s, autoplay) {
    var box = h("div", { class: "player" });
    var thumb = safeUrl(s.thumbnail);
    if (thumb) box.appendChild(h("img", { src: thumb, alt: "", loading: "lazy", decoding: "async" }));
    box.appendChild(h("button", {
      type: "button", class: "player__play", "aria-label": "Xem ngay tại đây: " + s.title,
      onclick: function () { embed(box, s); }
    }, h("span", { "aria-hidden": "true" }, "▶  Xem tại đây")));
    if (autoplay) embed(box, s);
    return box;
  }
  function embed(box, s) {
    if (!/^[\w-]{6,20}$/.test(s.video_id || "")) return;
    clear(box).appendChild(h("iframe", {
      src: "https://www.youtube-nocookie.com/embed/" + s.video_id + "?autoplay=1&rel=0",
      title: s.title, allow: "autoplay; encrypted-media; picture-in-picture; fullscreen", allowfullscreen: true
    }));
    var f = box.querySelector("iframe");
    if (f && box.isConnected) f.focus();
  }
  function streamMeta(s, label) {
    var parts = [isNewStream(s) ? newTag() : null, label || null, h("span", { class: "lab", text: s.channel || labName(s.lab) })];
    if (s.status === "live" && s.start_at) parts.push(h("span", { text: "bắt đầu " + relTime(s.start_at) }));
    if (s.status === "upcoming" && s.start_at) {
      var p = vn(Date.parse(s.start_at));
      parts.push(h("span", { text: p.hh + ":" + p.mm + " " + (dayDiff(Date.parse(s.start_at), state.now) === 0 ? partOfDay(p.h) + " nay" : shortDate(p)) }));
      parts.push(h("span", { text: countdown(s.start_at) }));
    }
    if (s.status === "ended") {
      parts.push(h("span", { text: s.end_at ? "Kết thúc " + relTime(s.end_at) : "Đã kết thúc" }));
      var dur = s.start_at && s.end_at ? duration(s.start_at, s.end_at) : null;
      if (dur) parts.push(h("span", { text: "dài " + dur }));
    }
    return meta(parts);
  }
  /* Live or upcoming takes the stage above the lead: it is the one thing that cannot wait. */
  function renderStage(d) {
    var sec = clear($("now-live"));
    var on = d.live.filter(function (s) { return s.status === "live"; })
      .concat(d.live.filter(function (s) { return s.status === "upcoming"; })
        .sort(function (a, b) { return Date.parse(a.start_at || 0) - Date.parse(b.start_at || 0); }));
    if (!on.length) { sec.hidden = true; return []; }
    var s = on[0], isLive = s.status === "live";
    sec.hidden = false;
    add(sec,
      h("h2", { id: "now-live-h", class: "stage__label" },
        isLive ? h("span", { class: "stage__dot", "aria-hidden": "true" }) : null,
        isLive ? "Đang phát trực tiếp" : "Sắp phát trực tiếp"),
      player(s, false),
      h("h3", { class: "stage__title" }, h("a", { href: safeUrl(s.url), target: "_blank", rel: "noopener", text: s.title })),
      streamMeta(s)
    );
    return [s];
  }
  function renderStreams(d, onStage) {
    var box = clear($("streams"));
    var rest = d.live.filter(function (s) { return onStage.indexOf(s) < 0; })
      .sort(function (a, b) {
        var o = { live: 0, upcoming: 1, ended: 2 };
        return o[a.status] - o[b.status] || Date.parse(b.end_at || b.start_at || 0) - Date.parse(a.end_at || a.start_at || 0);
      });
    if (onStage.length) {
      box.appendChild(h("p", { class: "empty" }, onStage[0].status === "live" ? "Buổi đang phát nằm ở " : "Buổi sắp phát nằm ở ",
        h("a", { class: "textlink", href: "#now-live", text: "đầu trang" }), "."));
    }
    var yt = d.sources.filter(function (s) { return s.kind === "youtube"; });
    var ytDown = yt.filter(function (s) { return !s.ok; });
    if (!rest.length && !onStage.length) {
      box.appendChild(empty(yt.length && ytDown.length === yt.length
        ? "Lần này không đọc được kênh YouTube nào, nên chưa biết có buổi phát trực tiếp nào không."
        : "Không có buổi phát trực tiếp nào trong 7 ngày qua. Khi một phòng lab lên sóng, buổi đó sẽ hiện ở đầu trang."));
    }
    if (rest.length) {
      var ul = h("ul", { class: "reruns" });
      rest.forEach(function (s) {
        var row = h("article", { class: "rerun" });
        var thumb = safeUrl(s.thumbnail) ? h("img", { class: "rerun__thumb", src: s.thumbnail, alt: "", loading: "lazy", decoding: "async" }) : h("span");
        var label = s.status === "ended" ? null : h("span", { class: "new", text: s.status === "live" ? "Đang phát" : "Sắp phát" });
        var watch = h("button", {
          type: "button", class: "btn btn--quiet",
          onclick: function () {
            var p = player(s, true);
            row.replaceChild(p, thumb);
            watch.hidden = true;
            var f = p.querySelector("iframe");
            if (f) f.focus();
          }
        }, s.status === "ended" ? "Xem lại tại đây" : "Xem tại đây");
        add(row, thumb, h("div", null,
          streamMeta(s, label),
          h("h3", { class: "rerun__title", text: s.title }),
          h("div", { class: "rerun__actions" }, watch,
            safeUrl(s.url) ? h("a", { class: "textlink", href: s.url, target: "_blank", rel: "noopener", text: "Mở trên YouTube" }) : null)
        ));
        ul.appendChild(h("li", null, row));
      });
      box.appendChild(ul);
    }
    if (ytDown.length && ytDown.length < yt.length) {
      box.appendChild(h("p", { class: "meta" }, h("span", {
        text: "Không đọc được: " + ytDown.map(function (s) { return s.name; }).join(", ") + ". Buổi phát của " +
          (ytDown.length > 1 ? "các kênh này" : "kênh này") + " có thể bị thiếu."
      })));
    }
  }

  /* ---------- lead story ---------- */
  function renderLead(lead) {
    var sec = clear($("lead"));
    if (!lead) { sec.hidden = true; return; }
    var u = lead.item;
    sec.hidden = false;
    var host = "";
    try { host = new URL(u.url).hostname.replace(/^www\./, ""); } catch (e) { /* keep empty */ }
    add(sec,
      h("h2", { id: "lead-h", class: "kicker", text: lead.fresh ? "Đáng chú ý nhất" : "Đáng chú ý nhất 48 giờ qua" }),
      meta([
        lead.fresh ? newTag() : null,
        h("span", { class: "lab", text: labName(u.lab) }),
        KIND[u.kind] ? h("span", { text: KIND[u.kind] }) : null,
        timeEl(u.published_at)
      ]),
      h("p", { class: "lead__title" }, h("a", { href: safeUrl(u.url), target: "_blank", rel: "noopener", text: u.title })),
      u.summary ? h("p", { class: "lead__sum", text: u.summary }) : null,
      safeUrl(u.url) ? h("a", { class: "lead__link", href: u.url, target: "_blank", rel: "noopener" },
        "Đọc bài gốc" + (host ? " tại " + host : ""), h("span", { "aria-hidden": "true", text: "→" })) : null
    );
  }

  /* ---------- the feed: unseen first, then the bookmark, then a few already seen ---------- */
  function renderFilters(d) {
    var box = clear($("filters"));
    var present = {};
    d.updates.forEach(function (u) { present[u.lab] = true; });
    var labs = LAB_ORDER.filter(function (l) { return present[l]; });
    Object.keys(present).forEach(function (l) { if (labs.indexOf(l) < 0) labs.push(l); });
    if (labs.length < 2) return;
    [null].concat(labs).forEach(function (l) {
      box.appendChild(h("button", {
        type: "button", class: "chip", "aria-pressed": String(state.lab === l),
        text: l === null ? "Tất cả" : labName(l),
        onclick: function () { state.lab = l; state.feedLimit = null; renderFilters(d); renderFeed(d); }
      }));
    });
  }
  function dayGroups(items) {
    var groups = [], byKey = {};
    items.forEach(function (u) {
      var ms = Date.parse(u.published_at), k = vn(ms).key;
      if (!byKey[k]) { byKey[k] = { ms: ms, items: [] }; groups.push(byKey[k]); }
      byKey[k].items.push(u);
    });
    return groups.map(function (g) {
      return h("section", { class: "day", "aria-label": dayLabel(g.ms) },
        h("h3", { class: "day__label", text: dayLabel(g.ms) }),
        h("div", { class: "day__col" }, h("ol", { class: "day__items" }, g.items.map(function (u) { return h("li", null, feedItem(u)); }))));
    });
  }
  function renderFeed(d) {
    var feed = clear($("feed"));
    var lead = state.lead && state.lead.item;
    var items = d.updates
      .filter(function (u) { return state.lab ? u.lab === state.lab : u !== lead; })
      .sort(byDateDesc("published_at"));
    var fresh = items.filter(isNewUpdate);
    var older = items.filter(function (u) { return !isNewUpdate(u); });
    var first = Math.min(Math.max(fresh.length, FEED_MIN), FEED_FIRST_MAX);
    var limit = Math.min(state.feedLimit || first, items.length);
    var showFresh = fresh.slice(0, limit);
    var showOlder = older.slice(0, Math.max(0, limit - showFresh.length));

    var fs = clear($("filter-state"));
    if (state.lab) {
      add(fs, "Đang lọc: chỉ tin " + labName(state.lab) + ". ",
        h("button", { type: "button", text: "Bỏ lọc", onclick: function () { state.lab = null; state.feedLimit = null; renderFilters(d); renderFeed(d); } }));
      fs.hidden = false;
    } else fs.hidden = true;

    if (!items.length) {
      feed.appendChild(empty(state.lab ? "Chưa có tin nào của " + labName(state.lab) + "." : "Chưa lấy được tin nào từ các phòng lab."));
    } else if (!fresh.length && state.lab) {
      feed.appendChild(empty("Không có tin mới của " + labName(state.lab) + ". Dưới đây là những tin anh đã xem."));
    }
    dayGroups(showFresh).forEach(function (g) { feed.appendChild(g); });
    if (showOlder.length) {
      feed.appendChild(h("p", { class: "bookmark", role: "separator" }, firstVisit()
        ? "Trên đây là 24 giờ qua"
        : state.baseline !== null ? "Anh đã xem những tin dưới đây, lần trước lúc " + whenPhrase(state.baseline) : "Anh đã xem những tin dưới đây"));
      dayGroups(showOlder).forEach(function (g) { feed.appendChild(g); });
    }

    var more = clear($("feed-more")), remaining = items.length - limit;
    if (remaining > 0) {
      more.appendChild(h("button", {
        type: "button", class: "btn btn--quiet",
        text: "Xem thêm " + Math.min(FEED_STEP, remaining) + " tin cũ hơn (còn " + remaining + ")",
        onclick: function () { state.feedLimit = limit + FEED_STEP; renderFeed(d); }
      }));
    }
    if (limit > first) {
      more.appendChild(h("button", {
        type: "button", class: "btn btn--quiet", text: "Thu gọn",
        onclick: function () { state.feedLimit = null; renderFeed(d); $("tin").scrollIntoView(); }
      }));
    }
    more.hidden = !more.children.length;
  }
  function feedItem(u) {
    var fresh = isNewUpdate(u);
    return h("article", { class: "item" + (fresh ? " is-new" : "") },
      meta([
        fresh ? newTag() : null,
        h("span", { class: "lab", text: labName(u.lab) }),
        KIND[u.kind] ? h("span", { text: KIND[u.kind] }) : null,
        timeEl(u.published_at)
      ]),
      h("h4", { class: "item__title" }, h("a", { href: safeUrl(u.url), target: "_blank", rel: "noopener", text: u.title })),
      u.summary ? h("p", { class: "item__sum", text: u.summary }) : null
    );
  }

  /* ---------- short side lists: five, then ten more at a time ---------- */
  function sideMore(boxId, name, total, rerender) {
    var box = clear($(boxId)), shown = Math.min(state.limits[name], total);
    if (total > shown) {
      box.appendChild(h("button", {
        type: "button", class: "btn btn--quiet",
        text: "Xem thêm " + Math.min(SIDE_STEP, total - shown) + " (còn " + (total - shown) + ")",
        onclick: function () { state.limits[name] = shown + SIDE_STEP; rerender(); }
      }));
    }
    if (shown > SIDE_SHORT) {
      box.appendChild(h("button", {
        type: "button", class: "btn btn--quiet", text: "Thu gọn",
        onclick: function () { state.limits[name] = SIDE_SHORT; rerender(); }
      }));
    }
    box.hidden = !box.children.length;
    return shown;
  }
  function repoName(id, url) {
    var parts = id.split("/");
    return h("a", { href: safeUrl(url), target: "_blank", rel: "noopener" },
      parts.length > 1 ? [h("span", { class: "owner", text: parts[0] + "/" }), parts.slice(1).join("/")] : [id]);
  }

  function renderReleases(d) {
    var ol = clear($("releases"));
    /* Unseen releases first, then the newest. */
    var rows = d.hf_releases.slice().sort(function (a, b) {
      return (isNewRelease(b) ? 1 : 0) - (isNewRelease(a) ? 1 : 0) || Date.parse(b.created_at) - Date.parse(a.created_at);
    });
    if (!rows.length) {
      ol.appendChild(h("li", null, empty(d.sources.some(function (s) { return s.kind === "hf" && !s.ok; })
        ? "Lần này không đọc được Hugging Face." : "Chưa thấy mô hình mở mới nào.")));
    }
    var shown = sideMore("releases-more", "releases", rows.length, function () { renderReleases(d); });
    rows.slice(0, shown).forEach(function (r) {
      ol.appendChild(h("li", null,
        h("p", { class: "ledger__name" }, repoName(r.id, r.url)),
        meta([
          isNewRelease(r) ? newTag() : null,
          h("span", { class: "lab", text: labName(r.lab) }),
          r.pipeline_tag ? h("span", { text: r.pipeline_tag }) : null,
          h("span", null, "đăng ", timeEl(r.created_at)),
          typeof r.likes === "number" ? h("span", { class: "num", text: n(r.likes) + " lượt thích" }) : null,
          typeof r.downloads === "number" ? h("span", { class: "num", text: n(r.downloads) + " lượt tải" }) : null
        ])
      ));
    });
  }

  function renderTrending(d) {
    var ghRows = (d.trending && d.trending.github) || [];
    var hfRows = (d.trending && d.trending.huggingface) || [];
    renderRanked("gh", ghRows, "Lần này không đọc được GitHub Trending.", function (r) {
      return [
        h("p", { class: "ranked__name" }, repoName(r.repo, r.url)),
        r.description ? h("p", { class: "ranked__desc", text: r.description }) : null,
        meta([
          r.language ? h("span", { text: r.language }) : null,
          typeof r.stars_today === "number" && r.stars_today > 0 ? h("span", { class: "num", text: "+" + n(r.stars_today) + " sao hôm nay" }) : null,
          typeof r.stars === "number" ? h("span", { class: "num", text: n(r.stars) + " sao" }) : null
        ])
      ];
    }, d);
    renderRanked("hf", hfRows, "Lần này không đọc được Hugging Face Trending.", function (r) {
      return [
        h("p", { class: "ranked__name" }, repoName(r.id, r.url)),
        meta([
          HF_TYPE[r.type] ? h("span", { text: HF_TYPE[r.type] }) : null,
          r.pipeline_tag ? h("span", { text: r.pipeline_tag }) : null,
          typeof r.likes === "number" ? h("span", { class: "num", text: n(r.likes) + " lượt thích" }) : null
        ])
      ];
    }, d);
  }
  function renderRanked(name, rows, emptyText, body, d) {
    var ol = clear($(name));
    if (!rows.length) ol.appendChild(h("li", { class: "is-empty" }, empty(emptyText)));
    var shown = sideMore(name + "-more", name, rows.length, function () { renderTrending(d); });
    rows.slice(0, shown).forEach(function (r) { ol.appendChild(h("li", null, h("div", null, body(r)))); });
  }

  /* ---------- colophon ---------- */
  function renderSources(d) {
    $("generated").textContent = "Cập nhật lúc " + fullTime(d.generated_at) + ", " + relTime(d.generated_at) + ".";
    var ul = clear($("sources"));
    d.sources.forEach(function (s) {
      ul.appendChild(h("li", null,
        h("span", { class: "src-name", text: s.name }), " ",
        s.ok ? h("span", { class: "num", text: n(s.count) + " mục" }) : h("span", { class: "is-down", text: "không đọc được" })
      ));
    });
  }

  function render() {
    var d = state.data;
    state.now = Date.now();
    state.lead = pickLead(d.updates);
    renderNotice(d);
    renderLede(d);
    var onStage = renderStage(d);
    renderLead(state.lead);
    renderFilters(d);
    renderFeed(d);
    renderStreams(d, onStage);
    renderTrending(d);
    renderReleases(d);
    renderSources(d);
  }

  function normalise(d) {
    d = d || {};
    d.sources = Array.isArray(d.sources) ? d.sources : [];
    d.updates = (Array.isArray(d.updates) ? d.updates : []).filter(function (u) { return u && u.title && !isNaN(Date.parse(u.published_at)); });
    d.hf_releases = (Array.isArray(d.hf_releases) ? d.hf_releases : []).filter(function (r) { return r && r.id && !isNaN(Date.parse(r.created_at)); });
    d.live = (Array.isArray(d.live) ? d.live : []).filter(function (s) { return s && s.video_id && s.title; });
    d.trending = d.trending || {};
    if (isNaN(Date.parse(d.generated_at))) d.generated_at = new Date().toISOString();
    return d;
  }

  function fail(err) {
    $("lede").textContent = "Chưa mở được bản tin.";
    var sub = $("lede-sub");
    sub.textContent = "Không tải được data/radar.json (" + (err && err.message ? err.message : "lỗi không rõ") + "). Kiểm tra máy chủ rồi thử lại.";
    sub.hidden = false;
    var act = clear($("lede-actions"));
    act.appendChild(h("button", { type: "button", class: "btn", text: "Thử lại", onclick: function () { location.reload(); } }));
    act.hidden = false;
    document.querySelectorAll(".page .section, .toc, .colophon").forEach(function (el) { el.hidden = true; });
  }

  $("mark-read").addEventListener("click", function () {
    markAllRead();
    state.feedLimit = null;
    render();
    $("lede").focus();
  });

  renderToday();
  fetch("data/radar.json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) {
      state.data = normalise(d);
      establishBaseline(state.data);
      render();
    })
    .catch(fail);

  /* Keep relative times honest if the tab stays open. */
  setInterval(function () { if (state.data) { state.now = Date.now(); renderLede(state.data); } }, 5 * 60e3);
})();
