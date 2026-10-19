// Search, "low stock only" and sorting for the product table on the dashboard.
// Works on the rows already in the page. Without JavaScript the table is still
// complete: the search box is hidden until this file runs.
(function () {
  const table = document.getElementById("products");
  const tools = document.querySelector(".table-tools");
  if (!table || !tools) {
    return;
  }
  const body = table.tBodies[0];
  const rows = Array.from(body.rows).filter((row) => row.dataset.name !== undefined);
  const noMatch = body.querySelector("tr.no-match");
  const search = document.getElementById("q");
  const lowOnly = document.getElementById("low-only");
  const count = document.getElementById("count");
  const headers = Array.from(table.querySelectorAll("th[data-key]"));
  let sortKey = "name";
  let direction = 1;

  // Compare two rows by the current column. Price and stock are numbers.
  function compare(a, b) {
    if (sortKey === "price" || sortKey === "stock") {
      return (Number(a.dataset[sortKey]) - Number(b.dataset[sortKey])) * direction;
    }
    return a.dataset[sortKey].localeCompare(b.dataset[sortKey], undefined, { numeric: true }) * direction;
  }

  function render() {
    const term = search.value.trim().toLowerCase();
    let shown = 0;
    rows.sort(compare);
    rows.forEach((row) => {
      const matches =
        (!term || row.dataset.name.includes(term) || row.dataset.sku.includes(term)) &&
        (!lowOnly.checked || row.dataset.low === "1");
      row.hidden = !matches;
      if (matches) {
        shown += 1;
      }
      body.appendChild(row);
    });
    if (noMatch) {
      noMatch.hidden = shown !== 0;
      body.appendChild(noMatch);
    }
    headers.forEach((th) => {
      if (th.dataset.key === sortKey) {
        th.setAttribute("aria-sort", direction === 1 ? "ascending" : "descending");
      } else {
        th.removeAttribute("aria-sort");
      }
    });
    count.textContent = shown === rows.length ? rows.length + " products" : "Showing " + shown + " of " + rows.length;
  }

  // Turn each heading into a button, so it works with the keyboard.
  headers.forEach((th) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sort";
    button.textContent = th.textContent;
    th.textContent = "";
    th.appendChild(button);
    button.addEventListener("click", () => {
      if (sortKey === th.dataset.key) {
        direction = -direction;
      } else {
        sortKey = th.dataset.key;
        direction = 1;
      }
      render();
    });
  });

  search.addEventListener("input", render);
  lowOnly.addEventListener("change", render);
  tools.hidden = false;
  render();
})();
