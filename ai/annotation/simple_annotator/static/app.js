(function () {
  "use strict";

  const byId = function (id) { return document.getElementById(id); };
  const ui = {
    progressCount: byId("progress-count"),
    reviewer: byId("reviewer-name"),
    progress: byId("review-progress"),
    position: byId("record-position"),
    previous: byId("previous-button"),
    next: byId("next-button"),
    jumpForm: byId("jump-form"),
    jumpNumber: byId("jump-number"),
    unfinished: byId("unfinished-button"),
    subject: byId("subject-source"),
    message: byId("message-source"),
    context: byId("thread-context"),
    metadata: byId("email-metadata"),
    classificationList: byId("classification-list"),
    labelCount: byId("label-count"),
    nonProjectHint: byId("non-project-hint"),
    spanList: byId("span-list"),
    spanEmpty: byId("span-empty"),
    spanCount: byId("span-count"),
    needsReview: byId("needs-review"),
    note: byId("review-note"),
    noteLength: byId("note-length"),
    saveIndicator: byId("save-indicator"),
    saveMessage: byId("save-message"),
    save: byId("save-button"),
    saveNext: byId("save-next-button"),
    spanMenu: byId("span-menu"),
    closeSpanMenu: byId("close-span-menu"),
    selectionPreview: byId("selection-preview"),
    spanOptions: byId("span-label-options"),
    toast: byId("toast")
  };

  const palette = ["#3977a8", "#9770bc", "#26958a", "#d28345", "#bf6073", "#6b8d54", "#bd9d34"];
  const state = {
    labels: [],
    spanLabels: [],
    selectedLabels: new Set(),
    spans: [],
    needsReview: false,
    note: "",
    subject: "",
    message: "",
    total: 0,
    completed: 0,
    firstUnfinished: null,
    index: null,
    email: null,
    loading: false,
    changeVersion: 0,
    savedVersion: 0,
    savePromise: null,
    saveTimer: null,
    loadToken: 0,
    toastTimer: null,
    selectionCandidate: null,
    selectionTimer: null
  };

  function setStatus(message, kind) {
    ui.saveMessage.textContent = message;
    ui.saveIndicator.className = "status-dot" + (kind ? " is-" + kind : "");
  }

  function showToast(message) {
    window.clearTimeout(state.toastTimer);
    ui.toast.textContent = message;
    ui.toast.hidden = false;
    state.toastTimer = window.setTimeout(function () { ui.toast.hidden = true; }, 3600);
  }

  function setBusy(busy) {
    state.loading = busy;
    const hasRecord = state.email !== null && state.total > 0;
    ui.previous.disabled = busy || !hasRecord || state.index <= 0;
    ui.next.disabled = busy || !hasRecord || state.index >= state.total - 1;
    ui.unfinished.disabled = busy || !hasRecord || !Number.isInteger(state.firstUnfinished);
    ui.jumpNumber.disabled = busy || state.total === 0;
    ui.jumpNumber.max = String(Math.max(1, state.total));
    ui.save.disabled = busy || !hasRecord;
    ui.saveNext.disabled = busy || !hasRecord;
    ui.classificationList.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function updateProgress() {
    ui.progress.max = Math.max(state.total, 1);
    ui.progress.value = Math.min(state.completed, state.total);
    ui.progressCount.textContent = state.completed + " of " + state.total + " reviewed";
    ui.position.textContent = Number.isInteger(state.index) && state.total
      ? "Email " + (state.index + 1) + " of " + state.total
      : "";
    if (Number.isInteger(state.index)) ui.jumpNumber.value = String(state.index + 1);
    setBusy(state.loading);
  }

  function labelName(key, inventory) {
    const item = inventory.find(function (label) { return label.key === key || label.name === key; });
    return item ? (item.name || item.key) : key;
  }

  function labelDefinition(key, inventory) {
    const item = inventory.find(function (label) { return label.key === key || label.name === key; });
    return item && item.definition ? item.definition : "";
  }

  function safePrimitive(value) {
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) {
      return value.map(function (part) {
        return typeof part === "string" || typeof part === "number" ? String(part) : "";
      }).filter(Boolean).join(", ");
    }
    return "";
  }

  function appendMetadataRow(label, value) {
    const formatted = safePrimitive(value);
    if (!formatted) return;
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = formatted;
    ui.metadata.append(term, detail);
  }

  function renderMetadata(source) {
    ui.metadata.replaceChildren();
    appendMetadataRow("From", source.sender);
    appendMetadataRow("To", source.recipients);
    appendMetadataRow("Cc", source.cc);
    appendMetadataRow("Sent", source.sent_at);
    appendMetadataRow("Attachments", source.attachment_names);
  }

  function sourceTextFor(field) {
    return field === "subject" ? state.subject : state.message;
  }

  function isSpanVisible(span) {
    const field = span.field || "current_message";
    if (field !== "subject" && field !== "current_message") return false;
    const source = sourceTextFor(field);
    return Number.isInteger(span.start) && Number.isInteger(span.end) &&
      span.start >= 0 && span.end > span.start && span.end <= source.length &&
      source.slice(span.start, span.end) === span.text;
  }

  function visibleSpansFor(field) {
    return state.spans.filter(function (span) {
      return (span.field || "current_message") === field && isSpanVisible(span);
    });
  }

  function renderSource(container, field) {
    const source = sourceTextFor(field);
    container.replaceChildren();
    container.classList.toggle("is-empty", source.length === 0);
    if (!source) return;

    const spans = visibleSpansFor(field);
    const boundaries = new Set([0, source.length]);
    spans.forEach(function (span) {
      boundaries.add(span.start);
      boundaries.add(span.end);
    });
    const points = Array.from(boundaries).sort(function (a, b) { return a - b; });

    for (let i = 0; i < points.length - 1; i += 1) {
      const start = points[i];
      const end = points[i + 1];
      if (end <= start) continue;
      const active = spans.filter(function (span) { return span.start < end && span.end > start; });
      const exactText = source.slice(start, end);
      if (!active.length) {
        container.appendChild(document.createTextNode(exactText));
        continue;
      }

      const mark = document.createElement("span");
      mark.className = "text-mark" + (active.length > 1 ? " text-mark-multiple" : "");
      const keys = Array.from(new Set(active.map(function (span) { return span.label; })));
      const names = keys.map(function (key) { return labelName(key, state.spanLabels); });
      const firstIndex = Math.max(0, state.spanLabels.findIndex(function (item) {
        return item.key === keys[0] || item.name === keys[0];
      }));
      const secondIndex = Math.max(0, state.spanLabels.findIndex(function (item) {
        return item.key === (keys[1] || keys[0]) || item.name === (keys[1] || keys[0]);
      }));
      mark.style.setProperty("--mark-color", palette[firstIndex % palette.length]);
      mark.style.setProperty("--mark-color-alt", palette[secondIndex % palette.length]);
      mark.dataset.labels = keys.join(" ");
      mark.title = keys.map(function (key) {
        const definition = labelDefinition(key, state.spanLabels);
        return definition ? labelName(key, state.spanLabels) + ": " + definition : labelName(key, state.spanLabels);
      }).join(" · ");
      mark.setAttribute("aria-label", exactText + ", " + names.join(", "));
      mark.textContent = exactText;
      container.appendChild(mark);
    }
  }

  function renderClassification() {
    ui.classificationList.replaceChildren();
    ui.labelCount.textContent = state.selectedLabels.size + " selected";
    ui.nonProjectHint.hidden = !state.selectedLabels.has("NON_PROJECT");

    state.labels.forEach(function (item, index) {
      const key = item.key || item.name || "";
      if (!key) return;
      const wrapper = document.createElement("label");
      wrapper.className = "label-option" + (key === "NON_PROJECT" ? " label-option-non-project" : "");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = key;
      checkbox.checked = state.selectedLabels.has(key);
      checkbox.disabled = state.needsReview;
      checkbox.setAttribute("aria-describedby", "label-description-" + index);
      checkbox.addEventListener("change", function () {
        if (checkbox.checked) {
          if (key === "NON_PROJECT") {
            state.selectedLabels.forEach(function (selected) {
              if (selected !== "NON_PROJECT") state.selectedLabels.delete(selected);
            });
          } else {
            state.selectedLabels.delete("NON_PROJECT");
          }
          state.selectedLabels.add(key);
        } else {
          state.selectedLabels.delete(key);
        }
        renderClassification();
        renderSource(ui.subject, "subject");
        renderSource(ui.message, "current_message");
        markDirty(true);
      });

      const copy = document.createElement("span");
      copy.className = "label-copy";
      const name = document.createElement("strong");
      name.textContent = item.name || key;
      const definition = document.createElement("small");
      definition.id = "label-description-" + index;
      definition.textContent = item.definition || "";
      copy.append(name, definition);
      const indicator = document.createElement("span");
      indicator.className = "checkbox-indicator";
      indicator.setAttribute("aria-hidden", "true");
      wrapper.append(checkbox, copy, indicator);
      ui.classificationList.appendChild(wrapper);
    });
  }

  function renderSpans() {
    ui.spanList.replaceChildren();
    const visible = state.spans.map(function (span, index) {
      return { span: span, index: index };
    }).filter(function (item) { return isSpanVisible(item.span); });
    ui.spanCount.textContent = visible.length + (visible.length === 1 ? " span" : " spans");
    ui.spanEmpty.hidden = visible.length > 0;

    visible.forEach(function (item, displayIndex) {
      const span = item.span;
      const row = document.createElement("div");
      row.className = "span-row";
      const details = document.createElement("div");
      details.className = "span-row-copy";
      const title = document.createElement("strong");
      title.textContent = labelName(span.label, state.spanLabels);
      title.title = labelDefinition(span.label, state.spanLabels);
      const quote = document.createElement("span");
      quote.className = "span-quote";
      quote.textContent = "“" + span.text + "”";
      const location = document.createElement("small");
      location.textContent = span.field === "subject" ? "Subject" : "Current message";
      details.append(title, quote, location);
      const remove = document.createElement("button");
      remove.className = "remove-span";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", "Remove " + labelName(span.label, state.spanLabels) + " span " + (displayIndex + 1));
      remove.disabled = state.needsReview;
      remove.addEventListener("click", function () {
        state.spans.splice(item.index, 1);
        renderSpans();
        renderSource(ui.subject, "subject");
        renderSource(ui.message, "current_message");
        markDirty(true);
      });
      row.append(details, remove);
      ui.spanList.appendChild(row);
    });

    renderSource(ui.subject, "subject");
    renderSource(ui.message, "current_message");
  }

  function updateReviewControls() {
    ui.needsReview.checked = state.needsReview;
    ui.note.value = state.note;
    ui.noteLength.textContent = state.note.length + " / 280";
    ui.note.placeholder = state.needsReview
      ? "Briefly say why this message needs another review."
      : "Add a brief note for the next reviewer.";
    ui.note.setAttribute("aria-label", state.needsReview ? "Short note for the next reviewer" : "Short note");
    ui.note.classList.toggle("is-review-note", state.needsReview);
  }

  function updateAnnotationUI() {
    renderClassification();
    renderSpans();
    updateReviewControls();
    const disabled = state.needsReview;
    ui.subject.classList.toggle("annotation-disabled", disabled);
    ui.message.classList.toggle("annotation-disabled", disabled);
    if (disabled) closeSpanMenu();
  }

  function renderCurrentEmail(response) {
    const source = response.source || response;
    state.subject = typeof source.subject === "string" ? source.subject : "";
    state.message = typeof source.current_message === "string" ? source.current_message : "";
    state.index = Number.isInteger(response.index) ? response.index : state.index;
    state.email = response;
    state.selectedLabels = new Set(Array.isArray(response.labels) ? response.labels : []);
    state.spans = Array.isArray(response.spans) ? response.spans.map(function (span) {
      return {
        field: span.field || "current_message",
        start: Number(span.start),
        end: Number(span.end),
        text: typeof span.text === "string" ? span.text : "",
        label: span.label
      };
    }) : [];
    state.needsReview = Boolean(response.needs_review);
    state.note = typeof response.note === "string" ? response.note : "";
    state.changeVersion = 0;
    state.savedVersion = 0;

    ui.subject.textContent = state.subject;
    ui.subject.setAttribute("aria-label", state.subject ? "Email subject. Select a phrase to annotate." : "Email subject is empty.");
    ui.message.textContent = state.message;
    ui.context.textContent = typeof source.thread_context === "string" ? source.thread_context : "";
    ui.context.classList.toggle("is-empty", ui.context.textContent.length === 0);
    if (!ui.context.textContent) ui.context.textContent = "No thread context.";
    renderMetadata(source);
    updateAnnotationUI();
    updateProgress();
    setStatus(state.needsReview ? "Needs another review" : "Email loaded", "ready");
  }

  function showEmptyState(message) {
    state.email = null;
    ui.subject.textContent = "";
    ui.message.textContent = "";
    ui.context.textContent = "";
    ui.metadata.replaceChildren();
    ui.classificationList.replaceChildren();
    ui.spanList.replaceChildren();
    ui.spanEmpty.hidden = false;
    ui.spanEmpty.textContent = message;
    setStatus(message, "error");
    updateProgress();
  }

  async function loadEmail(index) {
    if (index < 0 || index >= state.total) return;
    const token = ++state.loadToken;
    setBusy(true);
    setStatus("Loading email…", "");
    try {
      const response = await fetch("/api/email/" + encodeURIComponent(index), { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error("load");
      const email = await response.json();
      if (token !== state.loadToken) return;
      if (!email || typeof email !== "object") throw new Error("load");
      if (!Number.isInteger(email.index)) email.index = index;
      renderCurrentEmail(email);
    } catch (error) {
      if (token !== state.loadToken) return;
      showEmptyState("Could not load this email. Check the local server and try again.");
    } finally {
      if (token === state.loadToken) {
        state.loading = false;
        updateProgress();
      }
    }
  }

  function markDirty(immediate) {
    if (!state.email) return;
    state.changeVersion += 1;
    setStatus("Unsaved changes", "dirty");
    window.clearTimeout(state.saveTimer);
    state.saveTimer = window.setTimeout(function () {
      saveCurrent().catch(function () {});
    }, immediate ? 250 : 650);
  }

  async function performSave(version) {
    const index = state.index;
    const payload = {
      labels: Array.from(state.selectedLabels),
      spans: state.spans.map(function (span) {
        return { field: span.field || "current_message", start: span.start, end: span.end, text: span.text, label: span.label };
      }),
      needs_review: state.needsReview,
      note: state.note
    };
    setStatus("Saving…", "saving");
    const response = await fetch("/api/email/" + encodeURIComponent(index), {
      method: "PUT",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) throw new Error("save");
    const result = await response.json().catch(function () { return {}; });
    state.savedVersion = version;
    if (Number.isFinite(result.completed)) state.completed = result.completed;
    if (Object.prototype.hasOwnProperty.call(result, "first_unfinished")) {
      state.firstUnfinished = Number.isInteger(result.first_unfinished) ? result.first_unfinished : null;
    }
    if (state.email && typeof result.record_completed === "boolean") state.email.completed = result.record_completed;
    updateProgress();
    setStatus("All changes saved", "ready");
  }

  async function saveCurrent() {
    window.clearTimeout(state.saveTimer);
    if (!state.email || state.savedVersion === state.changeVersion) return;
    if (state.savePromise) {
      await state.savePromise;
      if (state.savedVersion < state.changeVersion) return saveCurrent();
      return;
    }

    const version = state.changeVersion;
    const pending = performSave(version);
    state.savePromise = pending;
    try {
      await pending;
    } catch (error) {
      setStatus("Could not save. Your changes are still here.", "error");
      showToast("Save failed. Check the local server, then try again.");
      throw error;
    } finally {
      if (state.savePromise === pending) state.savePromise = null;
    }

    if (state.savedVersion < state.changeVersion) return saveCurrent();
  }

  async function flushSave() {
    window.clearTimeout(state.saveTimer);
    await saveCurrent();
  }

  async function navigateTo(index) {
    if (state.loading || !Number.isInteger(index) || index < 0 || index >= state.total) return;
    if (index === state.index) return;
    try {
      await flushSave();
    } catch (error) {
      return;
    }
    await loadEmail(index);
  }

  async function saveAndNext() {
    if (state.loading || !state.email) return;
    try {
      await flushSave();
    } catch (error) {
      return;
    }
    if (state.index < state.total - 1) {
      await loadEmail(state.index + 1);
      return;
    }
    if (Number.isInteger(state.firstUnfinished) && state.firstUnfinished !== state.index) {
      await loadEmail(state.firstUnfinished);
      return;
    }
    showToast("This is the last email in the current review set.");
  }

  function sourceRootFor(node) {
    let element = node && node.nodeType === Node.ELEMENT_NODE ? node : node && node.parentElement;
    if (!element) return null;
    return element.closest(".source-text");
  }

  function closeSpanMenu() {
    ui.spanMenu.hidden = true;
    ui.spanOptions.replaceChildren();
    state.selectionCandidate = null;
  }

  function positionSpanMenu(rect) {
    const gap = 10;
    const menuWidth = Math.min(360, window.innerWidth - 24);
    ui.spanMenu.style.width = menuWidth + "px";
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - menuWidth - 12));
    ui.spanMenu.style.left = left + "px";
    const menuHeight = ui.spanMenu.offsetHeight;
    const below = rect.bottom + gap;
    const top = below + menuHeight <= window.innerHeight - 12
      ? below
      : Math.max(12, rect.top - menuHeight - gap);
    ui.spanMenu.style.top = top + "px";
  }

  function addSelectedSpan(label) {
    const candidate = state.selectionCandidate;
    if (!candidate || state.needsReview) return;
    const source = sourceTextFor(candidate.field);
    if (source.slice(candidate.start, candidate.end) !== candidate.text) {
      closeSpanMenu();
      showToast("The selected text changed. Select the phrase again.");
      return;
    }
    state.spans.push({
      field: candidate.field,
      start: candidate.start,
      end: candidate.end,
      text: candidate.text,
      label: label
    });
    closeSpanMenu();
    renderSpans();
    markDirty(true);
  }

  function openSpanMenu(candidate, rect, moveFocus) {
    if (state.needsReview || state.spanLabels.length === 0) return;
    state.selectionCandidate = candidate;
    ui.selectionPreview.textContent = "“" + candidate.text + "”";
    ui.spanOptions.replaceChildren();

    state.spanLabels.forEach(function (item) {
      const key = item.key || item.name || "";
      if (!key) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "span-label-button";
      button.title = item.definition || item.name || key;
      const name = document.createElement("strong");
      name.textContent = item.name || key;
      const definition = document.createElement("small");
      definition.textContent = item.definition || "";
      button.append(name, definition);
      button.addEventListener("pointerdown", function (event) { event.preventDefault(); });
      button.addEventListener("click", function () { addSelectedSpan(key); });
      ui.spanOptions.appendChild(button);
    });

    ui.spanMenu.hidden = false;
    positionSpanMenu(rect);
    if (moveFocus) {
      const first = ui.spanOptions.querySelector("button");
      if (first) first.focus();
    }
  }

  function inspectSelection() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      if (!ui.spanMenu.contains(document.activeElement)) closeSpanMenu();
      return;
    }

    const range = selection.getRangeAt(0);
    const startRoot = sourceRootFor(range.startContainer);
    const endRoot = sourceRootFor(range.endContainer);
    if (startRoot !== endRoot) {
      if (startRoot || endRoot) {
        closeSpanMenu();
        showToast("Select text within the subject or current message one at a time.");
      }
      return;
    }
    if (!startRoot || state.needsReview) return;

    const field = startRoot.dataset.field;
    if (field !== "subject" && field !== "current_message") return;
    const source = sourceTextFor(field);
    if (startRoot.textContent !== source) {
      closeSpanMenu();
      showToast("This text is being updated. Select the phrase again.");
      return;
    }

    const prefix = document.createRange();
    prefix.selectNodeContents(startRoot);
    try {
      prefix.setEnd(range.startContainer, range.startOffset);
    } catch (error) {
      closeSpanMenu();
      return;
    }
    const start = prefix.toString().length;
    const text = range.toString();
    const end = start + text.length;
    if (!text || source.slice(start, end) !== text) {
      closeSpanMenu();
      return;
    }

    const rect = range.getBoundingClientRect();
    const fallbackRects = range.getClientRects();
    const anchor = rect.width || rect.height ? rect : (fallbackRects.length ? fallbackRects[0] : null);
    if (!anchor) return;
    openSpanMenu({ field: field, start: start, end: end, text: text }, anchor, document.activeElement === startRoot);
  }

  function handleNeedsReviewChange() {
    if (ui.needsReview.checked) {
      const hasAnnotations = state.selectedLabels.size > 0 || state.spans.length > 0;
      if (hasAnnotations && !window.confirm("Mark this email as needing another review and clear its labels and text spans?")) {
        ui.needsReview.checked = false;
        return;
      }
      state.selectedLabels.clear();
      state.spans = [];
      state.needsReview = true;
    } else {
      state.needsReview = false;
    }
    closeSpanMenu();
    updateAnnotationUI();
    markDirty(true);
  }

  async function initialize() {
    setStatus("Loading progress…", "");
    try {
      const response = await fetch("/api/state", { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error("state");
      const data = await response.json();
      ui.reviewer.textContent = "Reviewer: " + (typeof data.reviewer === "string" ? data.reviewer : "unknown");
      state.labels = Array.isArray(data.labels) ? data.labels : [];
      state.spanLabels = Array.isArray(data.span_labels) ? data.span_labels : [];
      state.total = Number.isFinite(data.total) ? Math.max(0, data.total) : 0;
      state.completed = Number.isFinite(data.completed) ? Math.max(0, data.completed) : 0;
      state.firstUnfinished = Number.isInteger(data.first_unfinished) ? data.first_unfinished : null;
      updateProgress();
      if (state.total === 0) {
        showEmptyState("No emails are available in this review set.");
        return;
      }
      renderClassification();
      const startIndex = Number.isInteger(state.firstUnfinished) &&
        state.firstUnfinished >= 0 && state.firstUnfinished < state.total
        ? state.firstUnfinished
        : 0;
      await loadEmail(startIndex);
    } catch (error) {
      showEmptyState("Could not connect to the annotator. Start the local server and reload this page.");
    }
  }

  ui.previous.addEventListener("click", function () { navigateTo(state.index - 1); });
  ui.next.addEventListener("click", function () { navigateTo(state.index + 1); });
  ui.unfinished.addEventListener("click", function () {
    if (Number.isInteger(state.firstUnfinished)) navigateTo(state.firstUnfinished);
    else showToast("Every email in this review set has been reviewed.");
  });
  ui.jumpForm.addEventListener("submit", function (event) {
    event.preventDefault();
    const userNumber = Number(ui.jumpNumber.value);
    if (!Number.isInteger(userNumber) || userNumber < 1 || userNumber > state.total) {
      showToast("Enter an email number from 1 to " + state.total + ".");
      return;
    }
    navigateTo(userNumber - 1);
  });
  ui.save.addEventListener("click", function () {
    flushSave().catch(function () {});
  });
  ui.saveNext.addEventListener("click", saveAndNext);
  ui.needsReview.addEventListener("change", handleNeedsReviewChange);
  ui.note.addEventListener("input", function () {
    state.note = ui.note.value.slice(0, 280);
    ui.noteLength.textContent = state.note.length + " / 280";
    markDirty(false);
  });
  ui.closeSpanMenu.addEventListener("click", closeSpanMenu);
  ui.spanMenu.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeSpanMenu();
  });
  ui.spanMenu.addEventListener("click", function (event) {
    if (event.target === ui.spanMenu) closeSpanMenu();
  });

  document.addEventListener("mouseup", function () {
    window.setTimeout(inspectSelection, 0);
  });
  document.addEventListener("selectionchange", function () {
    window.clearTimeout(state.selectionTimer);
    state.selectionTimer = window.setTimeout(inspectSelection, 140);
  });
  document.addEventListener("mousedown", function (event) {
    if (!ui.spanMenu.hidden && !ui.spanMenu.contains(event.target) &&
      !event.target.closest(".source-text")) closeSpanMenu();
  });

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      saveAndNext();
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target && target.closest && target.closest("input, textarea, select, button, [contenteditable='true'], .span-menu")) return;
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) return;
    if (event.key === "ArrowLeft" && state.index > 0) {
      event.preventDefault();
      navigateTo(state.index - 1);
    } else if (event.key === "ArrowRight" && state.index < state.total - 1) {
      event.preventDefault();
      navigateTo(state.index + 1);
    }
  });

  window.addEventListener("resize", function () {
    if (!ui.spanMenu.hidden && state.selectionCandidate) inspectSelection();
  });
  window.addEventListener("beforeunload", function (event) {
    if (state.changeVersion > state.savedVersion) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  initialize();
}());
