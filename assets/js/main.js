/*
 * DNA landing page
 * ----------------
 * The 3D helix is a pre-rendered Blender (Cycles) fly-through split into
 * clips. Each section change plays the clip that moves the camera from the
 * current shot to the next one (or its reversed twin when going back), while
 * the copy leaves and enters with masked line reveals.
 *
 *   state 0 (hero) --t1--> state 1 --t2--> state 2 --t3--> state 0
 *   reversed clips (t1r, t2r, t3r) run the same moves backwards.
 */
(() => {
  "use strict";

  const N = 3;
  const VIDEO_DIR = "assets/video/";
  const STILLS = ["assets/img/hero.jpg", "assets/img/s2.jpg", "assets/img/s3.jpg"];
  const FWD = ["t1", "t2", "t3"]; // i -> i + 1
  const REV = ["t1r", "t2r", "t3r"]; // i + 1 -> i
  const IDLE = ["idle0", "idle1", "idle2"]; // seamless loops played while a section rests
  const IDLE_FADE = 260; // ms: blend from a finished move into its idle loop
  const MOVE_FADE = 320; // ms: blend from a drifting idle loop into a move
  // H.264 MP4 where it is natively supported (Safari, Chrome, Edge), VP9 WebM otherwise
  const probe = document.createElement("video");
  const EXT = probe.canPlayType('video/mp4; codecs="avc1.640028"') === "probably" ? ".mp4" : ".webm";

  const root = document.documentElement;
  const stage = document.getElementById("stage");
  const stills = Array.from(document.querySelectorAll("[data-still]"));
  const panels = Array.from(document.querySelectorAll(".panel"));
  const pagerBtns = Array.from(document.querySelectorAll(".pager [data-goto]"));
  const menuToggle = document.querySelector(".menu-toggle");
  const menu = document.getElementById("menu");
  const modal = document.getElementById("film");
  const modalVideo = modal.querySelector("video");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  let state = 0;
  let busy = false;
  let unlockedAt = 0;
  let menuOpen = false;
  let modalOpen = false;
  let topZ = 2;
  let idleToken = 0;
  let visibleIdle = null;
  const clips = {};

  /* ------------------------------------------------------------ text setup */
  panels.forEach((p) => {
    p.querySelectorAll(".line").forEach((l, i) => l.style.setProperty("--i", i));
    [".title", ".lead", ".cta"].forEach((sel, i) => {
      const el = p.querySelector(sel);
      if (el) el.style.setProperty("--i", i);
    });
  });
  menu.querySelectorAll(".line").forEach((l, i) => l.style.setProperty("--i", i));

  function enter(panel) {
    clearTimeout(panel._t);
    panel.classList.remove("is-out", "is-reset");
    void panel.offsetWidth;
    panel.classList.add("is-in");
  }

  function leave(panel) {
    if (!panel.classList.contains("is-in")) return;
    panel.classList.remove("is-in");
    panel.classList.add("is-out");
    clearTimeout(panel._t);
    panel._t = setTimeout(() => {
      panel.classList.add("is-reset");
      panel.classList.remove("is-out");
      void panel.offsetWidth;
      panel.classList.remove("is-reset");
    }, 950);
  }

  function setActive(i) {
    root.dataset.state = String(i);
    pagerBtns.forEach((b) => b.classList.toggle("is-active", Number(b.dataset.goto) === i));
    const id = panels[i].id;
    if (history.replaceState) history.replaceState(null, "", i === 0 ? location.pathname + location.search : "#" + id);
  }

  /* ----------------------------------------------------------------- clips */
  function makeClip(name) {
    const v = document.createElement("video");
    v.className = "stage__video";
    v.loop = IDLE.includes(name);
    v.muted = true;
    v.defaultMuted = true;
    v.playsInline = true;
    v.preload = "auto";
    v.setAttribute("muted", "");
    v.setAttribute("playsinline", "");
    v.setAttribute("disablepictureinpicture", "");
    stage.appendChild(v);
    clips[name] = { name, video: v, ready: false };
    return clips[name];
  }

  async function loadClip(c) {
    const url = VIDEO_DIR + c.name + EXT;
    try {
      if (location.protocol === "file:") throw new Error("file");
      const res = await fetch(url);
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      c.video.src = URL.createObjectURL(blob);
    } catch (e) {
      c.video.src = url;
    }
    await new Promise((resolve) => {
      const done = () => resolve();
      c.video.addEventListener("canplaythrough", done, { once: true });
      c.video.addEventListener("loadeddata", () => setTimeout(done, 400), { once: true });
      c.video.addEventListener("error", done, { once: true });
      c.video.load();
    });
    c.ready = !c.video.error && c.video.readyState >= 2;
  }

  async function loadAll() {
    // what the visitor needs first: this section's loop, then the moves out of it
    const order = [IDLE[state], FWD[state], REV[(state + N - 1) % N], ...IDLE, ...FWD, ...REV];
    const names = order.filter((n, i) => order.indexOf(n) === i);
    names.forEach(makeClip);
    for (const name of names) {
      await loadClip(clips[name]);
      // bring the resting section to life as soon as its loop is ready
      if (name === IDLE[state] && !busy && !visibleIdle) startIdle(state, 600);
    }
  }

  function hideOthers(keep) {
    Object.values(clips).forEach((o) => {
      if (o.video === keep) return;
      o.video.classList.remove("is-visible");
      if (o.video.loop) o.video.pause();
    });
    stills.forEach((s) => {
      if (s !== keep) s.classList.remove("is-visible");
    });
  }

  function reveal(v, fadeMs) {
    v.style.zIndex = String(++topZ);
    v.style.transition = fadeMs ? `opacity ${fadeMs}ms ease-out` : "none";
    v.classList.add("is-visible");
    setTimeout(() => {
      if (v.classList.contains("is-visible")) hideOthers(v);
    }, fadeMs + 40);
  }

  function startIdle(i, fadeMs) {
    const c = clips[IDLE[i]];
    if (!c || !c.ready || reduceMotion.matches) return;
    const token = ++idleToken;
    const v = c.video;
    let shown = false;
    const show = () => {
      if (shown || token !== idleToken) return;
      shown = true;
      visibleIdle = c;
      reveal(v, fadeMs);
    };
    try {
      v.currentTime = 0;
    } catch (e) {
      /* not seekable yet */
    }
    if ("requestVideoFrameCallback" in v) v.requestVideoFrameCallback(show);
    else v.addEventListener("playing", show, { once: true });
    const p = v.play();
    if (p && p.catch) p.catch(() => {});
  }

  function playClip(c, fadeMs = 0) {
    return new Promise((resolve, reject) => {
      const v = c.video;
      let shown = false;
      let finished = false;
      const show = () => {
        if (shown) return;
        shown = true;
        reveal(v, fadeMs);
      };
      const finish = () => {
        if (finished) return;
        finished = true;
        clearTimeout(safety);
        show();
        resolve();
      };
      v.pause();
      try {
        v.currentTime = 0;
      } catch (e) {
        /* not seekable yet */
      }
      if ("requestVideoFrameCallback" in v) v.requestVideoFrameCallback(show);
      else v.addEventListener("playing", show, { once: true });
      v.addEventListener("ended", finish, { once: true });
      const safety = setTimeout(finish, (v.duration || 2) * 1000 + 2000);
      const p = v.play();
      if (p && p.catch) {
        p.catch((err) => {
          clearTimeout(safety);
          if (!finished) {
            finished = true;
            reject(err);
          }
        });
      }
    });
  }

  function crossfadeTo(index, ms = 900) {
    const vis = stills.find((s) => s.classList.contains("is-visible")) || stills[0];
    const next = vis === stills[0] ? stills[1] : stills[0];
    return new Promise((resolve) => {
      const run = () => {
        next.style.zIndex = String(++topZ);
        requestAnimationFrame(() => {
          next.classList.add("is-visible");
          setTimeout(() => {
            hideOthers(next);
            resolve();
          }, ms);
        });
      };
      next.classList.remove("is-visible");
      next.onload = null;
      if (next.getAttribute("src") === STILLS[index] && next.complete) run();
      else {
        next.onload = run;
        next.onerror = run;
        next.src = STILLS[index];
      }
    });
  }

  /* ------------------------------------------------------------ navigation */
  async function go(dir) {
    if (busy || menuOpen || modalOpen) return;
    busy = true;
    const from = state;
    const to = (state + dir + N) % N;
    const name = dir > 0 ? FWD[from] : REV[to];
    const c = clips[name];
    const useVideo = !!(c && c.ready && !reduceMotion.matches);
    const dur = useVideo && isFinite(c.video.duration) ? c.video.duration * 1000 : 900;

    leave(panels[from]);
    setActive(to);
    const enterTimer = setTimeout(() => enter(panels[to]), Math.max(350, dur - 450));
    // the idle loop has drifted off the section pose, so blend into the move
    const fade = visibleIdle ? MOVE_FADE : 0;
    idleToken++;
    visibleIdle = null;

    try {
      if (useVideo) await playClip(c, fade);
      else await crossfadeTo(to);
    } catch (e) {
      await crossfadeTo(to);
    }
    state = to;
    startIdle(to, IDLE_FADE);
    // make sure the copy is in even if the clip ended early
    clearTimeout(enterTimer);
    if (!panels[to].classList.contains("is-in")) enter(panels[to]);
    setTimeout(() => {
      busy = false;
      unlockedAt = performance.now();
    }, 200);
  }

  function goTo(index) {
    if (index === state) return;
    go((index - state + N) % N === 1 ? 1 : -1);
  }

  // wheel / trackpad: one gesture = one section. A gesture is "consumed" once
  // it has moved the page; its trailing inertia is ignored until the stream
  // pauses or a fresh swipe shows up as a jump in delta.
  let wheelAcc = 0;
  let lastWheel = 0;
  let lastDelta = 0;
  let consumed = false;
  window.addEventListener(
    "wheel",
    (e) => {
      if (modalOpen) return;
      e.preventDefault();
      if (menuOpen) return;
      const now = performance.now();
      const d = e.deltaY || e.deltaX;
      const gap = now - lastWheel;
      if (gap > 160) {
        consumed = false;
        wheelAcc = 0;
      } else if (Math.abs(d) > Math.abs(lastDelta) * 1.8 && Math.abs(d) > 14 && now - unlockedAt > 250) {
        consumed = false;
      }
      lastWheel = now;
      lastDelta = d;
      if (busy || consumed) return;
      wheelAcc += d;
      if (Math.abs(wheelAcc) > 30) {
        consumed = true;
        const dir = Math.sign(wheelAcc);
        wheelAcc = 0;
        go(dir);
      }
    },
    { passive: false }
  );

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (modalOpen) closeModal();
      else if (menuOpen) toggleMenu(false);
      return;
    }
    if (menuOpen || modalOpen) return;
    if (["ArrowDown", "PageDown", " ", "ArrowRight"].includes(e.key)) {
      e.preventDefault();
      go(1);
    } else if (["ArrowUp", "PageUp", "ArrowLeft"].includes(e.key)) {
      e.preventDefault();
      go(-1);
    } else if (e.key === "Home") {
      goTo(0);
    }
  });

  let touchY = null;
  let touchX = null;
  window.addEventListener(
    "touchstart",
    (e) => {
      touchY = e.touches[0].clientY;
      touchX = e.touches[0].clientX;
    },
    { passive: true }
  );
  window.addEventListener(
    "touchend",
    (e) => {
      if (touchY === null) return;
      const dy = e.changedTouches[0].clientY - touchY;
      const dx = e.changedTouches[0].clientX - touchX;
      touchY = null;
      if (Math.abs(dy) > 45 && Math.abs(dy) > Math.abs(dx)) go(dy < 0 ? 1 : -1);
    },
    { passive: true }
  );

  document.querySelectorAll("[data-goto]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const i = Number(el.dataset.goto);
      if (menuOpen) {
        toggleMenu(false);
        setTimeout(() => goTo(i), 450);
      } else goTo(i);
    });
  });

  /* ------------------------------------------------------------------ menu */
  function toggleMenu(open = !menuOpen) {
    if (open && busy) return;
    menuOpen = open;
    root.classList.toggle("menu-open", open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menu.setAttribute("aria-hidden", String(!open));
  }
  menuToggle.addEventListener("click", () => toggleMenu());

  /* ----------------------------------------------------------------- modal */
  function openModal() {
    if (busy) return;
    modalOpen = true;
    if (visibleIdle) visibleIdle.video.pause();
    if (!modalVideo.getAttribute("src")) modalVideo.src = VIDEO_DIR + "film" + EXT;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    modalVideo.currentTime = 0;
    const p = modalVideo.play();
    if (p && p.catch) p.catch(() => {});
  }
  function closeModal() {
    modalOpen = false;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    setTimeout(() => modalVideo.pause(), 500);
    resumeIdle();
  }

  function resumeIdle() {
    if (!visibleIdle || document.hidden || modalOpen) return;
    const p = visibleIdle.video.play();
    if (p && p.catch) p.catch(() => {});
  }
  // save battery: stop the idle loop while the tab is in the background
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (visibleIdle) visibleIdle.video.pause();
    } else resumeIdle();
  });
  document.querySelectorAll("[data-watch]").forEach((b) => b.addEventListener("click", openModal));
  modal.querySelector(".modal__close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  /* -------------------------------------------------------------- parallax */
  if (window.matchMedia("(pointer: fine)").matches) {
    let raf = 0;
    let mx = 0;
    let my = 0;
    window.addEventListener("pointermove", (e) => {
      mx = (e.clientX / innerWidth) * 2 - 1;
      my = (e.clientY / innerHeight) * 2 - 1;
      if (!raf) {
        raf = requestAnimationFrame(() => {
          raf = 0;
          root.style.setProperty("--mx", mx.toFixed(3));
          root.style.setProperty("--my", my.toFixed(3));
        });
      }
    });
  }

  /* ------------------------------------------------------------------ boot */
  const fromHash = panels.findIndex((p) => "#" + p.id === location.hash);
  if (fromHash > 0) {
    state = fromHash;
    stills[0].src = STILLS[state];
  }
  setActive(state);

  const start = () => {
    setTimeout(() => enter(panels[state]), 250);
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 600));
    idle(() => loadAll());
  };
  const fontsReady = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  const firstStill = stills[0].complete ? Promise.resolve() : new Promise((r) => (stills[0].onload = stills[0].onerror = r));
  Promise.all([fontsReady, firstStill]).then(start);
})();
