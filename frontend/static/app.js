(() => {
  const $ = (s) => document.querySelector(s);
  const API_BASE = (window.APP && window.APP.apiBase) || "";
  const urlEl = $("#url");
  const logEl = $("#log");
  const progBar = $("#progress-bar");
  const progLbl = $("#progress-label");
  const btnDl = $("#btn-dl");
  const btnStop = $("#btn-stop");
  const modal = $("#modal");
  const modalTitle = $("#modal-title");
  const modalBody = $("#modal-body");
  const modalSearch = $("#modal-search");
  const modalYes = $("#modal-yes");
  const modalNo = $("#modal-no");
  const modalClose = $("#modal-close");

  let fmt = "mp3";
  let running = false;
  let jobId = null;
  let pollTimer = null;
  let modalResolve = null;
  let seenLogCount = 0;

  function log(msg) {
    logEl.textContent += msg + "\n";
    logEl.scrollTop = logEl.scrollHeight;
  }

  function setProg(v) {
    const pct = Math.max(0, Math.min(100, v));
    progBar.style.width = pct + "%";
    progLbl.textContent = pct > 0 ? pct.toFixed(0) + "%" : "idle";
  }

  function getQuality() {
    if (fmt === "mp3") {
      const r = document.querySelector('input[name="qmp3"]:checked');
      return r ? r.value : "320";
    }
    const r = document.querySelector('input[name="qmp4"]:checked');
    return r ? r.value : "1080";
  }

  function setFmt(next) {
    fmt = next;
    document.querySelectorAll(".seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.fmt === fmt);
    });
    $("#quality-mp3").classList.toggle("hidden", fmt !== "mp3");
    $("#quality-mp4").classList.toggle("hidden", fmt !== "mp4");
  }

  function showModal(title, body, { yesNo = true, searchHtml = null } = {}) {
    return new Promise((resolve) => {
      modalResolve = resolve;
      modalTitle.textContent = title;
      modalBody.textContent = body;
      modalSearch.innerHTML = searchHtml || "";
      modalSearch.classList.toggle("hidden", !searchHtml);
      modalYes.classList.toggle("hidden", !yesNo);
      modalNo.classList.toggle("hidden", !yesNo);
      modalClose.classList.toggle("hidden", yesNo);
      modal.classList.remove("hidden");
    });
  }

  function closeModal(result) {
    modal.classList.add("hidden");
    if (modalResolve) {
      modalResolve(result);
      modalResolve = null;
    }
  }

  modalYes.addEventListener("click", () => closeModal(true));
  modalNo.addEventListener("click", () => closeModal(false));
  modalClose.addEventListener("click", () => closeModal(null));

  async function api(path, opts = {}) {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  function triggerBrowserDownload(id) {
    const a = document.createElement("a");
    a.href = API_BASE + `/api/download/${id}/file`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function refreshStatus() {
    try {
      const s = await api("/api/status");
      const parts = [];
      if (s.ytdlp_ok) parts.push(`yt-dlp ${s.ytdlp_ver} ✓`);
      else parts.push("yt-dlp ✗");
      if (s.ffmpeg_ok) parts.push("ffmpeg ✓");
      else parts.push("ffmpeg ✗");
      parts.push(`Python ${s.python}`);
      $("#sys-status").textContent = parts.join("  ·  ");
      btnDl.disabled = !s.ytdlp_ok || running;
    } catch {
      $("#sys-status").textContent = API_BASE
        ? "API unreachable — set API_BASE_URL / start backend"
        : "status unavailable";
      if (API_BASE) btnDl.disabled = true;
    }
  }

  async function pollJob() {
    if (!jobId) return;
    try {
      const st = await api(`/api/download/${jobId}`);
      const logs = st.logs || [];
      for (let i = seenLogCount; i < logs.length; i++) {
        if (logs[i]) log(logs[i]);
      }
      seenLogCount = logs.length;
      setProg(st.progress);
      if (st.status === "running") return;
      clearInterval(pollTimer);
      pollTimer = null;
      const finishedId = jobId;
      running = false;
      jobId = null;
      btnStop.disabled = true;
      btnDl.disabled = false;
      if (st.status === "done") {
        log("── saving to your Downloads folder…");
        triggerBrowserDownload(finishedId);
        setProg(100);
      } else {
        setProg(0);
      }
    } catch (e) {
      log("✗ " + e.message);
      running = false;
      btnStop.disabled = true;
      btnDl.disabled = false;
      clearInterval(pollTimer);
    }
  }

  async function startDownload() {
    const url = urlEl.value.trim();
    if (!url) return;

    running = true;
    btnDl.disabled = true;
    btnStop.disabled = false;
    setProg(0);
    seenLogCount = 0;
    log("─".repeat(62));
    log(`── URL:     ${url}`);
    log("── probing formats / size…");

    try {
      const probe = await api("/api/probe", {
        method: "POST",
        body: JSON.stringify({ url, fmt, quality: getQuality() }),
      });
      let quality = getQuality();
      if (probe.downgrade_msg) {
        const ok = await showModal(
          "Quality not available",
          probe.downgrade_msg + "\n\nDownload at the highest available quality?"
        );
        if (!ok) throw new Error("cancelled");
        quality = probe.quality;
        log(`── quality adjusted → ${quality}`);
      }

      const est = await api("/api/estimate", {
        method: "POST",
        body: JSON.stringify({ url, fmt, quality }),
      });
      const ok = await showModal(
        "Confirm download",
        `Estimated download size: ${est.size_label}\nQuality: ${est.quality_label}\n\nDo you want to download this file?`
      );
      if (!ok) throw new Error("cancelled");

      const fmtLabel = fmt === "mp3" ? "M4A" : "MP4";
      log(`── format:  ${fmtLabel}  quality=${quality}`);
      log(`── size:    ${est.size_label}`);
      log("── save:    browser Downloads");

      const job = await api("/api/download", {
        method: "POST",
        body: JSON.stringify({ url, fmt, quality }),
      });
      jobId = job.job_id;
      pollTimer = setInterval(pollJob, 800);
    } catch (e) {
      if (e.message === "cancelled") log("⚠ cancelled by user");
      else log("✗ " + e.message);
      running = false;
      btnDl.disabled = false;
      btnStop.disabled = true;
      setProg(0);
    }
  }

  async function openSearch() {
    const q = urlEl.value.trim();
    if (!q) return;
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ query: q }),
      });
      const html = data.results
        .map(
          (r) => `
        <div class="search-item" data-url="${r.url}">
          <img src="${r.thumbnail}" alt="">
          <div>
            <div class="search-item-title">${escapeHtml(r.title)}</div>
            <div class="search-item-sub">${escapeHtml(r.uploader || "")} ${r.duration_label || ""}</div>
          </div>
        </div>`
        )
        .join("");
      await showModal("Search YouTube", `Results for: ${q}`, {
        yesNo: false,
        searchHtml: html,
      });
    } catch (e) {
      await showModal("Search failed", e.message, { yesNo: false });
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  modalSearch.addEventListener("click", (e) => {
    const item = e.target.closest(".search-item");
    if (!item) return;
    urlEl.value = item.dataset.url;
    log(`── selected: ${item.querySelector(".search-item-title").textContent}`);
    closeModal(null);
  });

  document.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => setFmt(b.dataset.fmt));
  });

  $("#btn-search").addEventListener("click", openSearch);
  btnDl.addEventListener("click", startDownload);
  btnStop.addEventListener("click", async () => {
    if (jobId) {
      await api(`/api/download/${jobId}/stop`, { method: "POST" });
      log("⚠ stop requested...");
    }
  });
  $("#btn-clear").addEventListener("click", () => {
    logEl.textContent = "";
  });
  $("#btn-about").addEventListener("click", () => {
    showModal(
      "About",
      `X2mate v${window.APP.version}\n\nWeb UI — Vercel frontend + separate yt-dlp backend.\n\n• M4A audio / MP4 video\n• Size confirmation before download\n• Files save to your browser Downloads folder\n\nGitHub: ${window.APP.github}`,
      { yesNo: false }
    );
  });

  log("✓ ready — paste a YouTube link…");
  if (API_BASE) {
    log(`── API: ${API_BASE}`);
  } else if (/vercel\.app$/i.test(location.hostname) || location.hostname !== "127.0.0.1") {
    log("⚠ No backend URL set. Host backend/ and set window.__API_BASE__ in config.js");
    $("#sys-status").textContent = "backend not configured";
    btnDl.disabled = true;
  }
  refreshStatus();
  setInterval(refreshStatus, 30000);
})();
