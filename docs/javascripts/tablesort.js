// Make content tables click-to-sort. Re-runs on Material instant navigation.
document$.subscribe(function () {
  document.querySelectorAll("article table:not([class])").forEach(function (table) {
    new Tablesort(table);
  });
});
