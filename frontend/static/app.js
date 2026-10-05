(() => {
  const $ = (s) => document.querySelector(s);
  const API_BASE = ((window.APP && window.APP.apiBase) || "").replace(/\/$/, "");
  const urlEl = $("#url");
  const logEl = $("#log");
  const progBar = $("#progress-bar");
  const progLbl = $("#progress-label");
  const btnDl = $("#btn-dl");
  const btnStop = $("#btn-stop");
  const modal = $("#modal");
  const modalTitle = $("#modal-title");
  const modalBody = $("#modal-body");
  const modalYes = $("#modal-yes");
  const modalNo = $("#modal-no");
  const modalClose = $("#modal-close");
  const searchModal = $("#search-modal");
  const searchQuery = $("#search-query");
  const searchStatus = $("#search-status");
  const searchResults = $("#search-results");
  const btnSearchRun = $("#btn-search-run");

  let fmt = "mp3";
  let running = false;
  let jobId = null;
  let pollTimer = null;
  let modalResolve = null;
  let seenLogCount = 0;
  let searchBusy = false;
  let statusRetries = 0;

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

  function showModal(title, body, { yesNo = true } = {}) {
    return new Promise((resolve) => {
      modalResolve = resolve;
      modalTitle.textContent = title;
      modalBody.textContent = body;
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
    if (!API_BASE && location.hostname !== "127.0.0.1" && location.hostname !== "localhost") {
      throw new Error("Backend not configured");
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const res = await fetch(API_BASE + path, {
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        ...opts,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    } catch (e) {
      if (e.name === "AbortError") throw new Error("Request timed out (backend may be waking up)");
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  function triggerBrowserDownload(id) {
    const a = document.createElement("a");
    a.href = API_BASE + `/api/download/${id}/file`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function setSearchStatus(text, kind = "") {
    searchStatus.textContent = text;
    searchStatus.className = "search-status" + (kind ? " " + kind : "");
  }

  async function refreshStatus() {
    if (!API_BASE) {
      $("#sys-status").textContent = "backend not configured";
      btnDl.disabled = true;
      return;
    }
    try {
      if (statusRetries > 0) {
        $("#sys-status").textContent = "Connecting to backend…";
      }
      const s = await api("/api/status");
      statusRetries = 0;
      const parts = [];
      if (s.ytdlp_ok) parts.push(`yt-dlp ${s.ytdlp_ver} ✓`);
      else parts.push("yt-dlp ✗");
      if (s.ffmpeg_ok) parts.push("ffmpeg ✓");
      else parts.push("ffmpeg ✗");
      parts.push(`Python ${s.python}`);
      $("#sys-status").textContent = parts.join("  ·  ");
      btnDl.disabled = !s.ytdlp_ok || running;
    } catch {
      statusRetries += 1;
      $("#sys-status").textContent =
        statusRetries <= 3
          ? "Connecting to backend…"
          : "API unreachable — backend may be sleeping";
      btnDl.disabled = true;
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
    if (!API_BASE) {
      log("✗ Backend not configured");
      return;
    }

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

  function openSearch() {
    searchResults.innerHTML = "";
    setSearchStatus("Type a name and hit Search");
    searchQuery.value = "";
    searchModal.classList.remove("hidden");
    setTimeout(() => searchQuery.focus(), 50);
  }

  function closeSearch() {
    searchModal.classList.add("hidden");
  }

  async function runSearch() {
    if (searchBusy) return;
    const q = searchQuery.value.trim();
    if (!q) {
      setSearchStatus("Enter a video name", "warn");
      return;
    }
    if (!API_BASE) {
      setSearchStatus("Backend not configured — set API URL first", "err");
      return;
    }

    searchBusy = true;
    btnSearchRun.disabled = true;
    searchResults.innerHTML = "";
    setSearchStatus("Searching…", "info");

    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ query: q }),
      });
      const results = data.results || [];
      if (!results.length) {
        setSearchStatus("No results", "warn");
        return;
      }
      setSearchStatus(`${results.length} result(s) — click one to select`);
      searchResults.innerHTML = results
        .map(
          (r) => `
        <div class="search-item" data-url="${escapeAttr(r.url)}" data-title="${escapeAttr(r.title)}">
          <img src="${escapeAttr(r.thumbnail || "")}" alt="" loading="lazy">
          <div>
            <div class="search-item-title">${escapeHtml(r.title)}</div>
            <div class="search-item-sub">${escapeHtml(r.uploader || "")}${r.duration_label ? " · " + escapeHtml(r.duration_label) : ""}</div>
          </div>
        </div>`
        )
        .join("");
    } catch (e) {
      setSearchStatus("Search failed: " + e.message, "err");
    } finally {
      searchBusy = false;
      btnSearchRun.disabled = false;
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function escapeAttr(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  searchResults.addEventListener("click", (e) => {
    const item = e.target.closest(".search-item");
    if (!item) return;
    urlEl.value = item.dataset.url;
    log(`── selected: ${item.dataset.title}`);
    closeSearch();
  });

  document.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => setFmt(b.dataset.fmt));
  });

  $("#btn-search").addEventListener("click", openSearch);
  btnSearchRun.addEventListener("click", runSearch);
  searchQuery.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runSearch();
    }
  });
  $("#search-modal-close").addEventListener("click", closeSearch);

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
    $("#sys-status").textContent = "Connecting to backend…";
  } else if (/vercel\.app$/i.test(location.hostname) || (location.hostname !== "127.0.0.1" && location.hostname !== "localhost")) {
    log("⚠ No backend URL set. Host backend/ and set window.__API_BASE__ in config.js");
    $("#sys-status").textContent = "backend not configured";
    btnDl.disabled = true;
  }
  refreshStatus();
  setInterval(refreshStatus, 15000);
})();
