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

  var live = document.querySelector("[data-live]");
  if (live && watch && !reduce) {
    var shots = live.querySelectorAll(".live-shot");
    var current = 0;
    var timer = null;
    var turn = function () {
      shots[current].classList.remove("on");
      current = (current + 1) % shots.length;
      shots[current].classList.add("on");
    };
    new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !timer) timer = window.setInterval(turn, 5200);
        if (!entry.isIntersecting && timer) { window.clearInterval(timer); timer = null; }
      });
    }, { threshold: 0.3 }).observe(live);
  }

  var CYCLE = 7000;
  var play = function (svg, index) {
    var delay = -((index * 1370) % CYCLE);
    var loop = { duration: CYCLE, iterations: Infinity, delay: delay, easing: "linear" };
    svg.querySelectorAll(".mk").forEach(function (mark) {
      var at = parseFloat(mark.getAttribute("data-at")) || 0.2;
      mark.animate([
        { opacity: 0, offset: 0 }, { opacity: 0, offset: at }, { opacity: 1, offset: at + 0.03 },
        { opacity: 1, offset: 0.88 }, { opacity: 0, offset: 0.95 }, { opacity: 0, offset: 1 }
      ], loop);
      var cut = mark.querySelector(".mk-cut");
      if (cut) cut.animate([
        { opacity: 0, offset: 0 }, { opacity: 0, offset: Math.min(0.86, at + 0.05) },
        { opacity: 1, offset: Math.min(0.87, at + 0.1) }, { opacity: 1, offset: 1 }
      ], loop);
    });
    var scan = svg.querySelector(".mk-scan");
    if (scan) scan.animate([
      { transform: "translateY(0)", opacity: 1, offset: 0 },
      { transform: "translateY(1120px)", opacity: 1, offset: 0.2 },
      { transform: "translateY(1120px)", opacity: 0, offset: 1 }
    ], { duration: CYCLE, iterations: Infinity, delay: delay, easing: "ease-in-out" });
    var aim = svg.querySelector(".mk-aim");
    if (!aim) return;
    var stops = aim.getAttribute("data-stops").split(";").map(function (s) { return s.split(","); });
    var frames = [{ transform: "translate(500px,500px) scale(1.6)", opacity: 0, offset: 0 },
      { transform: "translate(500px,500px) scale(1.6)", opacity: 0, offset: 0.16 }];
    svg.querySelectorAll(".mk").forEach(function (mark, i) {
      var at = parseFloat(mark.getAttribute("data-at")) || 0.2;
      var to = "translate(" + stops[i][0] + "px," + stops[i][1] + "px) scale(1)";
      frames.push({ transform: to, opacity: 1, offset: Math.max(frames[frames.length - 1].offset + 0.001, at - 0.02) });
      frames.push({ transform: to, opacity: 1, offset: at + 0.01 });
    });
    var last = frames[frames.length - 1];
    frames.push({ transform: last.transform, opacity: 0, offset: Math.min(0.99, last.offset + 0.06) });
    frames.push({ transform: last.transform, opacity: 0, offset: 1 });
    aim.animate(frames, { duration: CYCLE, iterations: Infinity, delay: delay, easing: "ease-in-out" });
  };

  var stage = document.querySelector("[data-mosaic-stage]");
  var grid = stage && stage.querySelector("[data-mosaic]");
  if (grid && !reduce && grid.animate) {
    Array.prototype.forEach.call(grid.querySelectorAll(".mz-tile svg"), play);
  }
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
    var share = window.matchMedia("(max-width: 699px)").matches ? 0.9 : 0.33;
    startScale = Math.max(1, Math.min(stick.clientWidth * share / size, (stick.clientHeight - 30) * 0.86 / size));
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
