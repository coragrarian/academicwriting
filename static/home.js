/* Deferred enhancement: labels and destinations come from the ordered rows;
   site-data supplies only the same exercise catalogue used by course pages. */
(() => {
  "use strict";

  const { readState, countCompleted } = window.AgrarianProgress;
  const { modules } = JSON.parse(document.getElementById("site-data").textContent);
  const progress = [...document.querySelectorAll("[data-home-module]")].map((row) => {
    const module = row.dataset.homeModule;
    const ids = modules[module];
    const completed = countCompleted(readState(module), ids);
    const total = ids.length;
    const region = row.querySelector(".contents-progress");
    const complete = total > 0 && completed === total;
    region.dataset.status = complete ? "completed" : completed ? "in-progress" : "not-started";
    region.querySelector(".contents-progress-status").textContent = complete
      ? "Completed"
      : completed ? `${completed} of ${total} exercises completed` : "Not started";
    region.querySelector(".contents-progress-fill").style.width = `${total ? completed / total * 100 : 0}%`;
    region.hidden = false;
    return { row, completed, total };
  });

  if (!progress.some(({ completed }) => completed > 0)) return;
  const entry = document.querySelector("[data-home-entry]");
  const label = entry.querySelector("[data-home-entry-label]");
  const next = progress.find(({ completed, total }) => completed < total);
  if (next) {
    label.textContent = `Continue with ${next.row.querySelector(".contents-title").textContent}`;
    entry.setAttribute("href", next.row.getAttribute("href"));
  } else {
    label.textContent = "Review the course";
    entry.setAttribute("href", "#course");
  }
})();
