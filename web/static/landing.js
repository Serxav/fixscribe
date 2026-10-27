// Page motion: content rises in as it enters the screen, and the mosaic of objects unfolds as
// you scroll (one object big, then fourteen more around it). Everything is visible without it.
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var clamp = function (v) { return Math.min(1, Math.max(0, v)); };
  var ease = function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };

  // 1. Reveal on scroll
  var items = document.querySelectorAll("[data-reveal]");
  if (reduce || !("IntersectionObserver" in window)) {
    items.forEach(function (el) { el.classList.add("in"); });
  } else {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in");
        seen.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    items.forEach(function (el) { seen.observe(el); });
  }

  // 2. The mosaic
  var stage = document.querySelector("[data-mosaic-stage]");
  var grid = stage && stage.querySelector("[data-mosaic]");
  if (!grid || reduce) return;
  var stick = stage.querySelector(".mosaic-stick");
  var caption = stage.querySelector(".mosaic-caption");
  var center = grid.querySelector("[data-center]");
  var tiles = Array.prototype.slice.call(grid.children);
  var startScale = 1;
  var queued = false;

  // Where each tile sits relative to the center tile, in tiles (offsets ignore transforms).
  var measure = function () {
    var size = center.offsetWidth;
    var cx = center.offsetLeft + size / 2;
    var cy = center.offsetTop + size / 2;
    tiles.forEach(function (tile) {
      tile.dx = tile.offsetLeft + tile.offsetWidth / 2 - cx;
      tile.dy = tile.offsetTop + tile.offsetHeight / 2 - cy;
      tile.ring = Math.round(Math.max(Math.abs(tile.dx), Math.abs(tile.dy)) / size);
    });
    var box = grid.getBoundingClientRect();
    // Start with the center tile filling most of the screen, centred on the grid's middle.
    startScale = Math.max(1, Math.min(stick.clientWidth * 0.86 / size, (stick.clientHeight - 40) * 0.82 / size));
    grid.dataset.ready = box.width > 0 ? "1" : "";
  };

  var draw = function () {
    queued = false;
    var box = stage.getBoundingClientRect();
    var room = box.height - window.innerHeight;
    var p = room > 0 ? clamp(-box.top / room) : 1;
    var shrink = ease(clamp((p - 0.06) / 0.42));
    center.style.transform = "scale(" + (startScale + (1 - startScale) * shrink).toFixed(3) + ")";
    tiles.forEach(function (tile) {
      if (tile === center) return;
      var start = 0.22 + 0.16 * (tile.ring - 1);
      var e = ease(clamp((p - start) / 0.3));
      var pull = (1 - e) * 0.45;
      tile.style.opacity = e.toFixed(3);
      tile.style.transform = "translate(" + (-tile.dx * pull).toFixed(1) + "px," + (-tile.dy * pull).toFixed(1) +
        "px) scale(" + (0.7 + 0.3 * e).toFixed(3) + ")";
    });
    caption.style.opacity = clamp((p - 0.74) / 0.14).toFixed(2);
    caption.style.transform = "translateY(" + ((1 - clamp((p - 0.74) / 0.14)) * 16).toFixed(1) + "px)";
  };

  var schedule = function () { if (!queued) { queued = true; window.requestAnimationFrame(draw); } };
  measure();
  draw();
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", function () { measure(); schedule(); });
})();
