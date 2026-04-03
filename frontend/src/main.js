import "./styles.css";
import { GlobalWorkerOptions, getDocument } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

const state = {
  activeDocument: null,
  isBusy: false,
};

const labelPalette = [
  "#ff5d73",
  "#1f9d8b",
  "#4f6af0",
  "#ef8f00",
  "#8138ff",
  "#0a7cff",
  "#d553c2",
  "#4a9942",
  "#cf3535",
  "#8b5e34",
];

const app = document.querySelector("#app");

app.innerHTML = `
  <main class="shell">
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">Docling Parse + Heron + EasyOCR</p>
        <h1>Compare Docling's classic parse stack against the Granite VLM.</h1>
        <p class="lede">
          Upload a PDF, run Docling with the Heron layout model, EasyOCR, and
          table structure extraction, then inspect the resulting provenance
          boxes directly on top of each page.
        </p>
      </div>
      <form class="upload-panel" id="upload-form">
        <label class="upload-drop" for="pdf-input">
          <span class="upload-title">Choose a PDF</span>
          <span class="upload-subtitle">Single-file upload. Large PDFs can take a while.</span>
        </label>
        <input id="pdf-input" name="file" type="file" accept="application/pdf" />
        <button class="upload-button" type="submit">Run Heron + EasyOCR</button>
        <p class="status" id="status">Waiting for a PDF.</p>
      </form>
    </section>

    <section class="workspace">
      <aside class="sidebar">
        <div class="panel">
          <div class="panel-header">
            <h2>Document</h2>
            <span class="pill" id="summary-pill">No file</span>
          </div>
          <div class="meta-grid" id="meta-grid">
            <div class="meta-card">
              <span class="meta-label">Pages</span>
              <strong>0</strong>
            </div>
            <div class="meta-card">
              <span class="meta-label">Regions</span>
              <strong>0</strong>
            </div>
            <div class="meta-card">
              <span class="meta-label">Time</span>
              <strong>n/a</strong>
            </div>
            <div class="meta-card">
              <span class="meta-label">Stack</span>
              <strong>n/a</strong>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <h2>Legend</h2>
          </div>
          <div class="legend" id="legend">
            <p class="empty-copy">Run a document to see detected label types.</p>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <h2>Markdown</h2>
          </div>
          <pre class="markdown-output" id="markdown-output">No output yet.</pre>
        </div>
      </aside>

      <section class="viewer-shell">
        <div class="viewer-toolbar">
          <div>
            <h2>Layout Viewer</h2>
            <p>PDF.js canvas with provenance overlays from Heron + EasyOCR.</p>
          </div>
          <a class="download-link disabled" id="download-link" href="#" target="_blank" rel="noreferrer">
            Open source PDF
          </a>
        </div>
        <div class="viewer-pages" id="viewer-pages">
          <div class="viewer-empty">
            <p>The viewer will appear here after a PDF upload finishes.</p>
          </div>
        </div>
      </section>
    </section>
  </main>
`;

const form = document.querySelector("#upload-form");
const input = document.querySelector("#pdf-input");
const statusNode = document.querySelector("#status");
const viewerPages = document.querySelector("#viewer-pages");
const legend = document.querySelector("#legend");
const markdownOutput = document.querySelector("#markdown-output");
const metaGrid = document.querySelector("#meta-grid");
const summaryPill = document.querySelector("#summary-pill");
const downloadLink = document.querySelector("#download-link");

