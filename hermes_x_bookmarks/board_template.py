"""The self-contained ``board.html`` page. ``__XBM_DATA__`` is replaced with the bookmarks JSON.

Every post string is put into the page with ``textContent``; links are http(s) only. Done marks
and view settings live in this browser's localStorage (wrapped in try/catch).
"""

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>X Bookmarks</title>
<style>
:root {
  --bg: #f6f6f3; --panel: #ffffff; --col: #ecece7; --ink: #1d1d1b; --muted: #6b6b66;
  --line: #dcdcd5; --accent: #1d6fd6; --chip: #f0f0eb; --p1: #c2410c; --p2: #8a6d1d; --p3: #7b7b74;
  --done: #3f8f4f; --shadow: 0 1px 2px rgba(0,0,0,.06);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141413; --panel: #1f1f1d; --col: #191917; --ink: #ececea; --muted: #9c9c96;
    --line: #33332f; --accent: #6ea8ff; --chip: #2a2a27; --p1: #fb923c; --p2: #d6b656; --p3: #9c9c96;
    --done: #6cc47d; --shadow: none;
  }
}
:root[data-theme="dark"] {
  --bg: #141413; --panel: #1f1f1d; --col: #191917; --ink: #ececea; --muted: #9c9c96;
  --line: #33332f; --accent: #6ea8ff; --chip: #2a2a27; --p1: #fb923c; --p2: #d6b656; --p3: #9c9c96;
  --done: #6cc47d; --shadow: none;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header { padding: 16px 16px 8px; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; }
h1 { font-size: 20px; margin: 0; letter-spacing: -.01em; }
.meta { color: var(--muted); font-size: 13px; }
.bar { display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 16px 12px; align-items: center;
  position: sticky; top: 0; background: var(--bg); z-index: 2; border-bottom: 1px solid var(--line); }
.bar input[type=search] { flex: 1 1 220px; min-width: 0; }
.bar input, .bar select, .bar button { font: inherit; color: var(--ink); background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; padding: 6px 9px; }
.bar label { display: inline-flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; }
.bar .count { color: var(--muted); font-size: 13px; margin-left: auto; }
.board { display: flex; gap: 12px; padding: 12px 16px 24px; overflow-x: auto; align-items: flex-start;
  scroll-snap-type: x proximity; }
.column { flex: 0 0 320px; max-width: 86vw; background: var(--col); border-radius: 12px; padding: 10px;
  scroll-snap-align: start; }
.column h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
  margin: 2px 4px 10px; display: flex; justify-content: space-between; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 11px;
  margin-bottom: 8px; box-shadow: var(--shadow); }
.card.done { opacity: .55; }
.top { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; color: var(--muted); font-size: 12px; }
.top .who { color: var(--ink); font-weight: 600; }
.badge { font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; }
.title { font-weight: 600; margin: 6px 0 4px; overflow-wrap: anywhere; }
.summary { margin: 0 0 6px; overflow-wrap: anywhere; }
.text { color: var(--muted); font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; margin: 0; }
.card.open .text { -webkit-line-clamp: unset; display: block; }
.extra { display: none; margin-top: 8px; font-size: 13px; }
.card.open .extra { display: block; }
.extra p { margin: 4px 0; overflow-wrap: anywhere; }
.extra a { color: var(--accent); }
.thumb { width: 100%; max-height: 180px; object-fit: cover; border-radius: 8px; margin-top: 8px;
  background: var(--chip); display: block; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.tag { background: var(--chip); border: 0; color: var(--ink); border-radius: 999px; padding: 1px 8px;
  font: inherit; font-size: 12px; cursor: pointer; }
.foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px; }
.prio { font-weight: 700; }
.prio.p1 { color: var(--p1); } .prio.p2 { color: var(--p2); } .prio.p3 { color: var(--p3); }
.foot a { color: var(--accent); text-decoration: none; margin-left: auto; }
.foot a:hover { text-decoration: underline; }
.foot label { display: inline-flex; gap: 4px; align-items: center; color: var(--muted); cursor: pointer; }
.more { all: unset; cursor: pointer; color: var(--accent); font-size: 12px; }
.showmore { width: 100%; font: inherit; padding: 7px; border-radius: 8px; border: 1px dashed var(--line);
  background: transparent; color: var(--muted); cursor: pointer; }
