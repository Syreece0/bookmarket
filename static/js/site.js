(function () {
  // Mobile navigation
  var toggle = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Hero slider: keyboard and screen-reader friendly, pauses on hover/focus, respects reduced motion.
  var hero = document.querySelector("[data-hero]");
  if (hero) {
    var slides = hero.querySelectorAll(".hero-slide");
    var dots = hero.querySelectorAll(".dots button");
    var idx = 0, timer = null;
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    function show(n) {
      idx = (n + slides.length) % slides.length;
      slides.forEach(function (s, i) { s.classList.toggle("active", i === idx); s.setAttribute("aria-hidden", i === idx ? "false" : "true"); });
      dots.forEach(function (d, i) { d.setAttribute("aria-current", i === idx ? "true" : "false"); });
    }
    function start() { if (!reduce && slides.length > 1) { stop(); timer = setInterval(function () { show(idx + 1); }, 7000); } }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    var prev = hero.querySelector("[data-prev]"), next = hero.querySelector("[data-next]");
    if (prev) prev.addEventListener("click", function () { show(idx - 1); });
    if (next) next.addEventListener("click", function () { show(idx + 1); });
    dots.forEach(function (d, i) { d.addEventListener("click", function () { show(i); }); });
    hero.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") show(idx - 1);
      if (e.key === "ArrowRight") show(idx + 1);
    });
    ["mouseenter", "focusin"].forEach(function (ev) { hero.addEventListener(ev, stop); });
    ["mouseleave", "focusout"].forEach(function (ev) { hero.addEventListener(ev, start); });
    show(0); start();
  }
})();

// CSRF helper for fetch() calls
function csrfToken() {
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}
function saveProgress(url, payload) {
  return fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(payload)
  }).catch(function () {});
}
