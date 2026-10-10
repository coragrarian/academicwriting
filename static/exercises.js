/* The renderer supplies #site-data, #answer-key and data-* hooks; this file
   collects learner responses, checks them and displays authored feedback.
   Module state stays in this closure during partial navigation. initialise()
   binds each new form; an ordinary page load restores state from localStorage. */
(() => {
  "use strict";

  const siteData = JSON.parse(document.getElementById("site-data").textContent);
  // Each module stores progress, raw responses and a checked flag by exercise
  // ID; responses are keyed again by question ID. Display order is irrelevant
  // to restoration, so semantic IDs must stay stable when rows are reordered.
  const storageKey = (module) => `agrarian-writing-v2:${module}`;

  function migrateIntroduction(saved) {
    let changed = false;
    // A subsection rename changed exercise IDs. Move all three records
    // together, preserving a current record if both old and new IDs exist.
    for (let number = 1; number <= 3; number++) {
      const previous = `introduction--further-practice--exercise-${number}`;
      const current = `introduction--grammar-and-vocabulary-in-the-introduction-section--exercise-${number}`;
      for (const record of [saved.progress, saved.responses, saved.checked]) {
        if (!Object.hasOwn(record, previous)) continue;
        if (!Object.hasOwn(record, current)) record[current] = record[previous];
        delete record[previous];
        changed = true;
      }
    }
    // Only previously checked canonical constructions are carried forward.
    // Arbitrary learner text remains untouched; there is no answer inference.
    const gapExercise = "introduction--indicating-a-research-gap--exercise-1";
    const responses = saved.responses[gapExercise];
    if (saved.checked[gapExercise] && responses && typeof responses === "object") {
      for (const [id, previous, current] of [
        ["context-q1", "has primarily concentrated", "has concentrated"],
        ["context-q3", "have only examined", "have examined"],
      ]) {
        if (typeof responses[id] === "string" && normaliseAnswer(responses[id]) === previous) {
          responses[id] = current;
          changed = true;
        }
      }
    }
    return changed;
  }

  function loadState(module) {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey(module)) || "{}");
      const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
      const saved = { progress: object(parsed.progress), responses: object(parsed.responses), checked: object(parsed.checked) };
      if (module === "introduction" && migrateIntroduction(saved)) {
        try {
          localStorage.setItem(storageKey(module), JSON.stringify(saved));
        } catch {
          // The migrated state remains usable if storage is read-only.
        }
      }
      return saved;
    } catch {
      return { progress: {}, responses: {}, checked: {} };
    }
  }

  const states = Object.fromEntries(Object.keys(siteData.modules).map((module) => [module, loadState(module)]));
  const state = states[siteData.module];

  function saveState() {
    try {
      localStorage.setItem(storageKey(siteData.module), JSON.stringify(state));
    } catch {
      // Checking still works when browser storage is unavailable.
    }
  }

  function updateProgress() {
    // Count the renderer's current exercise IDs, rather than every saved key:
    // an obsolete record must not inflate module or subsection completion.
    for (const [module, ids] of Object.entries(siteData.modules)) {
      const completed = ids.filter((id) => states[module].progress[id] === "completed").length;
      document.querySelectorAll(`[data-progress-other-module="${module}"]`).forEach((node) => {
        node.textContent = `${completed}/${ids.length}`;
      });
      document.querySelectorAll(`[data-progress-module="${module}"]`).forEach((node) => {
        node.textContent = `${completed}/${ids.length}`;
        const description = node.nextElementSibling;
        if (description?.hasAttribute("data-progress-description")) {
          description.textContent = `${completed} of ${ids.length} exercises completed`;
        }
      });
      for (const [slug, sectionIds] of Object.entries(siteData.course_sections[module])) {
        const sectionCompleted = sectionIds.filter((id) => states[module].progress[id] === "completed").length;
        document.querySelectorAll(`[data-progress-section="${slug}"][data-progress-module-id="${module}"]`).forEach((node) => {
          node.textContent = `${sectionCompleted}/${sectionIds.length}`;
          const description = node.nextElementSibling;
          if (description?.hasAttribute("data-progress-description")) {
            description.textContent = `${sectionCompleted} of ${sectionIds.length} exercises completed`;
          }
        });
      }
    }
    document.querySelectorAll("[data-exercise-link]").forEach((link) => {
      const value = states[link.dataset.moduleId].progress[link.dataset.exerciseLink] || "not-started";
      link.dataset.status = value;
      link.setAttribute("aria-label", `${link.textContent.trim()}: ${statusText(value)}`);
    });
  }

  function statusText(value) {
    return { "not-started": "Not started", "in-progress": "In progress", completed: "Completed" }[value];
  }

  function normaliseAnswer(value) {
    // Accept case and whitespace variation only. Punctuation, extra words
    // and grammatical differences remain part of the authored answer.
    return value.trim().toLowerCase().replace(/\s+/g, " ");
  }

  function initialise() {
    updateProgress();
    const form = document.getElementById("exercise-form");
    // Partial navigation replaces forms but retains this script. Guard the
    // actual DOM node so reinitialising a page cannot duplicate its handlers.
    if (!form || form.dataset.exerciseInitialised === "true") return;
    form.dataset.exerciseInitialised = "true";

    const exerciseId = form.dataset.exerciseId;
    const key = JSON.parse(document.getElementById("answer-key").textContent);
    const feedback = document.getElementById("exercise-feedback");
    const sharedFeedback = document.getElementById("shared-feedback");
    const status = document.querySelector("[data-current-status]");
    const controls = [...form.querySelectorAll("[data-question]")];
    const byId = Object.fromEntries(controls.map((control) => [control.dataset.question, control]));

    function selectedAnswers() {
      // Text remains a raw string; choices become arrays of zero-based option
      // indices, including selects. The answer key uses the same value shapes.
      return Object.fromEntries(controls.map((control) => {
        let value;
        if (control.tagName === "INPUT") value = control.value;
        else if (control.tagName === "SELECT") value = control.value === "" ? [] : [Number(control.value)];
        else value = [...control.querySelectorAll("input:checked")].map((input) => Number(input.value));
        return [control.dataset.question, value];
      }));
    }

    function restoreAnswers(saved) {
      for (const control of controls) {
        const value = saved[control.dataset.question];
        if (control.tagName === "INPUT") control.value = typeof value === "string" ? value : "";
        else if (control.tagName === "SELECT") control.value = Array.isArray(value) && value.length ? String(value[0]) : "";
        else control.querySelectorAll("input").forEach((input) => {
          input.checked = Array.isArray(value) && value.includes(Number(input.value));
        });
      }
    }

    function updateStatus() {
      const value = state.progress[exerciseId] || "not-started";
      status.textContent = statusText(value);
      status.dataset.status = value;
      updateProgress();
    }

    function clearFeedback() {
      feedback.textContent = "";
      feedback.className = "";
      for (const node of form.querySelectorAll("[data-item-feedback], [data-response-feedback], #shared-feedback")) {
        node.textContent = "";
        node.hidden = true;
      }
      for (const control of controls) {
        delete control.dataset.result;
        control.removeAttribute("aria-invalid");
        control.querySelectorAll("input").forEach((input) => input.removeAttribute("aria-invalid"));
      }
    }

    function correctAnswer(id, actual) {
      const question = key.questions[id];
      if (question.kind === "typed-gap") return normaliseAnswer(actual) === normaliseAnswer(question.expected);
      // Multi-select requires the exact set, not merely one expected option.
      return actual.length === question.expected.length && actual.every((value) => question.expected.includes(value));
    }

    function optionFeedback(group, given, results) {
      // Only selected options can supply an explanation; an incorrect attempt
      // must not reveal an unselected correct option's feedback. Prefer a
      // selected incorrect option when a group contains several responses.
      const ordered = [...group.questions].sort((a, b) => Number(results[a]) - Number(results[b]));
      for (const id of ordered) {
        const question = key.questions[id];
        if (question.kind === "typed-gap") continue;
        const values = [...given[id]].sort((a, b) => Number(question.expected.includes(a)) - Number(question.expected.includes(b)));
        for (const value of values) {
          if (question.option_feedback[value]) return question.option_feedback[value];
        }
      }
      return null;
    }

    function reviewSummary(message, responses, remaining = 0) {
      // Keep the existing summary wording; native fragment links let learners
      // revisit failures deliberately without moving focus during checking.
      feedback.replaceChildren(document.createTextNode(message));
      if (!responses.length) return;
      feedback.append(document.createTextNode(" Review "));
      responses.forEach((response, index) => {
        if (index) feedback.append(document.createTextNode(", "));
        const link = document.createElement("a");
        link.href = `#${response.id}`;
        link.textContent = response.label;
        feedback.append(link);
      });
      feedback.append(document.createTextNode(`${remaining ? ` and ${remaining} more` : ""}.`));
    }

    function showResult(given) {
      const results = Object.fromEntries(Object.keys(key.questions).map((id) => [id, correctAnswer(id, given[id])]));
      const allCorrect = Object.values(results).every(Boolean);
      let needsSharedFeedback = false;
      // Groups are semantic items or exercise-level direct responses, not
      // individual controls. Several gaps can therefore share one item result.
      for (const group of key.groups) {
        const correct = group.questions.filter((id) => results[id]).length;
        const groupCorrect = correct === group.questions.length;
        const outcome = groupCorrect ? "correct" : "incorrect";
        const groupNode = form.querySelector(`[data-response-group="${group.id}"]`);
        const itemFeedback = groupNode.querySelector("[data-item-feedback]");
        const specific = optionFeedback(group, given, results) || group.feedback[outcome];
        let message = specific;
        if (!message && key.feedback[outcome]) {
          // Shared exercise explanations appear once, below the item results.
          needsSharedFeedback = true;
        } else if (!message && !groupCorrect) {
          message = "Revise the responses marked for review, then check again.";
        }
        const heading = document.createElement("strong");
        heading.textContent = group.title
          ? (groupCorrect ? "Correct." : "Review this item.")
          : (groupCorrect ? "Correct." : "Review the marked responses.");
        // Source explanations often already begin with the result label.
        // Keep the visible status separate without repeating that opening.
        if (groupCorrect && message?.startsWith("Correct.")) {
          message = message.slice("Correct.".length).trimStart();
        }
        itemFeedback.replaceChildren(heading);
        if (message) itemFeedback.append(document.createTextNode(` ${message}`));
        for (const id of group.questions) {
          const question = key.questions[id];
          if (!question.gap_feedback) continue;
          const explanation = document.createElement("span");
          explanation.className = "gap-feedback";
          explanation.textContent = `${question.label}: ${results[id] ? "Correct." : "Review."} ${question.gap_feedback}`;
          itemFeedback.append(explanation);
        }
        itemFeedback.className = `item-feedback feedback-${outcome}`;
        itemFeedback.hidden = false;
        for (const id of group.questions) {
          const control = byId[id];
          control.dataset.result = results[id] ? "correct" : "incorrect";
          control.setAttribute("aria-invalid", String(!results[id]));
          control.querySelectorAll("input").forEach((input) => input.setAttribute("aria-invalid", String(!results[id])));
          const responseFeedback = document.getElementById(`${id}-feedback`);
          const question = key.questions[id];
          responseFeedback.textContent = `${question.label}: ${results[id] ? "Correct" : "Review this response"}.${question.gap_feedback ? ` ${question.gap_feedback}` : ""}`;
          responseFeedback.hidden = false;
        }
      }
      sharedFeedback.textContent = needsSharedFeedback ? key.feedback[allCorrect ? "correct" : "incorrect"] || "" : "";
      sharedFeedback.hidden = !sharedFeedback.textContent;
      const items = key.groups.filter((group) => group.title);
      if (items.length) {
        const correct = items.filter((group) => group.questions.every((id) => results[id])).length;
        const review = items.filter((group) => group.questions.some((id) => !results[id]))
          .map((group) => ({ id: group.id, label: group.title }));
        reviewSummary(`${correct} of ${items.length} items correct.`, review);
      } else {
        const correct = Object.values(results).filter(Boolean).length;
        const review = Object.keys(results).filter((id) => !results[id])
          .map((id) => ({ id, label: key.questions[id].label }));
        reviewSummary(`${correct} of ${controls.length} responses correct.`, review.slice(0, 5), Math.max(0, review.length - 5));
      }
      feedback.className = allCorrect ? "feedback-correct" : "feedback-incorrect";
      return allCorrect;
    }

    // Link feedback to native inputs as well as their fieldsets, making item
    // explanations discoverable when a keyboard user revisits a response.
    for (const group of key.groups) {
      const node = form.querySelector(`[data-response-group="${group.id}"]`);
      const description = node.querySelector("[data-item-feedback]").id;
      for (const id of group.questions) {
        const control = byId[id];
        for (const target of [control, ...control.querySelectorAll("input")]) {
          target.setAttribute("aria-describedby", `${id}-feedback ${description} shared-feedback`);
        }
      }
    }

    // Recreate feedback from responses and the checked flag instead of storing
    // per-question results. Checked attempts use the current key when a form
    // returns; an unchecked draft restores without revealing feedback.
    restoreAnswers(state.responses[exerciseId] || {});
    if (state.checked[exerciseId]) {
      const correct = showResult(selectedAnswers());
      state.progress[exerciseId] = correct ? "completed" : "in-progress";
    }
    updateStatus();

    form.addEventListener("input", () => {
      // Editing starts a new attempt: keep the draft, discard the old result
      // and require another Check before the exercise can count as completed.
      state.responses[exerciseId] = selectedAnswers();
      state.progress[exerciseId] = "in-progress";
      delete state.checked[exerciseId];
      clearFeedback();
      saveState();
      updateStatus();
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const given = selectedAnswers();
      const correct = showResult(given);
      state.responses[exerciseId] = given;
      state.progress[exerciseId] = correct ? "completed" : "in-progress";
      state.checked[exerciseId] = true;
      saveState();
      updateStatus();
    });

    document.getElementById("reset-exercise").addEventListener("click", () => {
      // Reset affects this exercise only; other saved attempts remain intact.
      form.reset();
      delete state.responses[exerciseId];
      delete state.progress[exerciseId];
      delete state.checked[exerciseId];
      clearFeedback();
      saveState();
      updateStatus();
      feedback.textContent = "Exercise reset.";
    });
  }

  window.AgrarianExercises = { initialise };
  initialise();
})();
