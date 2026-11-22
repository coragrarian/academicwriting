/* The renderer supplies #site-data, #answer-key and data-* hooks; this file
   collects learner responses, checks them and displays authored feedback.
   Saved state merges at exercise granularity: the mounted form is authoritative
   for its own exercise, persist() merges that exercise into fresh storage, and
   storage and persisted pageshow events refresh other exercises in place. */
/**
 * @typedef {"single-choice" | "multi-select" | "inline-choice" | "gap" | "matching" | "typed-gap"} ResponseKind
 * @typedef {Object} FeedbackPayload
 * @property {string | null} correct
 * @property {string | null} incorrect
 * @typedef {Object} QuestionPayload
 * @property {ResponseKind} kind
 * @property {number[] | string} expected
 * @property {string} label
 * @property {string | null} gap_feedback
 * @property {Object<string, string>} option_feedback
 * @typedef {Object} GroupPayload
 * @property {string} id
 * @property {string | null} title
 * @property {string[]} questions
 * @property {FeedbackPayload} feedback
 * @typedef {Object} AnswerPayload
 * @property {Object<string, QuestionPayload>} questions
 * @property {GroupPayload[]} groups
 * @property {FeedbackPayload} feedback
 * @typedef {Object} CourseSiteData
 * @property {string} module
 * @property {Object<string, string[]>} sections
 * @property {Object<string, string[]>} modules
 * @property {Object<string, Object<string, string[]>>} course_sections
 */
(() => {
  "use strict";

  const siteData = JSON.parse(document.getElementById("site-data").textContent);
  const { RECORDS, storageKey, readState, countCompleted } = window.AgrarianProgress;
  const moduleNames = Object.keys(siteData.modules);
  const moduleByKey = Object.fromEntries(moduleNames.map((module) => [storageKey(module), module]));
  const states = Object.fromEntries(moduleNames.map((module) => [module, readState(module, { persistRepair: true })]));
  const state = states[siteData.module];
  let mountedExerciseId = null;

  function persist(exerciseId) {
    // Merge only the mounted exercise so progress saved later in other tabs
    // is preserved while Reset deletions remain durable for this exercise.
    const fresh = readState(siteData.module);
    for (const key of RECORDS) {
      if (Object.hasOwn(state[key], exerciseId)) {
        fresh[key][exerciseId] = state[key][exerciseId];
      } else {
        delete fresh[key][exerciseId];
      }
    }
    try {
      localStorage.setItem(storageKey(siteData.module), JSON.stringify(fresh));
    } catch {
      // Checking still works when browser storage is unavailable.
    }
    for (const key of RECORDS) {
      state[key] = fresh[key];
    }
  }

  function refreshModules(modules) {
    // Keep the mounted form authoritative for its own exercise while adopting
    // state written in other tabs or before a back/forward-cache restore.
    for (const module of modules) {
      const fresh = readState(module);
      if (module === siteData.module && mountedExerciseId !== null) {
        for (const key of RECORDS) {
          if (Object.hasOwn(state[key], mountedExerciseId)) {
            fresh[key][mountedExerciseId] = state[key][mountedExerciseId];
          } else {
            delete fresh[key][mountedExerciseId];
          }
        }
      }
      for (const key of RECORDS) {
        states[module][key] = fresh[key];
      }
    }
    updateProgress();
  }

  window.addEventListener("storage", (event) => {
    try {
      if (event.storageArea !== localStorage) return;
    } catch {
      return;
    }
    if (event.key === null) {
      refreshModules(moduleNames);
    } else if (Object.hasOwn(moduleByKey, event.key)) {
      refreshModules([moduleByKey[event.key]]);
    }
  });

  window.addEventListener("pageshow", (event) => {
    if (event.persisted) refreshModules(moduleNames);
  });

  function updateProgress() {
    // Count the renderer's current exercise IDs, rather than every saved key:
    // an obsolete record must not inflate module or subsection completion.
    for (const [module, ids] of Object.entries(siteData.modules)) {
      const completed = countCompleted(states[module], ids);
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
        const sectionCompleted = countCompleted(states[module], sectionIds);
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
    const form = document.getElementById("exercise-form");
    mountedExerciseId = form ? form.dataset.exerciseId : null;
    updateProgress();
    // Partial navigation replaces forms but retains this script. Guard the
    // actual DOM node so reinitialising a page cannot duplicate its handlers.
    if (!form || form.dataset.exerciseInitialised === "true") return;
    form.dataset.exerciseInitialised = "true";

    const exerciseId = mountedExerciseId;
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
      const recomputed = correct ? "completed" : "in-progress";
      if (state.progress[exerciseId] !== recomputed) {
        state.progress[exerciseId] = recomputed;
        persist(exerciseId);
      }
    }
    updateStatus();

    form.addEventListener("input", () => {
      // Editing starts a new attempt: keep the draft, discard the old result
      // and require another Check before the exercise can count as completed.
      state.responses[exerciseId] = selectedAnswers();
      state.progress[exerciseId] = "in-progress";
      delete state.checked[exerciseId];
      clearFeedback();
      persist(exerciseId);
      updateStatus();
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const given = selectedAnswers();
      const correct = showResult(given);
      state.responses[exerciseId] = given;
      state.progress[exerciseId] = correct ? "completed" : "in-progress";
      state.checked[exerciseId] = true;
      persist(exerciseId);
      updateStatus();
    });

    document.getElementById("reset-exercise").addEventListener("click", () => {
      // Reset affects this exercise only; other saved attempts remain intact.
      form.reset();
      delete state.responses[exerciseId];
      delete state.progress[exerciseId];
      delete state.checked[exerciseId];
      clearFeedback();
      persist(exerciseId);
      updateStatus();
      feedback.textContent = "Exercise reset.";
    });
  }

  window.AgrarianExercises = { initialise };
  initialise();
})();
