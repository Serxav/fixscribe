"use strict";

const STAGE_LABELS = {
  ingest: "Preparing the video",
  transcribe: "Listening to the narration",
  scenes: "Finding the steps",
  analyze: "Watching the repair",
  guide: "Writing the guide",
  frames: "Picking the best photos",
};

function jobId() {
  const holder = document.getElementById("job");
  if (holder && holder.dataset.jobId) {
    return holder.dataset.jobId;
  }
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

async function refresh() {
  const id = jobId();
  const bar = document.getElementById("progress-bar");
  const stageLabel = document.getElementById("stage-label");
  const stateLabel = document.getElementById("state-label");
  const errorBox = document.getElementById("error");
  const guideLink = document.getElementById("guide-link");
  const retryLink = document.getElementById("retry-link");
  let status;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`);
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }
    status = await response.json();
  } catch {
    if (stateLabel) {
      stateLabel.textContent = "Could not reach the server, retrying…";
    }
    return;
  }
  const progress = Math.max(0, Math.min(1, Number(status.progress || 0)));
  if (bar) {
    bar.style.width = `${progress * 100}%`;
  }
  if (stageLabel) {
    stageLabel.textContent = STAGE_LABELS[status.stage] || status.stage || "";
  }
  if (stateLabel) {
    stateLabel.textContent = status.state || "";
  }
  const stageKeys = Object.keys(STAGE_LABELS);
  const currentIndex = stageKeys.indexOf(status.stage);
  document.querySelectorAll("#stage-list [data-stage]").forEach((item) => {
    const index = stageKeys.indexOf(item.dataset.stage);
    const done = status.state === "done" || (currentIndex >= 0 && index < currentIndex);
    item.classList.toggle("is-done", done);
    item.classList.toggle("is-current", status.state !== "done" && index === currentIndex);
    const dot = item.querySelector(".stage-dot");
    if (dot) {
      dot.textContent = done ? "✓" : String(index + 1);
    }
  });
  if (status.state === "done") {
    window.clearInterval(window.__fixscribeTimer);
    if (guideLink) {
      guideLink.classList.remove("hidden");
    }
  } else if (status.state === "failed") {
    window.clearInterval(window.__fixscribeTimer);
    if (errorBox) {
      errorBox.textContent = status.error || "The job failed.";
      errorBox.style.display = "flex";
    }
    if (retryLink) {
      retryLink.classList.remove("hidden");
    }
  }
}

window.__fixscribeTimer = window.setInterval(refresh, 2000);
void refresh();
