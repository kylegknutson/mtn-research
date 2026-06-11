/* nav-stats.js — append a compact stat badge (e.g. "11 mi · 3,750′ · C2") under
   each report's left-nav link, from docs/data/report_stats.json (built by
   gen_index.py). Path resolves from this script's own URL, so it survives
   Material instant-navigation and any base path. */
(function () {
  var BASE = (function () {
    var s = document.currentScript ||
            document.querySelector('script[src*="nav-stats.js"]');
    return s ? s.src.replace(/javascripts\/nav-stats\.js(\?.*)?$/, "") : "";
  })();
  var STATS = null;

  function decorate() {
    if (!STATS) return;
    document.querySelectorAll("a.md-nav__link").forEach(function (a) {
      if (a.querySelector(".nav-stat")) return;            // already decorated
      var href = a.getAttribute("href");
      if (!href) return;
      var path;
      try { path = new URL(href, a.baseURI).pathname; } catch (e) { return; }
      for (var key in STATS) {
        if (path.endsWith(key)) {
          var span = document.createElement("span");
          span.className = "nav-stat";
          span.textContent = STATS[key];
          a.appendChild(span);
          break;
        }
      }
    });
  }

  function init() {
    if (STATS) { decorate(); return; }
    fetch(BASE + "data/report_stats.json")
      .then(function (r) { return r.json(); })
      .then(function (d) { STATS = d; decorate(); })
      .catch(function () { /* nav badges are best-effort */ });
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(function () { init(); });
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