.empty { color: var(--muted); padding: 24px 16px; }
@media (max-width: 640px) {
  .board { flex-direction: column; overflow-x: visible; }
  .column { flex: 1 1 auto; max-width: none; width: 100%; }
}
</style>
</head>
<body>
<header>
  <h1>X Bookmarks</h1>
  <span class="meta" id="meta"></span>
</header>
<div class="bar">
  <input type="search" id="q" placeholder="Search text, summary, tags, @author" aria-label="Search">
  <select id="category" aria-label="Category"></select>
  <select id="kind" aria-label="Kind"></select>
  <select id="priority" aria-label="Priority">
    <option value="">Any priority</option><option value="1">p1 only</option>
    <option value="2">p1 and p2</option>
  </select>
  <label>Columns
    <select id="group" aria-label="Columns by">
      <option value="category">category</option><option value="kind">kind</option>
      <option value="priority">priority</option>
    </select>
  </label>
  <label><input type="checkbox" id="showdone"> show done</label>
  <label><input type="checkbox" id="images" checked> images</label>
  <span class="count" id="count"></span>
</div>
<main class="board" id="board"></main>
<script type="application/json" id="xbm-data">__XBM_DATA__</script>
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("xbm-data").textContent);
  var CARDS = DATA.cards;
  var PAGE = 60;
  var KIND_ORDER = ["read", "try", "task", "post-idea", "reference", "skill-candidate", ""];
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem("xbm:" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem("xbm:" + k, JSON.stringify(v)); } catch (e) {} }
  };
  var done = store.get("done", {});
  var shown = {};
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== "") n.textContent = text;
    return n;
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : ""; }
  function countBy(key) {
    var m = {};
    CARDS.forEach(function (c) { m[c[key]] = (m[c[key]] || 0) + 1; });
    return m;
  }
  function fillSelect(sel, label, counts, order) {
    sel.appendChild(new Option(label, ""));
    order.forEach(function (k) { if (k) sel.appendChild(new Option(k + " (" + counts[k] + ")", k)); });
  }

  var cats = countBy("category");
  fillSelect($("category"), "All categories", cats,
    Object.keys(cats).sort(function (a, b) { return cats[b] - cats[a] || a.localeCompare(b); }));
  var kinds = countBy("kind");
  fillSelect($("kind"), "All kinds", kinds, KIND_ORDER.filter(function (k) { return kinds[k]; }));
  $("meta").textContent = CARDS.length + " bookmarks" + (DATA.owner ? " of @" + DATA.owner : "") +
    " · exported " + DATA.generated;

  var prefs = store.get("prefs", {});
  ["category", "kind", "priority", "group"].forEach(function (id) {
    if (prefs[id] !== undefined && Array.prototype.some.call($(id).options, function (o) { return o.value === prefs[id]; })) {
      $(id).value = prefs[id];
    }
  });
  $("showdone").checked = !!prefs.showdone;
  $("images").checked = prefs.images !== false;

  function matches(c, q) {
    if (!q) return true;
    var hay = [c.title, c.summary, c.text, c.why, c.quoted, "@" + c.author, c.tags.join(" "), c.category, c.kind]
      .join(" ").toLowerCase();
    return q.split(/\s+/).every(function (w) { return hay.indexOf(w) !== -1; });
  }
  function filtered() {
    var q = $("q").value.trim().toLowerCase(), cat = $("category").value, kind = $("kind").value,
        pr = +$("priority").value || 0, sd = $("showdone").checked;
    return CARDS.filter(function (c) {
      return (!cat || c.category === cat) && (!kind || c.kind === kind) &&
        (!pr || (c.priority && c.priority <= pr)) && (sd || !done[c.id]) && matches(c, q);
    });
  }
  function groupKey(c, g) {
    if (g === "priority") return c.priority ? "p" + c.priority : "unsorted";
    if (g === "kind") return c.kind || "unsorted";
    return c.category;
  }
  function groupOrder(keys, g, groups) {
    if (g === "priority") return ["p1", "p2", "p3", "unsorted"].filter(function (k) { return groups[k]; });
    if (g === "kind") return KIND_ORDER.map(function (k) { return k || "unsorted"; }).filter(function (k) { return groups[k]; });
    return keys.sort(function (a, b) { return groups[b].length - groups[a].length || a.localeCompare(b); });
  }

  function renderCard(c) {
    var card = el("article", "card" + (done[c.id] ? " done" : ""));
    var top = el("div", "top");
    top.appendChild(el("span", "who", "@" + (c.author || "?")));
    top.appendChild(el("span", "", c.date));
    if (c.article) top.appendChild(el("span", "badge", "Article"));
    if (c.thread) top.appendChild(el("span", "badge", "Thread"));
    card.appendChild(top);
    var title = c.title || c.summary || c.text.slice(0, 140) || "(media only)";
    card.appendChild(el("div", "title", title));
    if (c.title && c.summary) card.appendChild(el("p", "summary", c.summary));
    if (c.text && c.text !== title) card.appendChild(el("p", "text", c.text));
    var extra = el("div", "extra");
    if (c.why) extra.appendChild(el("p", "", "Why saved: " + c.why));
    if (c.quoted) extra.appendChild(el("p", "", "Quotes @" + (c.quotedAuthor || "?") + ": " + c.quoted));
    c.links.forEach(function (u) {
      if (!safeUrl(u)) return;
      var p = el("p"), a = el("a", "", u);
      a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
      p.appendChild(a); extra.appendChild(p);
    });
    card.appendChild(extra);
    if (c.image && $("images").checked && safeUrl(c.image)) {
      var img = el("img", "thumb");
      img.loading = "lazy"; img.alt = ""; img.referrerPolicy = "no-referrer"; img.src = c.image;
      img.onerror = function () { img.remove(); };
      card.appendChild(img);
    }
    if (c.tags.length) {
      var tags = el("div", "tags");
      c.tags.forEach(function (t) {
        var b = el("button", "tag", "#" + t);
        b.type = "button";
        b.onclick = function () { $("q").value = t; render(); };
        tags.appendChild(b);
      });
      card.appendChild(tags);
    }
    var foot = el("div", "foot");
    if (c.priority) foot.appendChild(el("span", "prio p" + c.priority, "p" + c.priority));
    if (c.kind) foot.appendChild(el("span", "badge", c.kind));
    var more = el("button", "more", "more");
    more.type = "button";
    more.onclick = function () { card.classList.toggle("open"); more.textContent = card.classList.contains("open") ? "less" : "more"; };
    foot.appendChild(more);
    var lab = el("label"), cb = el("input");
    cb.type = "checkbox"; cb.checked = !!done[c.id];
    cb.onchange = function () {
      if (cb.checked) done[c.id] = 1; else delete done[c.id];
      store.set("done", done);
      card.classList.toggle("done", cb.checked);
    };
    lab.appendChild(cb); lab.appendChild(document.createTextNode("done"));
    foot.appendChild(lab);
    if (safeUrl(c.url)) {
      var a = el("a", "", "Open on X ↗");
      a.href = c.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      foot.appendChild(a);
    }
    card.appendChild(foot);
    return card;
  }

  function render() {
    var g = $("group").value, list = filtered(), groups = {};
    store.set("prefs", { category: $("category").value, kind: $("kind").value, priority: $("priority").value,
      group: g, showdone: $("showdone").checked, images: $("images").checked });
    list.forEach(function (c) { var k = groupKey(c, g); (groups[k] = groups[k] || []).push(c); });
    if (g !== "priority") Object.keys(groups).forEach(function (k) {
      groups[k].sort(function (a, b) { return (a.priority || 9) - (b.priority || 9); });
    });
    var board = $("board");
    board.textContent = "";
    $("count").textContent = "Showing " + list.length + " of " + CARDS.length;
    if (!list.length) { board.appendChild(el("p", "empty", "Nothing matches these filters.")); return; }
    groupOrder(Object.keys(groups), g, groups).forEach(function (k) {
      var col = el("section", "column"), h = el("h2");
      h.appendChild(el("span", "", k));
      h.appendChild(el("span", "", String(groups[k].length)));
      col.appendChild(h);
      var limit = shown[g + ":" + k] || PAGE;
      groups[k].slice(0, limit).forEach(function (c) { col.appendChild(renderCard(c)); });
      if (groups[k].length > limit) {
        var b = el("button", "showmore", "Show " + Math.min(PAGE, groups[k].length - limit) + " more");
        b.type = "button";
        b.onclick = function () { shown[g + ":" + k] = limit + PAGE; render(); };
        col.appendChild(b);
      }
      board.appendChild(col);
    });
  }

  var timer;
  $("q").addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(render, 150); });
  ["category", "kind", "priority", "group", "showdone", "images"].forEach(function (id) {
    $(id).addEventListener("change", render);
  });
  render();
})();
</script>
</body>
</html>
"""
