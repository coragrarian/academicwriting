/* Shared browser-local progress contract: each module stores RECORDS (progress,
   raw responses, checked flags and structural fingerprints) by exercise ID,
   which is the merge unit across tabs. readStoredState returns null when
   storage throws so exercise pages can fall back to in-memory session state.
   Count only the current catalogue; exercise pages alone check answers and
   write attempts. */
/**
 * @typedef {"not-started" | "in-progress" | "completed"} ExerciseStatus
 * @typedef {Object} SavedModuleState
 * @property {Object<string, ExerciseStatus>} progress
 * @property {Object<string, Object<string, (number[] | string)>>} responses
 * @property {Object<string, boolean>} checked
 * @property {Object<string, string>} fingerprints
 */
(() => {
  "use strict";

  const RECORDS = ["progress", "responses", "checked", "fingerprints"];
  const storageKey = (module) => `agrarian-writing-v2:${module}`;
  const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const emptyRecords = () => Object.fromEntries(RECORDS.map((key) => [key, {}]));

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

  /** Read and normalise stored state, returning null only when storage throws.
   * Malformed or non-object JSON yields empty records so a later write repairs
   * it. Home uses the default read-only mode; course pages retain their repair write.
   */
  function readStoredState(module, { persistRepair = false } = {}) {
    let raw;
    try {
      raw = localStorage.getItem(storageKey(module));
    } catch {
      return null;
    }
    let parsed = {};
    try {
      parsed = object(JSON.parse(raw || "{}"));
    } catch {
      parsed = {};
    }
    const saved = Object.fromEntries(RECORDS.map((key) => [key, object(parsed[key])]));
    if (module === "introduction" && migrateIntroduction(saved) && persistRepair) {
      try {
        localStorage.setItem(storageKey(module), JSON.stringify(saved));
      } catch {
        // The repaired state remains usable if storage is read-only.
      }
    }
    return saved;
  }

  /** Return stored state, or empty records when storage is unavailable. */
  function readState(module, options) {
    return readStoredState(module, options) ?? emptyRecords();
  }

  /** Count the exact stored completion value for current exercise IDs only. */
  function countCompleted(state, exerciseIds) {
    return exerciseIds.filter((id) => state.progress[id] === "completed").length;
  }

  window.AgrarianProgress = { RECORDS, storageKey, readStoredState, readState, countCompleted };
})();
