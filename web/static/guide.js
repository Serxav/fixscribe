"use strict";

// Segmented control: switch Take apart / Put back without a reload.
const tabs = document.querySelectorAll(".segmented [data-view]");
const panels = {
  "take-apart": document.getElementById("view-take-apart"),
  "put-back": document.getElementById("view-put-back"),
};
tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.setAttribute("aria-selected", String(item === tab)));
    const view = tab.dataset.view;
    Object.entries(panels).forEach(([key, panel]) => {
      if (panel) {
        panel.hidden = key !== view;
      }
    });
  });
});

// Cards fade-and-rise when they enter the viewport.
const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.08 }
);
document.querySelectorAll(".reveal").forEach((card) => revealObserver.observe(card));

// Step clips play only while their card is on screen.
const clipObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      const video = entry.target;
      if (entry.isIntersecting) {
        video.play().catch(() => {});
      } else {
        video.pause();
      }
    });
  },
  { threshold: 0.25 }
);
document.querySelectorAll("[data-step-clip]").forEach((video) => clipObserver.observe(video));

// Bottom sheet: full video, seek to the step, pause at its end.
const sheetRoot = document.getElementById("sheet-root");
const sheetVideo = document.getElementById("sheet-video");
let sheetEnd = null;
function closeSheet() {
  if (!sheetRoot || !sheetVideo) {
    return;
  }
  sheetVideo.pause();
  sheetRoot.hidden = true;
  sheetEnd = null;
}
function onTimeUpdate() {
  if (sheetEnd !== null && sheetVideo && sheetVideo.currentTime >= sheetEnd) {
    sheetVideo.pause();
  }
}
if (sheetVideo) {
  sheetVideo.addEventListener("timeupdate", onTimeUpdate);
}
document.querySelectorAll("[data-watch]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!sheetRoot || !sheetVideo) {
      return;
    }
    const start = Number(button.dataset.start || 0);
    sheetEnd = Number(button.dataset.end || 0) || null;
    sheetRoot.hidden = false;
    const seekAndPlay = () => {
      sheetVideo.currentTime = start;
      sheetVideo.play().catch(() => {});
    };
    if (sheetVideo.readyState >= 1) {
      seekAndPlay();
    } else {
      sheetVideo.addEventListener("loadedmetadata", seekAndPlay, { once: true });
    }
  });
});
document.querySelectorAll("[data-close-sheet]").forEach((el) => {
  el.addEventListener("click", closeSheet);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeSheet();
  }
});
