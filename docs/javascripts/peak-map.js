/* Interactive peak map — every ranked CO 13er/14er as a CalTopo-style peak icon,
   colored by status:
     green (#39FF14) = has a report   (hover = peak + report name; click -> report)
     red   (#e53935) = unclimbed, no report yet
     grey  (#b8b8b8) = already climbed
   Data: scripts/gen_peak_map.py -> docs/data/peaks.json
   Paths resolve from this script's own URL, so they work on any page and survive
   Material instant nav. */
(function () {
  var BASE = (function () {
    var s = document.currentScript ||
      document.querySelector('script[src*="peak-map.js"]');
    return s ? s.src.replace(/javascripts\/peak-map\.js(\?.*)?$/, "") : "";
  })();

  // Cache one divIcon per (color,size) — reused across all markers of a status.
  var ICONS = {};
  function peakIcon(key, fill, stroke, w) {
    if (!ICONS[key] && typeof L !== "undefined") {
      var h = Math.round(w * 0.92);
      ICONS[key] = L.divIcon({
        className: "peak-marker",
        html: '<svg width="' + w + '" height="' + h + '" viewBox="0 0 24 22" aria-hidden="true">' +
              '<path d="M12 2 L22.5 20.5 L1.5 20.5 Z" fill="' + fill + '" stroke="' + stroke +
              '" stroke-width="2.5" stroke-linejoin="round"/></svg>',
        iconSize: [w, h], iconAnchor: [w / 2, h - 1],
        popupAnchor: [0, -h + 2], tooltipAnchor: [0, -h + 4]
      });
    }
    return ICONS[key];
  }

  function init() {
    var el = document.getElementById("peak-map");
    if (!el || el.dataset.ready === "1") return;
    if (typeof L === "undefined") return;
    el.dataset.ready = "1";

    var map = L.map(el, { scrollWheelZoom: true, tap: false });
    var topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
      maxZoom: 17, attribution: "© OpenTopoMap (CC-BY-SA) | SRTM"
    });
    var light = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap, © CARTO"
    });
    topo.addTo(map);
    map.setView([39.0, -106.3], 7);

    fetch(BASE + "data/peaks.json").then(function (r) { return r.json(); }).then(function (d) {
      var reported = L.layerGroup();
      var climbed = L.layerGroup();
      var todo = L.layerGroup();
      var allBounds = [];

      function info(p) {
        return "<b>" + p.n + "</b> " + (p.ft ? p.ft.toLocaleString() + "'" : "") +
          "<br>" + (p.f ? "14er" : "13er") + (p.r ? " · CO rank " + p.r : "") +
          "<br><span style='color:#666'>" + p.rng + "</span>";
      }
      function esc(s) { return (s || "").replace(/</g, "&lt;"); }

      d.peaks.forEach(function (p) {
        allBounds.push([p.lat, p.lon]);
        var icon, layer, tip, popupExtra;
        if (p.s === "rep") {
          icon = peakIcon("rep", "#39FF14", "#0b3d0b", 24);
          layer = reported;
          tip = "<b>" + esc(p.n) + "</b><br><span style='color:#2a7d2a'>▸ " + esc(p.t) + "</span>";
          popupExtra = "<br><a href='" + BASE + p.u + "'><b>Open report →</b></a>";
        } else if (p.s === "done") {
          icon = peakIcon("done", "#b8b8b8", "#5b5b5b", 15);
          layer = climbed;
          if (p.u) {   // climbed AND has a report → grey, but keep the report link
            tip = "<b>" + esc(p.n) + "</b> · climbed ✓<br><span style='color:#2a7d2a'>▸ " + esc(p.t) + "</span>";
            popupExtra = "<br><i style='color:#777'>climbed ✓</i><br><a href='" + BASE + p.u + "'><b>Open report →</b></a>";
          } else {
            tip = "<b>" + esc(p.n) + "</b> · climbed ✓";
            popupExtra = "<br><i style='color:#777'>climbed ✓</i>";
          }
        } else {
          icon = peakIcon("todo", "#e53935", "#7a1414", 19);
          layer = todo;
          tip = "<b>" + esc(p.n) + "</b> · no report yet";
          popupExtra = "<br><i style='color:#b00'>no report yet</i>";
        }
        var m = L.marker([p.lat, p.lon], { icon: icon, riseOnHover: true });
        m.bindTooltip(tip, { direction: "top", opacity: 0.95 });
        m.bindPopup(info(p) + popupExtra);
        m.addTo(layer);
      });

      // draw order: climbed (bottom) -> todo -> reported (top)
      climbed.addTo(map); todo.addTo(map); reported.addTo(map);

      var c = d.counts || {};
      function tri(fill, stroke) {
        return '<span style="color:' + fill + ';-webkit-text-stroke:0.6px ' + stroke +
               ';text-shadow:0 0 1px ' + stroke + '">▲</span>';
      }
      var overlays = {};
      overlays[tri("#39FF14", "#0b3d0b") + " Reported (" + (c.green || 0) + ")"] = reported;
      overlays[tri("#e53935", "#7a1414") + " To do (" + (c.todo || 0) + ")"] = todo;
      overlays[tri("#b8b8b8", "#5b5b5b") + " Climbed (" + (c.climbed || 0) + ")"] = climbed;
      L.control.layers({ "Topo": topo, "Light": light }, overlays,
        { position: "topright", collapsed: false }).addTo(map);

      if (allBounds.length) map.fitBounds(allBounds, { padding: [30, 30] });

      var lg = L.control({ position: "bottomleft" });
      lg.onAdd = function () {
        var div = L.DomUtil.create("div", "peakmap-legend");
        div.innerHTML =
          "<span class='pk rep'></span> Has report &nbsp; " +
          "<span class='pk todo'></span> To do &nbsp; " +
          "<span class='pk done'></span> Climbed";
        return div;
      };
      lg.addTo(map);
      setTimeout(function () { map.invalidateSize(); }, 150);
    }).catch(function (e) {
      el.innerHTML = "<p style='padding:1em;color:#a00'>Couldn't load peak data (" + e + ").</p>";
    });
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(function () { init(); });
  } else if (document.readyState !== "loading") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
