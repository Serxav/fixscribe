(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var clamp = function (v) { return Math.min(1, Math.max(0, v)); };
  var ease = function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
  var watch = "IntersectionObserver" in window;

  var items = document.querySelectorAll("[data-reveal]");
  if (reduce || !watch) {
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

  var steps = document.querySelectorAll(".story-step");
  var screens = document.querySelectorAll(".device-screen .screen");
  var dots = document.querySelectorAll(".story-dots span");
  var show = function (index) {
    steps.forEach(function (el, i) { el.classList.toggle("on", i === index); });
    screens.forEach(function (el, i) { el.classList.toggle("on", i === index); });
    dots.forEach(function (el, i) { el.classList.toggle("on", i === index); });
  };
  if (steps.length) {
    show(0);
    if (watch) {
      var phone = window.matchMedia("(max-width: 899px)").matches;
      var reading = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) show(parseInt(entry.target.getAttribute("data-step"), 10) || 0);
        });
      }, { rootMargin: phone ? "-58% 0px -32% 0px" : "-45% 0px -45% 0px" });
      steps.forEach(function (el) { reading.observe(el); });
    }
  }

  var stage = document.querySelector("[data-mosaic-stage]");
  var grid = stage && stage.querySelector("[data-mosaic]");
  if (!grid || reduce) return;
  var stick = stage.querySelector(".mosaic-stick");
  var caption = stage.querySelector(".mosaic-caption");
  var center = grid.querySelector("[data-center]");
  var art = center.querySelector("svg");
  var tiles = Array.prototype.slice.call(grid.children);
  var startScale = 1;
  var queued = false;

  var measure = function () {
    var size = center.offsetWidth;
    var cx = center.offsetLeft + size / 2;
    var cy = center.offsetTop + size / 2;
    tiles.forEach(function (tile) {
      tile.dx = tile.offsetLeft + tile.offsetWidth / 2 - cx;
      tile.dy = tile.offsetTop + tile.offsetHeight / 2 - cy;
      tile.ring = Math.round(Math.max(Math.abs(tile.dx), Math.abs(tile.dy)) / size);
    });
    startScale = Math.max(1, Math.min(stick.clientWidth * 0.9 / size, (stick.clientHeight - 30) * 0.86 / size));
    var big = size * startScale;
    center.classList.add("big");
    art.style.width = art.style.height = big.toFixed(1) + "px";
    art.style.left = art.style.top = ((size - big) / 2).toFixed(1) + "px";
    art.style.borderRadius = (12 * startScale).toFixed(1) + "px";
  };

  var draw = function () {
    queued = false;
    var box = stage.getBoundingClientRect();
    var room = box.height - window.innerHeight;
    var p = room > 0 ? clamp(-box.top / room) : 1;
    var shrink = ease(clamp((p - 0.1) / 0.4));
    var scale = startScale + (1 - startScale) * shrink;
    art.style.transform = "scale(" + (scale / startScale).toFixed(4) + ")";
    center.style.setProperty("--detail", clamp(1 - shrink * 2.2).toFixed(2));
    tiles.forEach(function (tile) {
      if (tile === center) return;
      var start = 0.24 + 0.1 * (tile.ring - 1);
      var e = ease(clamp((p - start) / 0.28));
      var pull = (1 - e) * 0.45;
      tile.style.opacity = e.toFixed(3);
      tile.style.transform = "translate(" + (-tile.dx * pull).toFixed(1) + "px," + (-tile.dy * pull).toFixed(1) +
        "px) scale(" + (0.7 + 0.3 * e).toFixed(3) + ")";
    });
    var c = clamp((p - 0.76) / 0.14);
    caption.style.opacity = c.toFixed(2);
    caption.style.transform = "translateY(" + ((1 - c) * 16).toFixed(1) + "px)";
  };

  var schedule = function () { if (!queued) { queued = true; window.requestAnimationFrame(draw); } };
  measure();
  draw();
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", function () { measure(); schedule(); });
})();
