(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    sessionId: null,
    packet: null,
    recordId: null,
    syntheticFixture: false,
    lastValidation: null,
    validatedText: null,
    demos: [],
    busy: false,
    readOnlyGold: false,
  };

  function setNotice(message, tone = "") {
    const notice = $("notice");
    notice.textContent = message;
    notice.className = `notice${tone ? ` ${tone}` : ""}`;
  }

  function setBusy(value) {
    state.busy = value;
    const ready = Boolean(state.sessionId && state.packet);
    $("validateButton").disabled = !ready || value;
    $("saveButton").disabled = !ready || value || state.readOnlyGold;
    $("packetFile").disabled = value;
    $("loadDemo").disabled = value || state.demos.length === 0;
    $("openSaved").disabled = value || !$("savedSelect").value;
    $("demoSelect").disabled = value || state.demos.length === 0;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      credentials: "omit",
      mode: "same-origin",
      ...options,
      headers: { ...(options.headers || {}) },
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("The local dashboard returned an unreadable response.");
    }
    if (!response.ok) {
      const detail = payload?.error || payload?.validation?.errors?.join("; ") || "The local operation failed.";
      throw new Error(detail);
    }
    return payload;
  }

  function jsonPost(path, value) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value),
    });
  }

  function currentAnnotation() {
    try {
      const value = JSON.parse($("annotationEditor").value);
      if (!value || typeof value !== "object" || Array.isArray(value)) return { error: "Annotation JSON must be an object." };
      return { value };
    } catch (error) {
      return { error: error instanceof Error ? error.message : "Annotation JSON is invalid." };
    }
  }

  function textElement(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = String(value ?? "");
    return element;
  }

  function buildSourceMessage(source, spans) {
    const pre = $("sourceMessage");
    pre.replaceChildren();
    const original = typeof source.current_message === "string" ? source.current_message : "";
    const chars = Array.from(original);
    const relevant = spans.map((span, index) => ({ span, index }))
      .filter(({ span }) => span && span.field === "current_message" && span.source_id === source.source_id
        && Number.isInteger(span.start) && Number.isInteger(span.end)
        && span.start >= 0 && span.end > span.start && span.end <= chars.length);
    const boundaries = new Set([0, chars.length]);
    for (const { span } of relevant) {
      boundaries.add(span.start);
      boundaries.add(span.end);
    }
    const points = [...boundaries].sort((a, b) => a - b);
    for (let point = 0; point < points.length - 1; point += 1) {
      const start = points[point];
      const end = points[point + 1];
      if (end <= start) continue;
      const covering = relevant.filter(({ span }) => span.start < end && span.end > start);
      const piece = document.createElement(covering.length ? "mark" : "span");
      const beginning = covering.filter(({ span }) => span.start <= start && span.end > start);
      if (covering.length) piece.className = covering.length > 1 ? "evidence-mark evidence-overlap" : "evidence-mark";
      beginning.forEach(({ index }) => {
        const anchor = document.createElement("span");
        anchor.id = `source-fragment-${index}`;
        anchor.setAttribute("aria-hidden", "true");
        pre.appendChild(anchor);
      });
      piece.textContent = chars.slice(start, end).join("");
      pre.appendChild(piece);
    }
    if (!original) pre.textContent = "No current_message text is present in this packet.";
  }

  function renderEvidence(source, annotation) {
    const spans = Array.isArray(annotation.spans) ? annotation.spans : [];
    const rows = $("evidenceRows");
    rows.replaceChildren();
    const spanIndexes = new Map();
    spans.forEach((span, index) => {
      if (span && typeof span.id === "string" && !spanIndexes.has(span.id)) spanIndexes.set(span.id, index);
      const row = document.createElement("article");
      row.className = "evidence-row";
      row.id = `evidence-span-${index}`;
      const jump = document.createElement("a");
      jump.href = span?.field === "subject" ? "#sourceSubjectFull" : `#source-fragment-${index}`;
      const top = document.createElement("div");
      top.className = "evidence-top";
      const kind = textElement("span", "evidence-kind", span?.type || "UNKNOWN");
      const bounds = textElement("span", "", `${span?.start ?? "?"}:${span?.end ?? "?"}`);
      top.append(kind, bounds);
      const quote = textElement("span", "evidence-quote", typeof span?.text === "string" ? `“${span.text}”` : "Missing span text");
      jump.append(top, quote);
      row.appendChild(jump);
      const field = textElement("div", "muted", `${span?.field || "unknown field"} · ${span?.id || "no span id"}`);
      row.appendChild(field);
      rows.appendChild(row);
    });
    if (!spans.length) rows.appendChild(textElement("div", "empty-state", "No evidence spans are attached to this annotation."));
    buildSourceMessage(source, spans);
    return spanIndexes;
  }

  function renderEvents(annotation, spanIndexes) {
    const target = $("eventCards");
    target.replaceChildren();
    const events = Array.isArray(annotation.events) ? annotation.events : [];
    $("eventCount").textContent = `${events.length} ${events.length === 1 ? "event" : "events"}`;
    events.forEach((event) => {
      const card = document.createElement("article");
      card.className = "event-card";
      const head = document.createElement("div");
      head.className = "event-card-head";
      head.append(textElement("span", "event-kind", event?.kind || "UNKNOWN"), textElement("span", "event-id", event?.id || "no event id"));
      card.appendChild(head);
      card.appendChild(textElement("span", "event-state", `${event?.state || "unknown state"} · ${event?.certainty || "unknown certainty"}`));
      const className = event?.action_class || event?.document_class;
      if (className) card.appendChild(textElement("div", "event-class", `Class · ${className}`));
      const references = (Array.isArray(annotation.event_span_links) ? annotation.event_span_links : [])
        .filter((link) => link && link.event_id === event?.id);
      const evidence = document.createElement("div");
      evidence.className = "event-evidence";
      if (!references.length) {
        evidence.appendChild(textElement("span", "muted", "No linked evidence"));
      } else {
        references.forEach((link) => {
          const index = spanIndexes.get(link.span_id);
          const anchor = document.createElement("a");
          anchor.href = index === undefined ? "#evidenceRows" : `#evidence-span-${index}`;
          const quote = index === undefined ? "Unknown evidence span" : (annotation.spans[index]?.text || link.span_id);
          anchor.textContent = `${link.role || "EVIDENCE"} · ${quote}`;
          evidence.appendChild(anchor);
        });
      }
      card.appendChild(evidence);
      target.appendChild(card);
    });
    if (!events.length) target.appendChild(textElement("div", "empty-state", "This packet has no current events."));
  }

  function renderPreview(annotation) {
    const source = state.packet?.source || {};
    $("sourceId").textContent = source.source_id || "—";
    $("sourceSubject").textContent = source.subject || "No subject";
    $("sourceSubjectFull").textContent = source.subject || "No subject";
    $("scopeValue").textContent = annotation.scope?.value || "—";
    $("scopeReason").textContent = annotation.scope?.reason || "No scope rationale supplied.";
    const scopeEvidence = $("scopeEvidence");
    scopeEvidence.replaceChildren();
    const spanIndexes = renderEvidence(source, annotation);
    const scopeIds = Array.isArray(annotation.scope?.evidence_span_ids) ? annotation.scope.evidence_span_ids : [];
    scopeIds.forEach((spanId) => {
      const index = spanIndexes.get(spanId);
      const chip = textElement("a", "mini-chip", spanId);
      chip.href = index === undefined ? "#evidenceRows" : `#evidence-span-${index}`;
      chip.style.textDecoration = "none";
      scopeEvidence.appendChild(chip);
    });
    if (!scopeIds.length) scopeEvidence.appendChild(textElement("span", "muted", "No scope evidence"));
    renderEvents(annotation, spanIndexes);
    const review = annotation.needs_review === true;
    const reviewState = $("reviewState");
    reviewState.className = `review-state ${review ? "flagged" : "clear"}`;
    reviewState.textContent = review ? "Needs human review" : "No review flag";
    const reasons = Array.isArray(annotation.review_reasons) ? annotation.review_reasons : [];
    $("reviewReasons").textContent = reasons.length ? reasons.join(" · ") : "No review reasons recorded.";
  }

  function resetDerived() {
    state.lastValidation = null;
    state.validatedText = null;
    $("mapperStatus").className = "mapper-state pending";
    $("mapperStatus").textContent = "Validate to derive";
    $("derivedLabels").replaceChildren(textElement("span", "muted", "Labels appear after server-side V1 validation."));
    $("validationDetails").className = "validation-details hidden";
    $("saveStatus").textContent = "";
  }

  function renderOrigin(packet, internalDemo) {
    const badge = $("originBadge");
    const origin = packet.annotation?.provenance?.data_origin || "UNKNOWN";
    const tier = packet.annotation?.provenance?.annotation_tier || "UNSET";
    badge.className = "origin-badge";
    if (tier === "GOLD") {
      badge.classList.add("imported");
      badge.textContent = `GOLD · READ ONLY · ${origin}`;
    } else if (origin === "SYNTHETIC") {
      badge.classList.add("synthetic");
      badge.textContent = internalDemo ? "SYNTHETIC · HAND-AUTHORED DEMO" : "SYNTHETIC · AS RECORDED IN PACKET";
    } else {
      badge.classList.add("imported");
      badge.textContent = `IMPORTED PACKET · ORIGIN ${origin}`;
    }
    badge.classList.remove("hidden");
  }

  function acceptOpenedPacket(payload, { internalDemo = false } = {}) {
    state.sessionId = payload.session_id;
    state.packet = payload.packet;
    state.recordId = payload.record_id || null;
    state.syntheticFixture = internalDemo;
    state.readOnlyGold = payload.packet.annotation?.provenance?.annotation_tier === "GOLD";
    $("annotationEditor").value = JSON.stringify(payload.packet.annotation, null, 2);
    $("annotationEditor").disabled = state.readOnlyGold;
    $("formatJson").disabled = state.readOnlyGold;
    $("reviewNote").value = payload.review_note || "";
    $("reviewNote").disabled = state.readOnlyGold;
    $("packetWorkspace").classList.remove("hidden");
    renderOrigin(payload.packet, internalDemo);
    resetDerived();
    renderPreview(payload.packet.annotation);
    setNotice(state.readOnlyGold
      ? "Imported GOLD packet opened read-only. Its earlier human-review claim cannot be carried across edits, so annotation, notes, and saving are disabled."
      : internalDemo
        ? "Synthetic demonstration packet loaded from the hand-authored V1 fixture set. It is not real email and is not a human-reviewed gold record."
        : "Packet loaded into this local page. The original source and provenance remain fixed for this review session.");
    if (payload.validation) showValidation(payload.validation, $("annotationEditor").value);
    setBusy(false);
  }

  function showValidation(validation, editorValue) {
    state.lastValidation = validation;
    state.validatedText = editorValue;
    const status = $("mapperStatus");
    const labels = $("derivedLabels");
    const details = $("validationDetails");
    details.replaceChildren();
    const allMessages = [
      ...(validation.errors || []).map((item) => `Error: ${item}`),
      ...(validation.warnings || []).map((item) => `Review: ${item}`),
    ];
    const errors = validation.errors || [];
    if (!validation.valid) {
      status.className = "mapper-state invalid";
      status.textContent = "Validation failed";
      labels.replaceChildren(textElement("span", "muted", "No labels: the annotation did not pass validation."));
      details.className = "validation-details";
    } else {
      status.className = "mapper-state valid";
      status.textContent = validation.needs_review ? "Valid · review required" : "Valid · mapper ran";
      if (validation.needs_review) {
        labels.replaceChildren(textElement("span", "muted", "Derived labels withheld while this packet needs human review."));
      } else if (Array.isArray(validation.labels) && validation.labels.length) {
        labels.replaceChildren(...validation.labels.map((label) => textElement("span", "derived-label", label)));
      } else {
        labels.replaceChildren(textElement("span", "muted", "No derived labels for this validated annotation."));
      }
      details.className = allMessages.length ? "validation-details valid" : "validation-details hidden";
    }
    if (allMessages.length) {
      const list = document.createElement("ul");
      allMessages.forEach((message) => list.appendChild(textElement("li", "", message)));
      details.appendChild(list);
    } else if (!validation.valid && !errors.length) {
      details.appendChild(textElement("div", "", "Validation failed without a detailed message."));
    }
    if (validation.valid && validation.needs_review) {
      const stateLabel = $("reviewState");
      stateLabel.className = "review-state flagged";
      stateLabel.textContent = "Needs human review";
    }
  }

  async function loadDemos() {
    try {
      const data = await api("/api/demos");
      state.demos = Array.isArray(data.demos) ? data.demos : [];
      const select = $("demoSelect");
      select.replaceChildren();
      state.demos.forEach((demo) => {
        const option = document.createElement("option");
        option.value = demo.fixture_id;
        option.textContent = `${demo.fixture_id} · ${demo.subject || "Untitled"}`;
        select.appendChild(option);
      });
      if (!state.demos.length) {
        const option = document.createElement("option");
        option.textContent = "No standalone synthetic fixtures";
        select.appendChild(option);
      }
      setBusy(false);
      await refreshSavedRecords();
      if (state.demos.length) await loadDemo(state.demos[0].fixture_id);
      else setNotice("No standalone synthetic fixture was found. Open a V1 packet file to begin.", "warning");
    } catch (error) {
      setNotice(error.message, "error");
    }
  }

  async function loadDemo(fixtureId) {
    setBusy(true);
    setNotice("Loading a synthetic fixture…");
    try {
      const payload = await jsonPost("/api/open-demo", { fixture_id: fixtureId });
      acceptOpenedPacket(payload, { internalDemo: true });
    } catch (error) {
      setNotice(error.message, "error");
      setBusy(false);
    }
  }

  async function refreshSavedRecords() {
    const select = $("savedSelect");
    const previous = select.value;
    const data = await api("/api/records");
    select.replaceChildren();
    const records = Array.isArray(data.records) ? data.records : [];
    if (!records.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No saved reviews yet";
      select.appendChild(option);
    } else {
      records.forEach((record) => {
        const option = document.createElement("option");
        option.value = record.record_id;
        const review = record.needs_review ? " · review" : "";
          const tier = record.annotation_tier === "GOLD" ? " · GOLD · read only" : "";
          option.textContent = `${record.source_id} · ${record.subject || "Untitled"}${review}${tier}`;
        select.appendChild(option);
      });
      if (records.some((item) => item.record_id === previous)) select.value = previous;
    }
    setBusy(state.busy);
  }

  async function openSaved() {
    const recordId = $("savedSelect").value;
    if (!recordId) return;
    setBusy(true);
    setNotice("Reloading the saved local packet and its immutable original…");
    try {
      const payload = await api(`/api/records/${recordId}`);
      acceptOpenedPacket(payload);
      $("saveStatus").textContent = `Local record ${recordId}`;
    } catch (error) {
      setNotice(error.message, "error");
      setBusy(false);
    }
  }

  async function openFile(file) {
    if (!file) return;
    if (file.size > 1_000_000) {
      setNotice("Packet file exceeds the 1,000,000 byte limit.", "error");
      return;
    }
    setBusy(true);
    setNotice("Opening the selected packet in local memory…");
    try {
      const packet = JSON.parse(await file.text());
      const payload = await jsonPost("/api/open", packet);
      acceptOpenedPacket(payload);
    } catch (error) {
      setNotice(error.message || "The selected file is not a valid JSON packet.", "error");
      setBusy(false);
    } finally {
      $("packetFile").value = "";
    }
  }

  async function validateCurrent() {
    const parsed = currentAnnotation();
    if (parsed.error) {
      resetDerived();
      $("mapperStatus").className = "mapper-state invalid";
      $("mapperStatus").textContent = "Invalid JSON";
      $("derivedLabels").replaceChildren(textElement("span", "muted", "No labels: fix the annotation JSON first."));
      setNotice(parsed.error, "error");
      return null;
    }
    setBusy(true);
    setNotice("Checking exact source text, authored ranges, references and V1 semantics…");
    try {
      const payload = await jsonPost("/api/validate", { session_id: state.sessionId, annotation: parsed.value });
      showValidation(payload.validation, $("annotationEditor").value);
      setNotice(payload.validation.valid
        ? (payload.validation.needs_review ? "The annotation passes hard validation and still needs human review." : "The annotation passes V1 validation. Deterministic labels were derived by the local mapper.")
        : "The annotation has validation errors. Correct them before saving.", payload.validation.valid ? (payload.validation.needs_review ? "warning" : "") : "error");
      setBusy(false);
      return payload.validation;
    } catch (error) {
      setNotice(error.message, "error");
      setBusy(false);
      return null;
    }
  }

  async function saveCurrent() {
    const validation = await validateCurrent();
    if (!validation?.valid) return;
    const parsed = currentAnnotation();
    if (parsed.error) return;
    setBusy(true);
    $("saveStatus").textContent = "Saving local audit record…";
    try {
      const payload = await jsonPost("/api/save", {
        session_id: state.sessionId,
        annotation: parsed.value,
        review_note: $("reviewNote").value,
      });
      state.recordId = payload.record_id;
      $("saveStatus").textContent = `Saved local record ${payload.record_id} · ${payload.saved_at}`;
      setNotice("Saved locally with an append-only audit entry and an immutable copy of the original packet. The record remains in its incoming annotation tier.");
      await refreshSavedRecords();
      $("savedSelect").value = payload.record_id;
    } catch (error) {
      $("saveStatus").textContent = "";
      setNotice(error.message, "error");
    }
    setBusy(false);
  }

  $("loadDemo").addEventListener("click", () => loadDemo($("demoSelect").value));
  $("packetFile").addEventListener("change", (event) => openFile(event.target.files?.[0]));
  $("openSaved").addEventListener("click", openSaved);
  $("savedSelect").addEventListener("change", () => setBusy(state.busy));
  $("validateButton").addEventListener("click", validateCurrent);
  $("saveButton").addEventListener("click", saveCurrent);
  $("formatJson").addEventListener("click", () => {
    const parsed = currentAnnotation();
    if (parsed.error) {
      setNotice(parsed.error, "error");
      return;
    }
    $("annotationEditor").value = JSON.stringify(parsed.value, null, 2);
    resetDerived();
    renderPreview(parsed.value);
  });
  $("annotationEditor").addEventListener("input", () => {
    resetDerived();
    const parsed = currentAnnotation();
    if (parsed.error) {
      setNotice(`Annotation editor: ${parsed.error}`, "error");
      return;
    }
    renderPreview(parsed.value);
    setNotice("Unsaved annotation edit. Validate against the original source before saving.");
  });

  loadDemos();
})();
