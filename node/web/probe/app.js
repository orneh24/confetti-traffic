/* Pervium probe site - shared script. Fixed content: see index.html.
 *
 * The HTTP test never runs this; it only checks that the file arrives
 * byte for byte. It exists so the fetch includes a real JavaScript file,
 * which some inspection engines treat differently from HTML. When a person
 * opens the site in a browser it marks the page as having run its script
 * and adds simple sorting to the report table.
 */
(function () {
  "use strict";

  function markRan() {
    var el = document.getElementById("script-status");
    if (!el) return;
    el.textContent = "The script ran: this page loaded its JavaScript.";
    el.className = "ran";
  }

  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    var text = cell.textContent.trim();
    var num = parseFloat(text.replace(/[^0-9.\-]/g, ""));
    return isNaN(num) || cell.className.indexOf("num") === -1 ? text.toLowerCase() : num;
  }

  function sortTable(table, index, ascending) {
    var body = table.tBodies[0];
    if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (a, b) {
      var x = cellValue(a, index);
      var y = cellValue(b, index);
      if (x < y) return ascending ? -1 : 1;
      if (x > y) return ascending ? 1 : -1;
      return 0;
    });
    for (var i = 0; i < rows.length; i++) {
      body.appendChild(rows[i]);
    }
  }

  function makeSortable(table) {
    var head = table.tHead;
    if (!head || !head.rows.length) return;
    var cells = head.rows[0].cells;
    for (var i = 0; i < cells.length; i++) {
      (function (index, th) {
        var ascending = true;
        th.style.cursor = "pointer";
        th.title = "Sort by this column";
        th.addEventListener("click", function () {
          sortTable(table, index, ascending);
          ascending = !ascending;
        });
      })(i, cells[i]);
    }
  }

  function init() {
    markRan();
    var tables = document.querySelectorAll("table.report");
    for (var i = 0; i < tables.length; i++) {
      makeSortable(tables[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
