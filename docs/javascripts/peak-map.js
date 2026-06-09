/* Interactive peak map — every ranked CO 13er/14er, reported peaks highlighted.
   Data: scripts/gen_peak_map.py -> docs/data/peaks.json
   Container: <div id="peak-map"> (on home + /peak-map/). Paths are resolved from
   this script's own URL, so they work on any page and survive Material instant nav. */
(function () {
  // Absolute site base (e.g. https://host/mtn-research/), captured at load time.
  var BASE = (function () {
    var s = document.currentScript ||
      document.querySelector('script[src*="peak-map.js"]');
    return s ? s.src.replace(/javascripts\/peak-map\.js(\?.*)?$/, "") : "";
  })();

  function init() {
    var el = document.getElementById("peak-map");
    if (!el || el.dataset.ready === "1") return;
    if (typeof L === "undefined" || typeof L.markerClusterGroup === "undefined") return;
    el.dataset.ready = "1";

    var map = L.map(el, { scrollWheelZoom: true, tap: false });
    var topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
      maxZoom: 17, attribution: "© OpenTopoMap (CC-BY-SA) | SRTM"
    });
    var light = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap, © CARTO"
    });
    topo.addTo(map);
    map.setView([38.9, -106.3], 7);

    fetch(BASE + "data/peaks.json").then(function (r) { return r.json(); }).then(function (d) {
      var reported = L.layerGroup();
      var context = L.markerClusterGroup({
        chunkedLoading: true, maxClusterRadius: 50, disableClusteringAtZoom: 12,
        spiderfyOnMaxZoom: false
      });
      var repBounds = [];

      function popup(p, extra) {
        return "<b>" + p.n + "</b> " + (p.ft ? p.ft.toLocaleString() + "'" : "") +
          "<br>" + (p.f ? "14er" : "13er") + (p.r ? " · CO rank " + p.r : "") +
          "<br><span style='color:#666'>" + p.rng + "</span>" + extra;
      }

      d.peaks.forEach(function (p) {
        if (p.u) {
          var m = L.circleMarker([p.lat, p.lon], {
            radius: 7, color: "#0a6e26", weight: 2, fillColor: "#2ecc40", fillOpacity: 0.95
          });
          m.bindPopup(popup(p, "<br><a href='" + BASE + p.u + "'><b>Open report →</b></a>"));
          reported.addLayer(m);
          repBounds.push([p.lat, p.lon]);
        } else {
          var c = L.circleMarker([p.lat, p.lon], {
            radius: p.f ? 4 : 3, color: "#777", weight: 1,
            fillColor: p.f ? "#999" : "#c4c4c4", fillOpacity: 0.6
          });
          c.bindPopup(popup(p, "<br><i style='color:#999'>no report yet</i>"));
          context.addLayer(c);
        }
      });

      context.addTo(map);
      reported.addTo(map);
      L.control.layers(
        { "Topo": topo, "Light": light },
        { "Reported peaks": reported, "All ranked peaks": context },
        { position: "topright", collapsed: false }
      ).addTo(map);

      if (repBounds.length) map.fitBounds(repBounds, { padding: [50, 50], maxZoom: 10 });

      var c = d.counts || {};
      var lg = L.control({ position: "bottomleft" });
      lg.onAdd = function () {
        var div = L.DomUtil.create("div", "peakmap-legend");
        div.innerHTML =
          "<span class='dot rep'></span> Has report (" + (c.with_report || 0) + ") &nbsp; " +
          "<span class='dot ctx'></span> Ranked 13er/14er (" + (c.total || 0) + ")";
        return div;
      };
      lg.addTo(map);
      setTimeout(function () { map.invalidateSize(); }, 150);
    }).catch(function (e) {
      el.innerHTML = "<p style='padding:1em;color:#a00'>Couldn't load peak data (" + e + ").</p>";
    });
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(function () { init(); });   // Material instant nav
  } else if (document.readyState !== "loading") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
