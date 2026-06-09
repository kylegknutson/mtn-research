/* Interactive peak map — every ranked CO 13er/14er, by status:
     green CalTopo peak icon = has a report (click -> report)
     grey dot              = already climbed
     red dot               = unclimbed, no report yet
   Data: scripts/gen_peak_map.py -> docs/data/peaks.json
   Paths resolve from this script's own URL, so they work on any page and survive
   Material instant nav. */
(function () {
  var BASE = (function () {
    var s = document.currentScript ||
      document.querySelector('script[src*="peak-map.js"]');
    return s ? s.src.replace(/javascripts\/peak-map\.js(\?.*)?$/, "") : "";
  })();

  // CalTopo-style green peak marker (neon green #39FF14 fill, dark outline).
  var PEAK_ICON = null;
  function peakIcon() {
    if (!PEAK_ICON && typeof L !== "undefined") {
      PEAK_ICON = L.divIcon({
        className: "peak-marker",
        html: '<svg width="24" height="22" viewBox="0 0 24 22" aria-hidden="true">' +
              '<path d="M12 2 L22.5 20.5 L1.5 20.5 Z" fill="#39FF14" stroke="#0b3d0b" ' +
              'stroke-width="2.5" stroke-linejoin="round"/></svg>',
        iconSize: [24, 22], iconAnchor: [12, 20], popupAnchor: [0, -18]
      });
    }
    return PEAK_ICON;
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

    var canvas = L.canvas({ padding: 0.5 });   // fast rendering for the dot layers

    fetch(BASE + "data/peaks.json").then(function (r) { return r.json(); }).then(function (d) {
      var reported = L.layerGroup();
      var climbed = L.layerGroup();
      var todo = L.layerGroup();
      var allBounds = [];

      function meta(p) {
        return "<b>" + p.n + "</b> " + (p.ft ? p.ft.toLocaleString() + "'" : "") +
          "<br>" + (p.f ? "14er" : "13er") + (p.r ? " · CO rank " + p.r : "") +
          "<br><span style='color:#666'>" + p.rng + "</span>";
      }

      d.peaks.forEach(function (p) {
        allBounds.push([p.lat, p.lon]);
        if (p.s === "rep") {
          var url = BASE + p.u;
          var m = L.marker([p.lat, p.lon], { icon: peakIcon(), title: p.n + " — report" });
          m.bindPopup(meta(p) + "<br><a href='" + url + "'><b>Open report →</b></a>");
          m.on("click", function () { /* popup opens; link inside navigates */ });
          m.addTo(reported);
        } else if (p.s === "done") {
          L.circleMarker([p.lat, p.lon], {
            renderer: canvas, radius: p.f ? 4.5 : 3.5,
            color: "#5b5b5b", weight: 1, fillColor: "#9e9e9e", fillOpacity: 0.75
          }).bindPopup(meta(p) + "<br><i style='color:#777'>climbed ✓</i>").addTo(climbed);
        } else {
          L.circleMarker([p.lat, p.lon], {
            renderer: canvas, radius: p.f ? 5 : 4,
            color: "#8e1b1b", weight: 1, fillColor: "#e53935", fillOpacity: 0.85
          }).bindPopup(meta(p) + "<br><i style='color:#b00'>no report yet</i>").addTo(todo);
        }
      });

      // draw order: climbed (bottom) -> todo -> reported (top)
      climbed.addTo(map); todo.addTo(map); reported.addTo(map);

      var c = d.counts || {};
      var overlays = {};
      overlays["▲ Reported (" + (c.with_report || 0) + ")"] = reported;
      overlays["● To do (" + (c.todo || 0) + ")"] = todo;
      overlays["● Climbed (" + (c.climbed || 0) + ")"] = climbed;
      L.control.layers({ "Topo": topo, "Light": light }, overlays,
        { position: "topright", collapsed: false }).addTo(map);

      if (allBounds.length) map.fitBounds(allBounds, { padding: [30, 30] });

      var lg = L.control({ position: "bottomleft" });
      lg.onAdd = function () {
        var div = L.DomUtil.create("div", "peakmap-legend");
        div.innerHTML =
          "<span class='pk'></span> Has report &nbsp; " +
          "<span class='dot todo'></span> To do &nbsp; " +
          "<span class='dot done'></span> Climbed";
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
