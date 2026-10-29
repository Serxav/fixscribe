(function () {
  "use strict";
  var root = document.getElementById("job");
  if (!root) return;
  var jobId = root.dataset.jobId;
  var POLL_MS = 1500;
  var REPLAY_MS = 1700;
  var OPEN_AFTER_MS = 6000;
  var $ = function (id) { return document.getElementById(id); };
  var video = $("scan-video");
  var duration = 0;
  var shown = { video: false, ident: false, safety: false, turns: 0, segments: {}, cards: {} };
  var openTimer = null;

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function clock(seconds) {
    seconds = Math.max(0, Math.round(seconds || 0));
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
  }

  function title(text) {
    text = String(text || "");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  // The spoken step cuts ("step two", "paso 3", "next step", "siguiente paso"...) are marked;
  // "paso a paso" / "step by step" is not a cut.
  var NUMBER = "\\d+|one|two|three|four|five|six|seven|eight|nine|ten|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez";
  var CUT = new RegExp("\\b(?:(?:step|paso)\\s+(?:" + NUMBER + ")|next step|(?:siguiente|primer|[uú]ltimo) paso)\\b", "gi");
  function markCuts(text) {
    return escapeHtml(text).replace(CUT, '<mark class="cut">$&</mark>');
  }

  // ---- the video being scanned
  function showVideo(info) {
    if (shown.video || !info) return;
    shown.video = true;
    duration = info.duration_s || 0;
    $("duration").textContent = clock(duration);
    $("scan").style.setProperty("--ratio", info.width + " / " + info.height);
    $("scan").classList.toggle("portrait", info.height > info.width);
    video.src = info.url;
    video.play().catch(function () {});
    $("scan").classList.add("has-video");
  }

  function showIdentity(ident) {
    if (shown.ident || !ident) return;
    shown.ident = true;
    var parts = [ident.object, title(ident.category)];
    if (ident.task) parts.push(title(ident.task));
    $("tag-ident").innerHTML = parts.filter(Boolean).map(escapeHtml).join('<i class="sep"></i>');
    $("tag-ident").classList.remove("hidden");
  }

  var SAFETY = { normal: "Safe to do", caution: "Caution", professional_only: "Professional only" };
  function showSafety(safety) {
    if (shown.safety || !safety) return;
    shown.safety = true;
    var tag = $("tag-safety");
    tag.textContent = SAFETY[safety.level] || safety.level;
    tag.title = (safety.reasons || []).join(" ");
    tag.classList.add("run-safety-" + safety.level);
    tag.classList.remove("hidden");
  }

  // ---- what it heard
  function showHeard(heard) {
    if (!heard) return;
    var list = $("heard");
    if (heard.mode === "silent" || !heard.turns.length) {
      $("heard-note").textContent = "Silent video";
      list.innerHTML = '<li class="run-heard-empty muted small">No narration: FixScribe works from the picture alone.</li>';
      shown.turns = -1;
      return;
    }
    if (shown.turns === 0) list.innerHTML = "";
    heard.turns.slice(shown.turns).forEach(function (turn, k) {
      var li = document.createElement("li");
      li.className = "run-heard-line run-reveal";
      li.style.animationDelay = k * 90 + "ms";
      li.innerHTML = '<span class="mono t">' + clock(turn.t) + "</span><span>" + markCuts(turn.text) + "</span>";
      list.appendChild(li);
    });
    shown.turns = heard.turns.length;
  }

  // ---- steps on the timeline and as cards
  function showSteps(steps, draft) {
    if (!steps) return;
    $("steps-note").textContent = draft ? "First draft from Muse Spark, being checked…" : steps.length + " steps";
    var timeline = $("timeline");
    var cards = $("step-cards");
    steps.forEach(function (step, k) {
      var key = String(step.index);
      if (duration) {
        var segment = shown.segments[key];
        if (!segment) {
          segment = document.createElement("button");
          segment.type = "button";
          segment.className = "run-segment run-reveal";
          segment.style.animationDelay = k * 60 + "ms";
          segment.addEventListener("click", function () { seek(segment.dataset.start); });
          timeline.appendChild(segment);
          shown.segments[key] = segment;
        }
        segment.dataset.start = step.start_s;
        segment.dataset.end = step.end_s;
        segment.style.left = (100 * step.start_s / duration) + "%";
        segment.style.width = Math.max(0.6, 100 * (step.end_s - step.start_s) / duration) + "%";
        segment.title = step.index + ". " + step.title;
        segment.innerHTML = "<span>" + step.index + "</span>";
      }
      var card = shown.cards[key];
      if (!card) {
        card = document.createElement("li");
        card.className = "run-step-card run-reveal";
        card.style.animationDelay = k * 70 + "ms";
        card.innerHTML = '<button type="button" class="run-step-media"><span class="run-shimmer"></span></button>' +
          '<div class="run-step-text"><span class="mono n"></span><b></b><span class="muted small meta"></span></div>';
        card.querySelector(".run-step-media").addEventListener("click", function () { seek(card.dataset.start); });
        cards.appendChild(card);
        shown.cards[key] = card;
      }
      card.dataset.start = step.start_s;
      card.dataset.end = step.end_s;
      card.querySelector(".n").textContent = String(step.index).padStart(2, "0");
      card.querySelector("b").textContent = step.title;
      var meta = clock(step.start_s) + "–" + clock(step.end_s);
      if (step.count) meta += " · " + step.count + " " + (step.kind || "fastener") + (step.count === 1 ? "" : "s");
      card.querySelector(".meta").textContent = meta;
      setImage(card, step);
    });
  }

  function setImage(card, step) {
    var media = card.querySelector(".run-step-media");
    var src = step.overlay || step.image;
    if (!src || media.dataset.src === src) return;
    var img = new Image();
    img.alt = step.title;
    img.onload = function () {
      var old = media.querySelector("img");
      media.appendChild(img);
      requestAnimationFrame(function () { img.classList.add("in"); });
      if (old) setTimeout(function () { old.remove(); }, 600);
      var shimmer = media.querySelector(".run-shimmer");
      if (shimmer) shimmer.remove();
      if (step.overlay) {
        card.classList.add("seen");
        var badge = media.querySelector(".run-found") || document.createElement("span");
        badge.className = "run-found";
        badge.textContent = step.found ? step.found + " found by SAM" : step.part ? "Part found" : "Checked";
        if (step.found || step.part) badge.classList.add("hit");
        media.appendChild(badge);
      }
    };
    media.dataset.src = src;
    img.src = src;
  }

  function seek(start) {
    if (!video.src || start == null) return;
    video.currentTime = Number(start) + 0.05;
    video.play().catch(function () {});
  }

  // The step being played lights up on the timeline and in the list.
  function follow() {
    if (duration && video.src) {
      var t = video.currentTime || 0;
      $("playhead").style.left = (100 * t / duration) + "%";
      [shown.segments, shown.cards].forEach(function (group) {
        Object.keys(group).forEach(function (key) {
          var el = group[key];
          el.classList.toggle("active", t >= Number(el.dataset.start) && t < Number(el.dataset.end));
        });
      });
    }
    requestAnimationFrame(follow);
  }

  // ---- stages, status and the end
  function render(data) {
    var percent = Math.round((data.progress || 0) * 100);
    if (data.state === "done") percent = 100;
    $("bar").style.width = percent + "%";
    $("percent").textContent = percent + "%";
    var stages = data.stages || [];
    var running = stages.filter(function (s) { return s.status === "running"; })[0];
    var label = data.state === "done" ? "Your guide is ready"
      : data.state === "failed" ? "Stopped" : running ? running.label + "…" : "Starting…";
    $("stage-label").textContent = label;
    $("scan-caption").textContent = running ? running.label : data.state === "done" ? "Done" : label;
    $("live").className = "run-live " + data.state;
    root.classList.toggle("is-done", data.state === "done");
    $("error").textContent = data.error || "";
    $("error").classList.toggle("hidden", !data.error);
    $("guide-link").classList.toggle("hidden", data.state !== "done");
    $("resume-button").classList.toggle("hidden", data.state !== "failed");
    $("retry-link").classList.toggle("hidden", data.state !== "failed");
    if (stages.length) {
      $("stage-list").innerHTML = stages.map(function (s) {
        var time = s.seconds != null && s.status !== "waiting" ? s.seconds.toFixed(1) + " s" : "";
        var error = s.error ? '<span class="err">' + escapeHtml(s.error) + "</span>" : "";
        return '<li class="' + s.status + '"><i class="dot ' + s.status + '"></i><span>' + escapeHtml(s.label) +
          '</span><span class="muted small tabular">' + time + "</span>" + error + "</li>";
      }).join("");
    }
    var story = data.story || {};
    showVideo(story.video);
    showIdentity(story.identity);
    showHeard(story.heard);
    showSteps(story.steps, story.draft);
    showSafety(story.safety);
    if (data.state === "done") finish(data);
  }

  function finish(data) {
    if (!$("done").classList.contains("hidden") || root.dataset.stayed) return;
    var story = data.story || {};
    var steps = story.steps || [];
    var counted = steps.reduce(function (sum, s) { return sum + (s.count || 0); }, 0);
    var seconds = (data.stages || []).reduce(function (sum, s) { return sum + (s.seconds || 0); }, 0);
    $("done-title").textContent = story.identity ? story.identity.object : "Your repair";
    var stats = [
      [steps.length, "steps"],
      [counted, "fasteners to track"],
      [story.safety ? SAFETY[story.safety.level] || story.safety.level : "Checked", "safety"],
      [clock(seconds), "to make the guide"],
    ];
    $("done-stats").innerHTML = stats.map(function (s) {
      return "<div><dt>" + escapeHtml(s[0]) + "</dt><dd>" + escapeHtml(s[1]) + "</dd></div>";
    }).join("");
    $("done").classList.remove("hidden");
    if (!replaying) openTimer = setTimeout(function () { window.location.href = "/guides/" + jobId; }, OPEN_AFTER_MS);
  }

  $("done-stay").addEventListener("click", function () {
    clearTimeout(openTimer);
    root.dataset.stayed = "1";
    $("done").classList.add("hidden");
  });

  function poll() {
    fetch("/api/jobs/" + jobId, { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.state === "done" && replaying) { replay(data); return; }
        render(data);
        if (data.state !== "done" && data.state !== "failed") setTimeout(poll, POLL_MS);
      })
      .catch(function () { setTimeout(poll, POLL_MS * 2); });
  }

  // ---- replay: a finished job shown stage by stage, with its real results (?replay=1)
  var replaying = /[?&]replay=1\b/.test(window.location.search);
  var REVEALS = {
    ingest: ["video"], transcribe: ["heard"], identify: ["identity"], analyze: ["steps"],
    plan: ["plan"], safety: ["safety"], frames: ["frames"], perception: ["perception"],
  };

  function partial(story, done) {
    var has = {};
    done.forEach(function (name) { (REVEALS[name] || []).forEach(function (k) { has[k] = true; }); });
    var out = {};
    if (has.video) out.video = story.video;
    if (has.heard) out.heard = story.heard;
    if (has.identity) out.identity = story.identity;
    if (has.safety) out.safety = story.safety;
    if (has.steps && story.steps) {
      out.draft = !has.plan;
      out.steps = story.steps.map(function (s) {
        return {
          index: s.index, title: s.title, start_s: s.start_s, end_s: s.end_s,
          kind: has.plan ? s.kind : null, count: has.plan ? s.count : 0,
          image: has.frames ? s.image : null,
          overlay: has.perception ? s.overlay : null, found: s.found, part: s.part,
        };
      });
    }
    if (has.perception) out.fasteners = story.fasteners;
    return out;
  }

  function replay(data) {
    $("replay-tag").classList.remove("hidden");
    var stages = data.stages;
    var k = 0;
    function tick() {
      var done = stages.slice(0, k).map(function (s) { return s.name; });
      var view = {
        state: k >= stages.length ? "done" : "running",
        progress: k / stages.length,
        stages: stages.map(function (s, i) {
          return i < k ? s : i === k ? { name: s.name, label: s.label, status: "running" } : { name: s.name, label: s.label, status: "waiting" };
        }),
        story: partial(data.story || {}, done),
      };
      render(view);
      if (k < stages.length) { k += 1; setTimeout(tick, REPLAY_MS); }
    }
    tick();
  }

  $("resume-button").addEventListener("click", function () {
    $("resume-button").disabled = true;
    fetch("/api/jobs/" + jobId + "/resume", { method: "POST" })
      .then(function () { $("resume-button").disabled = false; poll(); })
      .catch(function () { $("resume-button").disabled = false; });
  });

  requestAnimationFrame(follow);
  poll();
})();