function setStatus(message, tone = "neutral") {
  statusNode.textContent = message;
  statusNode.dataset.tone = tone;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function colorForLabel(label, indexMap) {
  const index = indexMap.get(label) ?? 0;
  return labelPalette[index % labelPalette.length];
}

function formatElapsed(runtime) {
  if (typeof runtime?.elapsedSeconds !== "number") {
    return "n/a";
  }

  return `${runtime.elapsedSeconds.toFixed(2)}s`;
}

function updateMeta(summary, runtime, filename) {
  summaryPill.textContent = filename ?? "No file";
  metaGrid.innerHTML = `
    <div class="meta-card">
      <span class="meta-label">Pages</span>
      <strong>${summary?.pageCount ?? 0}</strong>
    </div>
    <div class="meta-card">
      <span class="meta-label">Regions</span>
      <strong>${summary?.itemCount ?? 0}</strong>
    </div>
    <div class="meta-card">
      <span class="meta-label">Time</span>
      <strong>${formatElapsed(runtime)}</strong>
    </div>
    <div class="meta-card">
      <span class="meta-label">Stack</span>
      <strong>${runtime?.displayName ?? "n/a"}</strong>
    </div>
  `;
}

function renderLegend(labels) {
  const entries = Object.entries(labels ?? {});
  if (!entries.length) {
    legend.innerHTML = `<p class="empty-copy">Run a document to see detected label types.</p>`;
    return new Map();
  }

  const labelIndex = new Map(entries.map(([label], index) => [label, index]));
  legend.innerHTML = entries
    .map(
      ([label, count]) => `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${colorForLabel(label, labelIndex)}"></span>
          <span class="legend-label">${label.replaceAll("_", " ")}</span>
          <span class="legend-count">${count}</span>
        </div>
      `,
    )
    .join("");

  return labelIndex;
}

async function renderDocument(payload) {
  state.activeDocument = payload;

  updateMeta(payload.summary, payload.runtime, payload.filename);
  markdownOutput.textContent = payload.markdown || "No markdown output.";
  const labelIndex = renderLegend(payload.summary?.labels);

  downloadLink.href = payload.pdfUrl;
  downloadLink.classList.remove("disabled");

  viewerPages.innerHTML = `<div class="viewer-loading">Rendering PDF pages…</div>`;

  const pdf = await getDocument(payload.pdfUrl).promise;
  viewerPages.innerHTML = "";

  for (const pageInfo of payload.pages) {
    const page = await pdf.getPage(pageInfo.pageNo);
    const viewport = page.getViewport({ scale: 1.5 });

    const pageCard = document.createElement("article");
    pageCard.className = "page-card";

    const pageHeader = document.createElement("header");
    pageHeader.className = "page-header";
    pageHeader.innerHTML = `
      <h3>Page ${pageInfo.pageNo}</h3>
      <span>${pageInfo.items.length} regions</span>
    `;

    const stage = document.createElement("div");
    stage.className = "page-stage";
    stage.style.width = `${viewport.width}px`;
    stage.style.height = `${viewport.height}px`;

    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    canvas.className = "pdf-canvas";
    stage.appendChild(canvas);

    const overlay = document.createElement("div");
    overlay.className = "overlay-layer";
    stage.appendChild(overlay);

    await page.render({
      canvasContext: canvas.getContext("2d"),
      viewport,
    }).promise;

    for (const item of pageInfo.items) {
      const box = document.createElement("button");
      box.type = "button";
      box.className = "layout-box";
      box.style.left = `${(item.bbox.left / pageInfo.width) * 100}%`;
      box.style.top = `${(item.bbox.top / pageInfo.height) * 100}%`;
      box.style.width = `${(item.bbox.width / pageInfo.width) * 100}%`;
      box.style.height = `${(item.bbox.height / pageInfo.height) * 100}%`;
      box.style.setProperty("--box-color", colorForLabel(item.label, labelIndex));
      box.title = `${item.label}${item.text ? `: ${item.text}` : ""}`;
      box.dataset.label = item.label;

      const info = document.createElement("span");
      info.className = "box-tooltip";
      info.innerHTML = `
        <strong>${escapeHtml(item.label.replaceAll("_", " "))}</strong>
        <span>${escapeHtml(item.text || "No text extracted for this region.")}</span>
      `;
      box.appendChild(info);
      overlay.appendChild(box);
    }

    pageCard.append(pageHeader, stage);
    viewerPages.appendChild(pageCard);
  }
}

async function submitForm(event) {
  event.preventDefault();

  const [file] = input.files || [];
  if (!file) {
    setStatus("Choose a PDF before starting.", "error");
    return;
  }

  if (state.isBusy) {
    return;
  }

  state.isBusy = true;
  setStatus("Uploading PDF and running Heron + EasyOCR. This can take a while.", "busy");
  viewerPages.innerHTML = `<div class="viewer-loading">Docling is processing the upload…</div>`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/api/documents", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Upload failed." }));
      throw new Error(error.detail || "Upload failed.");
    }

    const payload = await response.json();
    await renderDocument(payload);
    const elapsed = formatElapsed(payload.runtime);
    setStatus(`Processed ${payload.filename}${elapsed === "n/a" ? "" : ` in ${elapsed}`}.`, "success");
  } catch (error) {
    viewerPages.innerHTML = `
      <div class="viewer-empty">
        <p>${escapeHtml(error.message || "The document could not be processed.")}</p>
      </div>
    `;
    setStatus(error.message || "The document could not be processed.", "error");
  } finally {
    state.isBusy = false;
  }
}

form.addEventListener("submit", submitForm);
