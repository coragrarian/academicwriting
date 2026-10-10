/* Shared browser-local progress contract: each module stores progress, raw
   responses and checked flags by exercise ID. Count only the current catalogue;
   exercise pages alone check answers and write attempts. */
(() => {
  "use strict";

  const storageKey = (module) => `agrarian-writing-v2:${module}`;
  const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};

  function migrateIntroduction(saved) {
    let changed = false;
    // Retain the existing subsection-rename repair across all three records,
    // preserving a current record when both old and current IDs are stored.
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
    // Preserve the existing repair of recognised, previously checked text.
    const gapExercise = "introduction--indicating-a-research-gap--exercise-1";
    const responses = saved.responses[gapExercise];
    if (saved.checked[gapExercise] && responses && typeof responses === "object") {
      for (const [id, previous, current] of [
        ["context-q1", "has primarily concentrated", "has concentrated"],
        ["context-q3", "have only examined", "have examined"],
      ]) {
        if (typeof responses[id] === "string" && responses[id].trim().toLowerCase().replace(/\s+/g, " ") === previous) {
          responses[id] = current;
          changed = true;
        }
      }
    }
    return changed;
  }

  /** Read the existing format, optionally persisting its compatibility repair.
   * Home uses the default read-only mode; course pages retain their repair write.
   */
  function readState(module, { persistRepair = false } = {}) {
    try {
      const parsed = object(JSON.parse(localStorage.getItem(storageKey(module)) || "{}"));
      const saved = { progress: object(parsed.progress), responses: object(parsed.responses), checked: object(parsed.checked) };
      if (module === "introduction" && migrateIntroduction(saved) && persistRepair) {
        try {
          localStorage.setItem(storageKey(module), JSON.stringify(saved));
        } catch {
          // The repaired state remains usable if storage is read-only.
        }
      }
      return saved;
    } catch {
      return { progress: {}, responses: {}, checked: {} };
    }
  }

  /** Count the exact stored completion value for current exercise IDs only. */
  function countCompleted(state, exerciseIds) {
    return exerciseIds.filter((id) => state.progress[id] === "completed").length;
  }

  window.AgrarianProgress = { storageKey, readState, countCompleted };
})();
