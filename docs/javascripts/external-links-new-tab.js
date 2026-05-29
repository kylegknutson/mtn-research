// Make every external link in a peak report (or any docs page) open in a new tab.
// Uses Material's document$ observable so this re-runs on instant navigation, not
// just initial page load.
//
// "External" = absolute http/https URL whose origin differs from the docs site.
// Internal navigation (peak↔peak links, anchors) keeps default same-tab behavior.

(function () {
  function markExternalLinks() {
    document.querySelectorAll('a[href^="http://"], a[href^="https://"]').forEach(function (link) {
      try {
        if (link.host && link.host !== window.location.host) {
          link.setAttribute('target', '_blank');
          link.setAttribute('rel', 'noopener noreferrer');
        }
      } catch (e) {
        // Ignore malformed URLs
      }
    });
  }

  // Material for MkDocs exposes a document$ observable. Subscribe so this runs
  // after every instant-navigation render. Fall back to DOMContentLoaded.
  if (typeof document$ !== 'undefined' && document$.subscribe) {
    document$.subscribe(markExternalLinks);
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', markExternalLinks);
  } else {
    markExternalLinks();
  }
})();
