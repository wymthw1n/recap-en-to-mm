// Recap English -> Myanmar Web Client
document.addEventListener("DOMContentLoaded", () => {
  // State
  const state = {
    selectedSource: null,
    sources: [],
    jobs: [],
    activeJobId: null,
    activeWs: null,
    previewTime: 1.0,
    previewDuration: 0.0,
    activeOverlayTarget: "title", // "title" | "subtitle" | "logo" | "extra" | "blur"
    activeBlurIndex: 0,
    tapToPlaceEnabled: false,
    enable_original_background: false,
    original_background_volume: 25,
    overlays: {
      title_text: "",
      title_pos: [0.50, 0.12],
      title_size: 54,
      extra_text: "",
      extra_text_pos: [0.50, 0.84],
      extra_size: 42,
      logo_enabled: false,
      logo_path: "",
      logo_pos: [0.80, 0.06],
      logo_width_frac: 0.16,
      burn_subtitles: true,
      subtitle_pos: [0.50, 0.86],
      subtitle_size: 3.6,
      subtitle_size_pct: 3.6,
      subtitle_width_pct: 85,
      subtitle_color: "#FFDE00",
      subtitle_style: "outline",
      blur_boxes: [],
    },
  };

  // DOM Elements
  const tabBtns = document.querySelectorAll(".nav-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  // Tab Switching
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const pane = document.getElementById(`tab-${target}`);
      if (pane) pane.classList.add("active");

      if (target === "sources") loadSources();
      if (target === "jobs") loadJobs();
      if (target === "settings") loadSettings();
    });
  });

  // ---------------- Sources & Uploads ----------------
  const videoFileInput = document.getElementById("videoFileInput");
  const videoDropZone = document.getElementById("videoDropZone");
  const downloadUrlInput = document.getElementById("downloadUrlInput");
  const downloadBtn = document.getElementById("downloadBtn");
  const downloadProgress = document.getElementById("downloadProgress");
  const downloadStatusText = document.getElementById("downloadStatusText");
  const selectedSourceBanner = document.getElementById("selectedSourceBanner");
  const selectedThumb = document.getElementById("selectedThumb");
  const selectedTitle = document.getElementById("selectedTitle");
  const selectedDuration = document.getElementById("selectedDuration");
  const selectedRes = document.getElementById("selectedRes");
  const sourcesGrid = document.getElementById("sourcesGrid");

  async function loadSources() {
    try {
      const res = await fetch("/api/sources");
      state.sources = await res.json();
      document.getElementById("sourceCountBadge").innerText = state.sources.length;
      renderSourcesGrid();
    } catch (err) {
      console.error("Error loading sources:", err);
    }
  }

  function renderSourcesGrid() {
    if (!sourcesGrid) return;
    if (state.sources.length === 0) {
      sourcesGrid.innerHTML = `<div class="card p-4 muted text-center" style="grid-column: 1/-1;">No source videos in library yet. Download via link or upload one!</div>`;
      return;
    }
    sourcesGrid.innerHTML = state.sources.map(src => `
      <div class="source-card">
        <div class="source-thumb-wrap">
          <img src="${src.thumbnail_path ? '/' + src.thumbnail_path : ''}" alt="${src.name}">
          <span class="source-duration-tag">${formatSeconds(src.duration)}</span>
        </div>
        <div class="source-info">
          <h4>${escapeHtml(src.name)}</h4>
          <div class="muted small">${src.width}x${src.height} · ${(src.file_size / (1024*1024)).toFixed(1)} MB</div>
          <div class="source-actions">
            <button class="btn btn-sm btn-primary select-src-btn" data-id="${src.id}">Use in Workspace</button>
            <button class="btn btn-sm btn-danger del-src-btn" data-id="${src.id}">Delete</button>
          </div>
        </div>
      </div>
    `).join("");

    sourcesGrid.querySelectorAll(".select-src-btn").forEach(b => {
      b.addEventListener("click", () => {
        const found = state.sources.find(s => s.id === b.dataset.id);
        if (found) selectSource(found);
      });
    });

    sourcesGrid.querySelectorAll(".del-src-btn").forEach(b => {
      b.addEventListener("click", async () => {
        if (!confirm("Delete this source video?")) return;
        await fetch(`/api/sources/${b.dataset.id}`, { method: "DELETE" });
        loadSources();
      });
    });
  }

  function selectSource(src) {
    state.selectedSource = src;
    state.previewDuration = src.duration || 0.0;
    selectedSourceBanner.classList.remove("hidden");
    selectedThumb.src = src.thumbnail_path ? `/${src.thumbnail_path}` : "";
    selectedTitle.innerText = src.name;
    selectedDuration.innerText = formatSeconds(src.duration);
    selectedRes.innerText = `${src.width}x${src.height}`;

    // Switch to workspace tab
    document.querySelector('.nav-btn[data-tab="workspace"]').click();

    // Set preview seek slider max
    const slider = document.getElementById("previewSeekSlider");
    slider.max = Math.max(1, Math.floor(src.duration));
    slider.value = Math.min(1.0, src.duration);
    state.previewTime = parseFloat(slider.value);

    refreshPreviewFrame();
  }

  // Upload handler
  videoFileInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);

    const oldText = videoDropZone.querySelector(".drop-text").innerHTML;
    videoDropZone.querySelector(".drop-text").innerHTML = "Uploading & analyzing...";
    try {
      const res = await fetch("/api/upload/video", { method: "POST", body: formData });
      const record = await res.json();
      loadSources();
      selectSource(record);
    } catch (err) {
      alert("Upload error: " + err.message);
    } finally {
      videoDropZone.querySelector(".drop-text").innerHTML = oldText;
      videoFileInput.value = "";
    }
  });

  // Download handler
  downloadBtn.addEventListener("click", async () => {
    const url = downloadUrlInput.value.trim();
    if (!url) return;
    downloadBtn.disabled = true;
    downloadProgress.classList.remove("hidden");
    downloadStatusText.innerText = "Downloading with yt-dlp... please wait";

    try {
      const res = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Download failed");
      }
      const record = await res.json();
      downloadUrlInput.value = "";
      loadSources();
      selectSource(record);
    } catch (err) {
      alert("Download failed: " + err.message);
    } finally {
      downloadBtn.disabled = false;
      downloadProgress.classList.add("hidden");
    }
  });

  // ---------------- Visual Preview & Framing ----------------
  const previewImage = document.getElementById("previewImage");
  const previewContainer = document.getElementById("previewContainer");
  const overlayCanvas = document.getElementById("overlayCanvas");
  const previewTimeLabel = document.getElementById("previewTimeLabel");
  const previewSeekSlider = document.getElementById("previewSeekSlider");
  const refreshFrameBtn = document.getElementById("refreshFrameBtn");
  const seekBackBtn = document.getElementById("seekBackBtn");
  const seekFwdBtn = document.getElementById("seekFwdBtn");

  const ratioSelect = document.getElementById("ratioSelect");
  const fillSelect = document.getElementById("fillSelect");
  const zoomSlider = document.getElementById("zoomSlider");
  const zoomVal = document.getElementById("zoomVal");
  const flipCheck = document.getElementById("flipCheck");

  zoomSlider.addEventListener("input", () => {
    zoomVal.innerText = `${parseFloat(zoomSlider.value).toFixed(2)}x`;
  });
  zoomSlider.addEventListener("change", refreshPreviewFrame);
  ratioSelect.addEventListener("change", () => {
    updatePreviewAspectRatio();
    refreshPreviewFrame();
  });
  fillSelect.addEventListener("change", refreshPreviewFrame);
  flipCheck.addEventListener("change", refreshPreviewFrame);

  previewSeekSlider.addEventListener("input", () => {
    state.previewTime = parseFloat(previewSeekSlider.value);
    updatePreviewTimeLabel();
  });
  previewSeekSlider.addEventListener("change", refreshPreviewFrame);

  seekBackBtn.addEventListener("click", () => {
    state.previewTime = Math.max(0, state.previewTime - 5);
    previewSeekSlider.value = state.previewTime;
    updatePreviewTimeLabel();
    refreshPreviewFrame();
  });
  seekFwdBtn.addEventListener("click", () => {
    state.previewTime = Math.min(state.previewDuration || 9999, state.previewTime + 5);
    previewSeekSlider.value = state.previewTime;
    updatePreviewTimeLabel();
    refreshPreviewFrame();
  });
  refreshFrameBtn.addEventListener("click", refreshPreviewFrame);

  function updatePreviewTimeLabel() {
    previewTimeLabel.innerText = `${formatSeconds(state.previewTime)} / ${formatSeconds(state.previewDuration)}`;
  }

  function updatePreviewAspectRatio() {
    if (!previewContainer) return;
    const ratio = ratioSelect.value;
    if (ratio === "9:16") {
      previewContainer.style.aspectRatio = "9 / 16";
      previewContainer.style.maxWidth = "310px";
      previewContainer.style.maxHeight = "540px";
    } else if (ratio === "1:1") {
      previewContainer.style.aspectRatio = "1 / 1";
      previewContainer.style.maxWidth = "460px";
      previewContainer.style.maxHeight = "460px";
    } else if (ratio === "Original" && state.selectedSource && state.selectedSource.width && state.selectedSource.height) {
      const sw = state.selectedSource.width;
      const sh = state.selectedSource.height;
      previewContainer.style.aspectRatio = `${sw} / ${sh}`;
      previewContainer.style.maxWidth = sw >= sh ? "640px" : "320px";
      previewContainer.style.maxHeight = sw >= sh ? "360px" : "540px";
    } else {
      // 16:9
      previewContainer.style.aspectRatio = "16 / 9";
      previewContainer.style.maxWidth = "640px";
      previewContainer.style.maxHeight = "360px";
    }
  }

  async function refreshPreviewFrame() {
    if (!state.selectedSource) return;
    updatePreviewTimeLabel();
    updatePreviewAspectRatio();
    const params = new URLSearchParams({
      source_id: state.selectedSource.id,
      time: state.previewTime.toFixed(2),
      zoom: zoomSlider.value,
      mirror: flipCheck.checked ? "true" : "false",
      ratio: ratioSelect.value,
      fill: fillSelect.value,
    });

    previewImage.src = `/api/preview/frame?${params.toString()}`;
    updateOverlayPositions();
  }

  // ---------------- Overlays & Positioning ----------------
  const overlayTitle = document.getElementById("overlayTitle");
  const overlayTitleText = document.getElementById("overlayTitleText");
  const overlayExtra = document.getElementById("overlayExtra");
  const overlayExtraText = document.getElementById("overlayExtraText");
  const overlayLogo = document.getElementById("overlayLogo");
  const overlayLogoImg = document.getElementById("overlayLogoImg");
  const overlaySubtitle = document.getElementById("overlaySubtitle");
  const overlaySubtitleText = document.getElementById("overlaySubtitleText");

  const titleTextInput = document.getElementById("titleTextInput");
  const extraTextInput = document.getElementById("extraTextInput");
  const logoFileInput = document.getElementById("logoFileInput");
  const logoEnabledCheck = document.getElementById("logoEnabledCheck");
  const logoSizeSlider = document.getElementById("logoSizeSlider");
  const logoSizeVal = document.getElementById("logoSizeVal");
  const addBlurBtn = document.getElementById("addBlurBtn");
  const blurBoxesList = document.getElementById("blurBoxesList");

  // Subtitle Controls
  const burnSubtitlesCheck = document.getElementById("burnSubtitlesCheck");
  const subSizeSlider = document.getElementById("subSizeSlider");
  const subSizeVal = document.getElementById("subSizeVal");
  const subSizeMinusBtn = document.getElementById("subSizeMinusBtn");
  const subSizePlusBtn = document.getElementById("subSizePlusBtn");
  const subWidthSlider = document.getElementById("subWidthSlider");
  const subWidthVal = document.getElementById("subWidthVal");
  const subWidthMinusBtn = document.getElementById("subWidthMinusBtn");
  const subWidthPlusBtn = document.getElementById("subWidthPlusBtn");
  const subYSlider = document.getElementById("subYSlider");
  const subYVal = document.getElementById("subYVal");
  const subYMinusBtn = document.getElementById("subYMinusBtn");
  const subYPlusBtn = document.getElementById("subYPlusBtn");
  const subCenterHBtn = document.getElementById("subCenterHBtn");
  const subSizePresetBtns = document.querySelectorAll(".preset-pill-btn[data-subsize]");
  const subWidthPresetBtns = document.querySelectorAll(".preset-pill-btn[data-subwidth]");
  const subYPresetBtns = document.querySelectorAll(".pos-preset-btn[data-suby]");
  const subColorBtns = document.querySelectorAll(".sub-color-btn");
  const subColorPicker = document.getElementById("subColorPicker");
  const subStyleSelect = document.getElementById("subStyleSelect");

  // Original Background Sound Controls
  const enableOrigBgCheck = document.getElementById("enableOrigBgCheck");
  const origBgVolSlider = document.getElementById("origBgVolSlider");
  const origBgVolVal = document.getElementById("origBgVolVal");

  // Inputs binding
  titleTextInput.addEventListener("input", () => {
    state.overlays.title_text = titleTextInput.value;
    overlayTitleText.innerText = titleTextInput.value || "Title Preview";
    overlayTitle.classList.toggle("hidden", !titleTextInput.value);
    updateOverlayPositions();
  });

  extraTextInput.addEventListener("input", () => {
    state.overlays.extra_text = extraTextInput.value;
    overlayExtraText.innerText = extraTextInput.value || "Extra Text";
    overlayExtra.classList.toggle("hidden", !extraTextInput.value);
    updateOverlayPositions();
  });

  logoEnabledCheck.addEventListener("change", () => {
    state.overlays.logo_enabled = logoEnabledCheck.checked;
    overlayLogo.classList.toggle("hidden", !logoEnabledCheck.checked || !state.overlays.logo_path);
    updateOverlayPositions();
  });

  logoSizeSlider.addEventListener("input", () => {
    const val = parseInt(logoSizeSlider.value);
    state.overlays.logo_width_frac = val / 100.0;
    logoSizeVal.innerText = `${val}%`;
    if (state.activeOverlayTarget === "logo") {
      posSizeSlider.value = val;
      posSizeVal.innerText = `${val}%`;
    }
    updateOverlayPositions();
  });

  logoFileInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/upload/logo", { method: "POST", body: formData });
      const data = await res.json();
      state.overlays.logo_path = data.path;
      overlayLogoImg.src = `/${data.rel_path}`;
      logoEnabledCheck.checked = true;
      state.overlays.logo_enabled = true;
      overlayLogo.classList.remove("hidden");
      updateOverlayPositions();
    } catch (err) {
      alert("Logo upload failed: " + err.message);
    }
  });

  // Subtitle Helpers & Input Bindings
  function setSubtitleSize(val) {
    const clamped = Math.max(2.0, Math.min(6.5, Math.round(val * 10) / 10));
    state.overlays.subtitle_size_pct = clamped;
    state.overlays.subtitle_size = clamped;
    if (subSizeSlider) subSizeSlider.value = clamped;
    if (subSizeVal) subSizeVal.innerText = `${clamped.toFixed(1)}%`;
    if (state.activeOverlayTarget === "subtitle") {
      posSizeSlider.value = clamped;
      posSizeVal.innerText = `${clamped.toFixed(1)}%`;
    }
    if (subSizePresetBtns) {
      subSizePresetBtns.forEach(b => {
        b.classList.toggle("active", Math.abs(parseFloat(b.dataset.subsize) - clamped) < 0.1);
      });
    }
    updateOverlayPositions();
  }

  function setSubtitleWidth(val) {
    const clamped = Math.max(50, Math.min(95, Math.round(val)));
    state.overlays.subtitle_width_pct = clamped;
    if (subWidthSlider) subWidthSlider.value = clamped;
    if (subWidthVal) subWidthVal.innerText = `${clamped}%`;
    if (subWidthPresetBtns) {
      subWidthPresetBtns.forEach(b => {
        b.classList.toggle("active", parseInt(b.dataset.subwidth) === clamped);
      });
    }
    updateOverlayPositions();
  }

  function setSubtitleY(val) {
    const clamped = Math.max(10, Math.min(95, Math.round(val)));
    state.overlays.subtitle_pos[1] = clamped / 100.0;
    if (subYSlider) subYSlider.value = clamped;
    if (subYVal) subYVal.innerText = `${clamped}%`;
    if (state.activeOverlayTarget === "subtitle") {
      posYSlider.value = clamped;
      posYVal.innerText = `${clamped}%`;
    }
    if (subYPresetBtns) {
      subYPresetBtns.forEach(b => {
        b.classList.toggle("active", parseInt(b.dataset.suby) === clamped);
      });
    }
    updateOverlayPositions();
  }

  if (burnSubtitlesCheck) {
    burnSubtitlesCheck.addEventListener("change", () => {
      state.overlays.burn_subtitles = burnSubtitlesCheck.checked;
      if (overlaySubtitle) {
        overlaySubtitle.classList.toggle("hidden", !burnSubtitlesCheck.checked);
      }
      updateOverlayPositions();
    });
  }

  // Size Controls
  if (subSizeSlider) {
    subSizeSlider.addEventListener("input", () => {
      setSubtitleSize(parseFloat(subSizeSlider.value));
    });
  }
  if (subSizeMinusBtn) {
    subSizeMinusBtn.addEventListener("click", () => {
      setSubtitleSize((state.overlays.subtitle_size_pct || 3.6) - 0.2);
    });
  }
  if (subSizePlusBtn) {
    subSizePlusBtn.addEventListener("click", () => {
      setSubtitleSize((state.overlays.subtitle_size_pct || 3.6) + 0.2);
    });
  }
  if (subSizePresetBtns) {
    subSizePresetBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        setSubtitleSize(parseFloat(btn.dataset.subsize));
      });
    });
  }

  // Width Controls
  if (subWidthSlider) {
    subWidthSlider.addEventListener("input", () => {
      setSubtitleWidth(parseInt(subWidthSlider.value));
    });
  }
  if (subWidthMinusBtn) {
    subWidthMinusBtn.addEventListener("click", () => {
      setSubtitleWidth((state.overlays.subtitle_width_pct || 85) - 5);
    });
  }
  if (subWidthPlusBtn) {
    subWidthPlusBtn.addEventListener("click", () => {
      setSubtitleWidth((state.overlays.subtitle_width_pct || 85) + 5);
    });
  }
  if (subWidthPresetBtns) {
    subWidthPresetBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        setSubtitleWidth(parseInt(btn.dataset.subwidth));
      });
    });
  }

  // Y Position Controls
  if (subYSlider) {
    subYSlider.addEventListener("input", () => {
      setSubtitleY(parseInt(subYSlider.value));
    });
  }
  if (subYMinusBtn) {
    subYMinusBtn.addEventListener("click", () => {
      setSubtitleY(Math.round(state.overlays.subtitle_pos[1] * 100) - 2);
    });
  }
  if (subYPlusBtn) {
    subYPlusBtn.addEventListener("click", () => {
      setSubtitleY(Math.round(state.overlays.subtitle_pos[1] * 100) + 2);
    });
  }
  if (subYPresetBtns) {
    subYPresetBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        setSubtitleY(parseInt(btn.dataset.suby));
      });
    });
  }
  if (subCenterHBtn) {
    subCenterHBtn.addEventListener("click", () => {
      state.overlays.subtitle_pos[0] = 0.50;
      if (state.activeOverlayTarget === "subtitle") {
        posXSlider.value = 50;
        posXVal.innerText = "50%";
      }
      updateOverlayPositions();
    });
  }

  // Color & Style Controls
  if (subColorBtns) {
    subColorBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        subColorBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.overlays.subtitle_color = btn.dataset.color;
        if (subColorPicker) subColorPicker.value = btn.dataset.color;
        updateOverlayPositions();
      });
    });
  }

  if (subColorPicker) {
    subColorPicker.addEventListener("input", () => {
      subColorBtns.forEach(b => b.classList.remove("active"));
      state.overlays.subtitle_color = subColorPicker.value;
      updateOverlayPositions();
    });
  }

  if (subStyleSelect) {
    subStyleSelect.addEventListener("change", () => {
      state.overlays.subtitle_style = subStyleSelect.value;
      updateOverlayPositions();
    });
  }

  // Original Background Sound Inputs binding
  if (enableOrigBgCheck) {
    enableOrigBgCheck.addEventListener("change", () => {
      state.enable_original_background = enableOrigBgCheck.checked;
    });
  }

  if (origBgVolSlider) {
    origBgVolSlider.addEventListener("input", () => {
      const val = parseInt(origBgVolSlider.value);
      state.original_background_volume = val;
      if (origBgVolVal) origBgVolVal.innerText = `${val}%`;
    });
  }

  // Blur Boxes List & Canvas Management
  function renderBlurBoxesList() {
    if (!blurBoxesList) return;
    if (state.overlays.blur_boxes.length === 0) {
      blurBoxesList.innerHTML = `<span class="muted small">No blur boxes added</span>`;
      return;
    }
    blurBoxesList.innerHTML = state.overlays.blur_boxes.map((box, i) => {
      const isSelected = state.activeOverlayTarget === "blur" && state.activeBlurIndex === i;
      return `
        <div class="blur-box-item ${isSelected ? 'active' : ''}" data-index="${i}">
          <div style="font-weight: 600; color: #38bdf8; min-width: 48px;">#${i + 1}</div>
          <div class="blur-box-item-inputs">
            <div>
              <label>X%</label>
              <input type="number" min="0" max="100" value="${Math.round(box.x * 100)}" data-field="x" data-index="${i}">
            </div>
            <div>
              <label>Y%</label>
              <input type="number" min="0" max="100" value="${Math.round(box.y * 100)}" data-field="y" data-index="${i}">
            </div>
            <div>
              <label>W%</label>
              <input type="number" min="5" max="100" value="${Math.round(box.w * 100)}" data-field="w" data-index="${i}">
            </div>
            <div>
              <label>H%</label>
              <input type="number" min="5" max="100" value="${Math.round(box.h * 100)}" data-field="h" data-index="${i}">
            </div>
          </div>
          <button type="button" class="btn btn-xs btn-danger del-blur-btn" data-index="${i}" title="Remove box">&times;</button>
        </div>
      `;
    }).join("");

    blurBoxesList.querySelectorAll(".blur-box-item").forEach(item => {
      item.addEventListener("click", (e) => {
        if (e.target.classList.contains("del-blur-btn") || e.target.tagName === "INPUT") return;
        state.activeBlurIndex = parseInt(item.dataset.index);
        state.activeOverlayTarget = "blur";
        segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "blur"));
        syncPositionControlsToTarget();
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
      });
    });

    blurBoxesList.querySelectorAll(".del-blur-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index);
        state.overlays.blur_boxes.splice(idx, 1);
        if (state.activeBlurIndex >= state.overlays.blur_boxes.length) {
          state.activeBlurIndex = Math.max(0, state.overlays.blur_boxes.length - 1);
        }
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
        syncPositionControlsToTarget();
      });
    });

    blurBoxesList.querySelectorAll("input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        const idx = parseInt(inp.dataset.index);
        const field = inp.dataset.field;
        const val = Math.max(0, Math.min(100, parseInt(inp.value) || 0)) / 100.0;
        if (state.overlays.blur_boxes[idx]) {
          state.overlays.blur_boxes[idx][field] = val;
          renderBlurBoxesOnCanvas();
          if (state.activeBlurIndex === idx && state.activeOverlayTarget === "blur") {
            syncPositionControlsToTarget();
          }
        }
      });
    });
  }

  function renderBlurBoxesOnCanvas() {
    if (!overlayCanvas) return;
    overlayCanvas.querySelectorAll(".blur-box-elem").forEach(el => el.remove());
    state.overlays.blur_boxes.forEach((box, i) => {
      const el = document.createElement("div");
      const isSelected = state.activeOverlayTarget === "blur" && state.activeBlurIndex === i;
      el.className = `blur-box-elem ${isSelected ? "active" : ""}`;
      el.style.left = `${box.x * 100}%`;
      el.style.top = `${box.y * 100}%`;
      el.style.width = `${box.w * 100}%`;
      el.style.height = `${box.h * 100}%`;
      el.innerHTML = `<span class="blur-box-label">Blur #${i + 1}</span>`;

      setupCanvasDraggable(
        el,
        () => [box.x, box.y],
        ([nx, ny]) => {
          box.x = Math.max(0, Math.min(1 - box.w, nx));
          box.y = Math.max(0, Math.min(1 - box.h, ny));
          el.style.left = `${box.x * 100}%`;
          el.style.top = `${box.y * 100}%`;
          renderBlurBoxesList();
        },
        () => {
          state.activeBlurIndex = i;
          state.activeOverlayTarget = "blur";
          segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "blur"));
          syncPositionControlsToTarget();
          renderBlurBoxesList();
          renderBlurBoxesOnCanvas();
        }
      );

      overlayCanvas.appendChild(el);
    });
  }

  if (addBlurBtn) {
    addBlurBtn.addEventListener("click", () => {
      state.overlays.blur_boxes.push({ x: 0.10, y: 0.10, w: 0.25, h: 0.12 });
      state.activeBlurIndex = state.overlays.blur_boxes.length - 1;
      state.activeOverlayTarget = "blur";
      segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "blur"));
      syncPositionControlsToTarget();
      renderBlurBoxesList();
      renderBlurBoxesOnCanvas();
    });
  }

  // Mobile / Touch Positioning Hub
  const segBtns = document.querySelectorAll(".seg-btn");
  const gridBtns = document.querySelectorAll(".grid-btn");
  const tapToPlaceCheck = document.getElementById("tapToPlaceCheck");
  const posXSlider = document.getElementById("posXSlider");
  const posYSlider = document.getElementById("posYSlider");
  const posSizeSlider = document.getElementById("posSizeSlider");
  const posXVal = document.getElementById("posXVal");
  const posYVal = document.getElementById("posYVal");
  const posSizeVal = document.getElementById("posSizeVal");
  const stepBtns = document.querySelectorAll(".step-btn");
  const sizeStepper = document.getElementById("sizeStepper");

  segBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      segBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeOverlayTarget = btn.dataset.target;
      if (state.activeOverlayTarget === "blur" && state.overlays.blur_boxes.length === 0) {
        state.overlays.blur_boxes.push({ x: 0.10, y: 0.10, w: 0.25, h: 0.12 });
        state.activeBlurIndex = 0;
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
      }
      syncPositionControlsToTarget();
      updateOverlayPositions();
      renderBlurBoxesOnCanvas();
    });
  });

  tapToPlaceCheck.addEventListener("change", () => {
    state.tapToPlaceEnabled = tapToPlaceCheck.checked;
  });

  // Tap-to-Place on preview container
  previewContainer.addEventListener("click", (e) => {
    if (!state.tapToPlaceEnabled) return;
    if (e.target.closest(".overlay-elem") || e.target.closest(".blur-box-elem")) return;
    const rect = previewContainer.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    setTargetPosition(x, y);
  });

  // 9-Grid Presets
  const PRESET_COORDS = {
    "top-left": [0.15, 0.10],
    "top-center": [0.50, 0.12],
    "top-right": [0.85, 0.10],
    "center-left": [0.15, 0.50],
    "center": [0.50, 0.50],
    "center-right": [0.85, 0.50],
    "bottom-left": [0.15, 0.88],
    "bottom-center": [0.50, 0.84],
    "bottom-right": [0.85, 0.88],
  };

  gridBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const align = btn.dataset.align;
      const coords = PRESET_COORDS[align] || [0.5, 0.5];
      setTargetPosition(coords[0], coords[1]);
    });
  });

  function setTargetPosition(x, y) {
    const t = state.activeOverlayTarget;
    if (t === "title") {
      state.overlays.title_pos = [x, y];
    } else if (t === "subtitle") {
      state.overlays.subtitle_pos = [x, y];
    } else if (t === "logo") {
      state.overlays.logo_pos = [x, y];
    } else if (t === "extra") {
      state.overlays.extra_text_pos = [x, y];
    } else if (t === "blur") {
      const box = state.overlays.blur_boxes[state.activeBlurIndex];
      if (box) {
        box.x = Math.max(0, Math.min(1 - box.w, x - box.w / 2));
        box.y = Math.max(0, Math.min(1 - box.h, y - box.h / 2));
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
      }
    }
    syncPositionControlsToTarget();
    updateOverlayPositions();
  }

  // Stepper buttons (+ and -)
  stepBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const adjust = btn.dataset.adjust;
      const delta = parseInt(btn.dataset.delta);
      if (adjust === "posX") {
        posXSlider.value = Math.max(0, Math.min(100, parseInt(posXSlider.value) + delta));
        posXSlider.dispatchEvent(new Event("input"));
      } else if (adjust === "posY") {
        posYSlider.value = Math.max(0, Math.min(100, parseInt(posYSlider.value) + delta));
        posYSlider.dispatchEvent(new Event("input"));
      } else if (adjust === "size") {
        const isSub = (state.activeOverlayTarget === "subtitle");
        const min = parseFloat(posSizeSlider.min) || (isSub ? 2.0 : 6);
        const max = parseFloat(posSizeSlider.max) || (isSub ? 6.5 : 96);
        const step = parseFloat(posSizeSlider.step) || (isSub ? 0.2 : 1);
        const current = parseFloat(posSizeSlider.value) || 0;
        const change = (delta > 0 ? step : -step);
        const next = Math.max(min, Math.min(max, +(current + change).toFixed(1)));
        posSizeSlider.value = next;
        posSizeSlider.dispatchEvent(new Event("input"));
      }
    });
  });

  posXSlider.addEventListener("input", () => {
    const x = parseInt(posXSlider.value) / 100.0;
    posXVal.innerText = `${posXSlider.value}%`;
    const t = state.activeOverlayTarget;
    if (t === "title") state.overlays.title_pos[0] = x;
    else if (t === "subtitle") state.overlays.subtitle_pos[0] = x;
    else if (t === "logo") state.overlays.logo_pos[0] = x;
    else if (t === "extra") state.overlays.extra_text_pos[0] = x;
    else if (t === "blur") {
      const box = state.overlays.blur_boxes[state.activeBlurIndex];
      if (box) {
        box.x = x;
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
      }
    }
    updateOverlayPositions();
  });

  posYSlider.addEventListener("input", () => {
    const y = parseInt(posYSlider.value) / 100.0;
    posYVal.innerText = `${posYSlider.value}%`;
    const t = state.activeOverlayTarget;
    if (t === "title") state.overlays.title_pos[1] = y;
    else if (t === "subtitle") {
      state.overlays.subtitle_pos[1] = y;
      if (subYSlider) subYSlider.value = Math.round(y * 100);
      if (subYVal) subYVal.innerText = `${Math.round(y * 100)}%`;
      if (subYPresetBtns) {
        subYPresetBtns.forEach(b => b.classList.toggle("active", parseInt(b.dataset.suby) === Math.round(y * 100)));
      }
    }
    else if (t === "logo") state.overlays.logo_pos[1] = y;
    else if (t === "extra") state.overlays.extra_text_pos[1] = y;
    else if (t === "blur") {
      const box = state.overlays.blur_boxes[state.activeBlurIndex];
      if (box) {
        box.y = y;
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
      }
    }
    updateOverlayPositions();
  });

  posSizeSlider.addEventListener("input", () => {
    const isSub = (state.activeOverlayTarget === "subtitle");
    const val = isSub ? parseFloat(posSizeSlider.value) : parseInt(posSizeSlider.value);
    const t = state.activeOverlayTarget;
    if (t === "title") {
      state.overlays.title_size = val;
      posSizeVal.innerText = `${val}px`;
    } else if (t === "subtitle") {
      state.overlays.subtitle_size = val;
      state.overlays.subtitle_size_pct = val;
      if (subSizeSlider) subSizeSlider.value = val;
      if (subSizeVal) subSizeVal.innerText = `${val.toFixed(1)}%`;
      posSizeVal.innerText = `${val.toFixed(1)}%`;
      if (subSizePresetBtns) {
        subSizePresetBtns.forEach(b => b.classList.toggle("active", Math.abs(parseFloat(b.dataset.subsize) - val) < 0.1));
      }
    } else if (t === "extra") {
      state.overlays.extra_size = val;
      posSizeVal.innerText = `${val}px`;
    } else if (t === "logo") {
      state.overlays.logo_width_frac = val / 100.0;
      logoSizeSlider.value = val;
      logoSizeVal.innerText = `${val}%`;
      posSizeVal.innerText = `${val}%`;
    } else if (t === "blur") {
      const box = state.overlays.blur_boxes[state.activeBlurIndex];
      if (box) {
        box.w = val / 100.0;
        posSizeVal.innerText = `${val}%`;
        renderBlurBoxesList();
        renderBlurBoxesOnCanvas();
      }
    }
    updateOverlayPositions();
  });

  function syncPositionControlsToTarget() {
    const t = state.activeOverlayTarget;
    let pos = [0.5, 0.5];
    let size = 54;
    let minSize = 16, maxSize = 96, stepSize = 2;
    let unit = "px";
    let label = "Size / Scale";

    if (t === "title") {
      pos = state.overlays.title_pos;
      size = state.overlays.title_size;
      minSize = 18; maxSize = 96; stepSize = 2;
      unit = "px";
      label = "Title Font Size";
    } else if (t === "subtitle") {
      pos = state.overlays.subtitle_pos;
      size = state.overlays.subtitle_size_pct || state.overlays.subtitle_size || 3.6;
      minSize = 2.0; maxSize = 6.5; stepSize = 0.2;
      unit = "%";
      label = "Subtitle Size (% of Video Height)";
    } else if (t === "extra") {
      pos = state.overlays.extra_text_pos;
      size = state.overlays.extra_size;
      minSize = 16; maxSize = 80; stepSize = 2;
      unit = "px";
      label = "Extra Font Size";
    } else if (t === "logo") {
      pos = state.overlays.logo_pos;
      size = Math.round(state.overlays.logo_width_frac * 100);
      minSize = 6; maxSize = 40; stepSize = 1;
      unit = "%";
      label = "Logo Width";
    } else if (t === "blur") {
      const box = state.overlays.blur_boxes[state.activeBlurIndex] || state.overlays.blur_boxes[0];
      if (box) {
        pos = [box.x, box.y];
        size = Math.round(box.w * 100);
      }
      minSize = 5; maxSize = 70; stepSize = 1;
      unit = "%";
      label = "Blur Box Width";
    }

    posXSlider.value = Math.round(pos[0] * 100);
    posYSlider.value = Math.round(pos[1] * 100);
    posXVal.innerText = `${posXSlider.value}%`;
    posYVal.innerText = `${posYSlider.value}%`;

    posSizeSlider.min = minSize;
    posSizeSlider.max = maxSize;
    posSizeSlider.step = stepSize;
    posSizeSlider.value = size;
    posSizeVal.innerText = `${unit === "%" && t === "subtitle" ? Number(size).toFixed(1) : size}${unit}`;

    const sizeLabelElem = sizeStepper ? sizeStepper.querySelector("label") : null;
    if (sizeLabelElem) {
      sizeLabelElem.innerHTML = `${label} (<span id="posSizeVal">${unit === "%" && t === "subtitle" ? Number(size).toFixed(1) : size}${unit}</span>)`;
    }
  }

  // Direct Interactive Dragging on Canvas
  let activeDragTarget = null;
  let dragOffset = { x: 0, y: 0 };

  function setupCanvasDraggable(elem, getPos, setPos, onSelect) {
    if (!elem) return;
    function startDrag(e) {
      if (e.target.closest && e.target.closest(".blur-resize-handle")) return;
      if (e.type === "touchstart" && e.cancelable) {
        e.preventDefault();
      }
      e.stopPropagation();
      onSelect();
      activeDragTarget = { elem, getPos, setPos };
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      const rect = previewContainer.getBoundingClientRect();
      const currentPos = getPos();
      dragOffset = {
        x: (clientX - rect.left) / rect.width - currentPos[0],
        y: (clientY - rect.top) / rect.height - currentPos[1],
      };
    }
    elem.addEventListener("mousedown", startDrag);
    elem.addEventListener("touchstart", startDrag, { passive: false });
  }

  window.addEventListener("mousemove", (e) => {
    if (!activeDragTarget) return;
    const clientX = e.clientX;
    const clientY = e.clientY;
    const rect = previewContainer.getBoundingClientRect();
    const nx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width - dragOffset.x));
    const ny = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height - dragOffset.y));
    activeDragTarget.setPos([nx, ny]);
    syncPositionControlsToTarget();
    if (state.activeOverlayTarget === "subtitle" && subYSlider) {
      subYSlider.value = Math.round(ny * 100);
      if (subYVal) subYVal.innerText = `${Math.round(ny * 100)}%`;
      if (subYPresetBtns) {
        subYPresetBtns.forEach(b => b.classList.toggle("active", parseInt(b.dataset.suby) === Math.round(ny * 100)));
      }
    }
    updateOverlayPositions();
  });

  window.addEventListener("touchmove", (e) => {
    if (!activeDragTarget || !e.touches || !e.touches[0]) return;
    if (e.cancelable) e.preventDefault();
    const clientX = e.touches[0].clientX;
    const clientY = e.touches[0].clientY;
    const rect = previewContainer.getBoundingClientRect();
    const nx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width - dragOffset.x));
    const ny = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height - dragOffset.y));
    activeDragTarget.setPos([nx, ny]);
    syncPositionControlsToTarget();
    if (state.activeOverlayTarget === "subtitle" && subYSlider) {
      subYSlider.value = Math.round(ny * 100);
      if (subYVal) subYVal.innerText = `${Math.round(ny * 100)}%`;
      if (subYPresetBtns) {
        subYPresetBtns.forEach(b => b.classList.toggle("active", parseInt(b.dataset.suby) === Math.round(ny * 100)));
      }
    }
    updateOverlayPositions();
  }, { passive: false });

  window.addEventListener("mouseup", () => { activeDragTarget = null; });
  window.addEventListener("touchend", () => { activeDragTarget = null; });
  window.addEventListener("resize", updateOverlayPositions);

  // Bind Canvas Drag to Title, Extra, Logo, Subtitle
  setupCanvasDraggable(
    overlayTitle,
    () => state.overlays.title_pos,
    ([nx, ny]) => { state.overlays.title_pos = [nx, ny]; },
    () => {
      state.activeOverlayTarget = "title";
      segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "title"));
      syncPositionControlsToTarget();
    }
  );

  setupCanvasDraggable(
    overlaySubtitle,
    () => state.overlays.subtitle_pos,
    ([nx, ny]) => { state.overlays.subtitle_pos = [nx, ny]; },
    () => {
      state.activeOverlayTarget = "subtitle";
      segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "subtitle"));
      syncPositionControlsToTarget();
    }
  );

  setupCanvasDraggable(
    overlayExtra,
    () => state.overlays.extra_text_pos,
    ([nx, ny]) => { state.overlays.extra_text_pos = [nx, ny]; },
    () => {
      state.activeOverlayTarget = "extra";
      segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "extra"));
      syncPositionControlsToTarget();
    }
  );

  setupCanvasDraggable(
    overlayLogo,
    () => state.overlays.logo_pos,
    ([nx, ny]) => { state.overlays.logo_pos = [nx, ny]; },
    () => {
      state.activeOverlayTarget = "logo";
      segBtns.forEach(b => b.classList.toggle("active", b.dataset.target === "logo"));
      syncPositionControlsToTarget();
    }
  );

  function updateOverlayPositions() {
    // Title
    overlayTitle.style.left = `${state.overlays.title_pos[0] * 100}%`;
    overlayTitle.style.top = `${state.overlays.title_pos[1] * 100}%`;
    overlayTitle.style.fontSize = `${state.overlays.title_size * 0.5}px`;

    // Subtitle (Rendered strictly above blur box)
    if (overlaySubtitle) {
      overlaySubtitle.classList.toggle("hidden", !state.overlays.burn_subtitles);
      overlaySubtitle.style.left = `${state.overlays.subtitle_pos[0] * 100}%`;
      overlaySubtitle.style.top = `${state.overlays.subtitle_pos[1] * 100}%`;
      const containerH = previewContainer.clientHeight || 360;
      const sizePct = state.overlays.subtitle_size_pct || state.overlays.subtitle_size || 3.6;
      const previewFontSize = Math.max(12, Math.round(containerH * (sizePct / 100.0)));
      overlaySubtitle.style.fontSize = `${previewFontSize}px`;
      const widthPct = state.overlays.subtitle_width_pct || 85;
      overlaySubtitle.style.maxWidth = `${widthPct}%`;
      overlaySubtitle.style.color = state.overlays.subtitle_color || "#FFDE00";
      if (state.overlays.subtitle_style === "box") {
        overlaySubtitle.classList.add("style-box");
      } else {
        overlaySubtitle.classList.remove("style-box");
      }
    }

    // Extra
    overlayExtra.style.left = `${state.overlays.extra_text_pos[0] * 100}%`;
    overlayExtra.style.top = `${state.overlays.extra_text_pos[1] * 100}%`;
    overlayExtra.style.fontSize = `${state.overlays.extra_size * 0.5}px`;

    // Logo
    overlayLogo.style.left = `${state.overlays.logo_pos[0] * 100}%`;
    overlayLogo.style.top = `${state.overlays.logo_pos[1] * 100}%`;
    overlayLogo.style.width = `${state.overlays.logo_width_frac * 100}%`;
  }

  // ---------------- Voice Settings ----------------
  const edgeVoiceSelect = document.getElementById("edgeVoiceSelect");
  const voiceSpeedSlider = document.getElementById("voiceSpeedSlider");
  const voiceSpeedVal = document.getElementById("voiceSpeedVal");
  const voiceVolSlider = document.getElementById("voiceVolSlider");
  const voiceVolVal = document.getElementById("voiceVolVal");
  const shortPausesCheck = document.getElementById("shortPausesCheck");

  voiceSpeedSlider.addEventListener("input", () => {
    const val = parseInt(voiceSpeedSlider.value);
    voiceSpeedVal.innerText = `${val >= 0 ? '+' : ''}${val}%`;
  });
  voiceVolSlider.addEventListener("input", () => {
    voiceVolVal.innerText = `${voiceVolSlider.value}%`;
  });

  // ---------------- Job Execution & WebSockets ----------------
  const startJobBtn = document.getElementById("startJobBtn");
  const stopJobBtn = document.getElementById("stopJobBtn");
  const jobStatusBadge = document.getElementById("jobStatusBadge");
  const jobStageText = document.getElementById("jobStageText");
  const jobProgressBar = document.getElementById("jobProgressBar");
  const jobProgressLabel = document.getElementById("jobProgressLabel");
  const jobProgressPercent = document.getElementById("jobProgressPercent");
  const liveLogConsole = document.getElementById("liveLogConsole");
  const logLinesCount = document.getElementById("logLinesCount");

  let logLines = [];

  function appendLog(line) {
    logLines.push(line);
    if (logLines.length > 500) logLines.shift();
    liveLogConsole.innerText = logLines.join("\n");
    liveLogConsole.scrollTop = liveLogConsole.scrollHeight;
    logLinesCount.innerText = `${logLines.length} lines`;
  }

  // Logs Drawer Controls
  const drawerToggleBtn = document.getElementById("drawerToggleBtn");
  const logsDrawer = document.getElementById("logsDrawer");
  const drawerArrow = document.getElementById("drawerArrow");
  const copyLogsBtn = document.getElementById("copyLogsBtn");
  const clearLogsBtn = document.getElementById("clearLogsBtn");
  const liveDot = document.getElementById("liveDot");
  const quickWatchBtn = document.getElementById("quickWatchBtn");

  function toggleLogsDrawer(forceOpen = null) {
    if (!logsDrawer) return;
    if (forceOpen === true) {
      logsDrawer.classList.remove("hidden");
      if (drawerArrow) drawerArrow.classList.add("open");
    } else if (forceOpen === false) {
      logsDrawer.classList.add("hidden");
      if (drawerArrow) drawerArrow.classList.remove("open");
    } else {
      const isHidden = logsDrawer.classList.toggle("hidden");
      if (drawerArrow) drawerArrow.classList.toggle("open", !isHidden);
    }
  }

  if (drawerToggleBtn) {
    drawerToggleBtn.addEventListener("click", () => toggleLogsDrawer());
  }

  if (copyLogsBtn) {
    copyLogsBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(logLines.join("\n"));
      const oldHtml = copyLogsBtn.innerHTML;
      copyLogsBtn.innerText = "Copied!";
      setTimeout(() => { copyLogsBtn.innerHTML = oldHtml; }, 1500);
    });
  }

  if (clearLogsBtn) {
    clearLogsBtn.addEventListener("click", () => {
      logLines = [];
      liveLogConsole.innerText = "[Console cleared]";
      logLinesCount.innerText = "0 lines";
    });
  }

  if (quickWatchBtn) {
    quickWatchBtn.addEventListener("click", () => {
      if (state.activeJobId) openVideoModal(state.activeJobId);
    });
  }

  startJobBtn.addEventListener("click", async () => {
    if (!state.selectedSource) {
      alert("Please select or upload a source video first!");
      return;
    }

    const payload = {
      source_id: state.selectedSource.id,
      voice: edgeVoiceSelect.value,
      edge_tts_rate: voiceSpeedVal.innerText,
      output_ratio: ratioSelect.value,
      frame_fill: fillSelect.value,
      zoom_factor: parseFloat(zoomSlider.value),
      mirror_video: flipCheck.checked,
      voice_volume_percent: parseInt(voiceVolSlider.value),
      short_pauses: shortPausesCheck.checked,
      enable_original_background: state.enable_original_background,
      original_background_volume: state.original_background_volume,
      overlays: {
        blur_boxes: state.overlays.blur_boxes,
        blur_strength: 18,
        title_text: state.overlays.title_text,
        title_position: state.overlays.title_pos,
        title_font_size: state.overlays.title_size,
        logo_enabled: state.overlays.logo_enabled,
        logo_path: state.overlays.logo_path,
        logo_position: state.overlays.logo_pos,
        logo_width_fraction: state.overlays.logo_width_frac,
        extra_text: state.overlays.extra_text,
        extra_text_position: state.overlays.extra_text_pos,
        extra_text_font_size: state.overlays.extra_size,
        burn_subtitles: state.overlays.burn_subtitles,
        subtitle_position: state.overlays.subtitle_pos,
        subtitle_font_size: state.overlays.subtitle_size_pct || state.overlays.subtitle_size || 3.6,
        subtitle_size_percent: state.overlays.subtitle_size_pct || state.overlays.subtitle_size || 3.6,
        subtitle_box_width_percent: state.overlays.subtitle_width_pct || 85.0,
        subtitle_font_color: state.overlays.subtitle_color,
        subtitle_style: state.overlays.subtitle_style,
      },
    };

    startJobBtn.disabled = true;
    stopJobBtn.disabled = false;
    if (quickWatchBtn) quickWatchBtn.classList.add("hidden");
    logLines = [];
    appendLog("Initiating job request...");
    toggleLogsDrawer(true);

    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      state.activeJobId = data.job_id;
      connectJobWebSocket(data.job_id);
    } catch (err) {
      alert("Failed to start job: " + err.message);
      startJobBtn.disabled = false;
      stopJobBtn.disabled = true;
    }
  });

  stopJobBtn.addEventListener("click", async () => {
    if (!state.activeJobId) return;
    try {
      await fetch(`/api/jobs/${state.activeJobId}/stop`, { method: "POST" });
      appendLog("Stop requested by user.");
    } catch (err) {
      console.error(err);
    }
  });

  function connectJobWebSocket(jobId) {
    if (state.activeWs) {
      state.activeWs.close();
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/ws/jobs/${jobId}`);
    state.activeWs = ws;

    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.kind === "log") {
          appendLog(ev.text);
        } else if (ev.kind === "progress") {
          const pct = ev.total > 0 ? Math.round((ev.current / ev.total) * 100) : 0;
          jobProgressBar.style.width = `${pct}%`;
          jobProgressPercent.innerText = `${pct}%`;
          jobProgressLabel.innerText = `${ev.label} (${ev.current}/${ev.total})`;
        } else if (ev.kind === "stage") {
          jobStageText.innerText = ev.stage;
        } else if (ev.kind === "status") {
          setJobStatusBadge(ev.status);
        } else if (ev.kind === "done") {
          setJobStatusBadge("completed");
          jobStageText.innerText = "Job Completed!";
          startJobBtn.disabled = false;
          stopJobBtn.disabled = true;
          if (quickWatchBtn) quickWatchBtn.classList.remove("hidden");
          loadJobs();
        } else if (ev.kind === "stopped" || ev.kind === "error") {
          setJobStatusBadge(ev.kind === "stopped" ? "stopped" : "failed");
          startJobBtn.disabled = false;
          stopJobBtn.disabled = true;
          loadJobs();
        }
      } catch (err) {
        console.error("WS error:", err);
      }
    };

    ws.onclose = () => {
      state.activeWs = null;
    };
  }

  function setJobStatusBadge(status) {
    jobStatusBadge.className = `status-badge ${status}`;
    jobStatusBadge.innerText = (status || "READY").toUpperCase();
    if (liveDot) {
      liveDot.classList.toggle("active", status === "running");
    }
  }

  // ---------------- Generated Jobs Tab ----------------
  const jobsList = document.getElementById("jobsList");
  const refreshJobsBtn = document.getElementById("refreshJobsBtn");

  async function loadJobs() {
    try {
      const res = await fetch("/api/jobs");
      state.jobs = await res.json();
      document.getElementById("jobCountBadge").innerText = state.jobs.length;
      renderJobsList();
    } catch (err) {
      console.error(err);
    }
  }

  if (refreshJobsBtn) refreshJobsBtn.addEventListener("click", loadJobs);

  function renderJobsList() {
    if (!jobsList) return;
    if (state.jobs.length === 0) {
      jobsList.innerHTML = `<div class="card p-4 muted text-center">No generated recap jobs yet. Launch one from Workspace!</div>`;
      return;
    }

    jobsList.innerHTML = state.jobs.map(job => {
      const isDone = job.status === "completed" && job.output_video_path;
      return `
        <div class="job-item-card">
          <div class="job-item-left">
            <span class="status-badge ${job.status}">${job.status.toUpperCase()}</span>
            <div>
              <strong>${escapeHtml(job.source_title)}</strong>
              <div class="muted small">${job.voice} · Ratio: ${job.output_ratio} · ${formatDate(job.created_at)}</div>
              ${job.stage ? `<div class="small text-accent">${escapeHtml(job.stage)}</div>` : ''}
              ${job.error_message ? `<div class="small text-danger">${escapeHtml(job.error_message)}</div>` : ''}
            </div>
          </div>
          <div class="job-item-right">
            ${isDone ? `
              <button class="btn btn-sm btn-primary play-job-btn" data-id="${job.job_id}">Watch Video</button>
              <a href="/api/jobs/${job.job_id}/final" download class="btn btn-sm btn-secondary">Download MP4</a>
            ` : ''}
            <button class="btn btn-sm btn-secondary inspect-plan-btn" data-id="${job.job_id}">Inspect Plan</button>
            ${job.status === 'stopped' || job.status === 'failed' ? `
              <button class="btn btn-sm btn-success resume-job-btn" data-id="${job.job_id}">Resume</button>
            ` : ''}
            <button class="btn btn-sm btn-danger del-job-btn" data-id="${job.job_id}">Delete</button>
          </div>
        </div>
      `;
    }).join("");

    // Attach listeners
    jobsList.querySelectorAll(".play-job-btn").forEach(b => {
      b.addEventListener("click", () => {
        openVideoModal(b.dataset.id);
      });
    });

    jobsList.querySelectorAll(".inspect-plan-btn").forEach(b => {
      b.addEventListener("click", () => {
        openPlanModal(b.dataset.id);
      });
    });

    jobsList.querySelectorAll(".resume-job-btn").forEach(b => {
      b.addEventListener("click", async () => {
        await fetch(`/api/jobs/${b.dataset.id}/resume`, { method: "POST" });
        loadJobs();
        document.querySelector('.nav-btn[data-tab="workspace"]').click();
        connectJobWebSocket(b.dataset.id);
      });
    });

    jobsList.querySelectorAll(".del-job-btn").forEach(b => {
      b.addEventListener("click", async () => {
        if (!confirm("Delete this job and output files?")) return;
        await fetch(`/api/jobs/${b.dataset.id}`, { method: "DELETE" });
        loadJobs();
      });
    });
  }

  // ---------------- Modals ----------------
  const videoModal = document.getElementById("videoModal");
  const modalVideoPlayer = document.getElementById("modalVideoPlayer");
  const modalVideoTitle = document.getElementById("modalVideoTitle");
  const modalCloseBtn = document.getElementById("modalCloseBtn");
  const modalDownloadSrt = document.getElementById("modalDownloadSrt");
  const modalDownloadAss = document.getElementById("modalDownloadAss");

  function openVideoModal(jobId) {
    const job = state.jobs.find(j => j.job_id === jobId);
    if (!job) return;
    modalVideoTitle.innerText = `${job.source_title} (Myanmar Recap)`;
    modalVideoPlayer.src = `/api/jobs/${jobId}/final`;
    if (modalDownloadSrt) {
      modalDownloadSrt.href = `/api/jobs/${jobId}/subtitles.srt`;
      modalDownloadSrt.download = `${job.source_title || 'recap'}_subtitles.srt`;
    }
    if (modalDownloadAss) {
      modalDownloadAss.href = `/api/jobs/${jobId}/subtitles.ass`;
      modalDownloadAss.download = `${job.source_title || 'recap'}_subtitles.ass`;
    }
    videoModal.classList.remove("hidden");
    modalVideoPlayer.play();
  }

  modalCloseBtn.addEventListener("click", () => {
    modalVideoPlayer.pause();
    modalVideoPlayer.src = "";
    videoModal.classList.add("hidden");
  });

  const planModal = document.getElementById("planModal");
  const planSegmentsList = document.getElementById("planSegmentsList");
  const planModalCloseBtn = document.getElementById("planModalCloseBtn");

  async function openPlanModal(jobId) {
    planSegmentsList.innerHTML = `<span class="muted">Loading plan & translations...</span>`;
    planModal.classList.remove("hidden");
    try {
      const res = await fetch(`/api/jobs/${jobId}/plan`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      let segments = [];
      if (Array.isArray(data.translations)) {
        segments = data.translations;
      } else if (data.translations && Array.isArray(data.translations.items)) {
        segments = data.translations.items;
      } else if (data.translations && Array.isArray(data.translations.segments)) {
        segments = data.translations.segments;
      } else if (data.plan && Array.isArray(data.plan.segments)) {
        segments = data.plan.segments;
      }

      if (!segments || segments.length === 0) {
        planSegmentsList.innerHTML = `<div class="p-3 muted">No translation segments generated yet.</div>`;
        return;
      }

      planSegmentsList.innerHTML = segments.map((seg, i) => {
        const start = seg.speech_start ?? seg.gemini_start ?? seg.video_start ?? seg.start ?? 0;
        const end = seg.speech_end ?? seg.gemini_end ?? seg.video_end ?? seg.end ?? 0;
        const timeLabel = seg.timestamp || `[${Number(start).toFixed(2)}s - ${Number(end).toFixed(2)}s]`;
        const srcText = seg.source_text || seg.text || "";
        const mmText = seg.translation || seg.narration || seg.myanmar_text || seg.text_mm || "";
        return `
          <div class="plan-segment-item" style="padding: 10px 12px; margin-bottom: 8px; background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px;">
            <div class="space-between mb-1" style="display: flex; justify-content: space-between; align-items: center;">
              <strong class="font-mono small" style="color: var(--color-accent); font-size: 0.85rem;">#${i + 1} · ${escapeHtml(timeLabel)}</strong>
              ${seg.semantic_boundary ? `<span class="badge badge-secondary" style="font-size: 0.72rem; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.08);">${escapeHtml(seg.semantic_boundary)}</span>` : ''}
            </div>
            <div class="small muted mb-1" style="color: var(--color-text-muted); font-size: 0.88rem; line-height: 1.4;">${escapeHtml(srcText)}</div>
            <div class="mm-text" style="color: #6ee7b7; font-size: 1.05rem; line-height: 1.6; font-weight: 500;">${escapeHtml(mmText)}</div>
          </div>
        `;
      }).join("");
    } catch (err) {
      planSegmentsList.innerHTML = `<div class="p-3 text-danger">Error loading plan: ${escapeHtml(err.message)}</div>`;
    }
  }

  planModalCloseBtn.addEventListener("click", () => {
    planModal.classList.add("hidden");
  });
  planModal.querySelector(".modal-backdrop")?.addEventListener("click", () => {
    planModal.classList.add("hidden");
  });
  videoModal.querySelector(".modal-backdrop")?.addEventListener("click", () => {
    modalVideoPlayer.pause();
    modalVideoPlayer.src = "";
    videoModal.classList.add("hidden");
  });

  // ---------------- Settings Tab ----------------
  const settingsForm = document.getElementById("settingsForm");
  const geminiApiKeyInput = document.getElementById("geminiApiKeyInput");
  const toggleKeyVisBtn = document.getElementById("toggleKeyVisBtn");
  const testKeyBtn = document.getElementById("testKeyBtn");
  const keyTestResult = document.getElementById("keyTestResult");
  const fallbackKeysContainer = document.getElementById("fallbackKeysContainer");
  const addFallbackKeyBtn = document.getElementById("addFallbackKeyBtn");
  const geminiProxyInput = document.getElementById("geminiProxyInput");
  const geminiModelSelect = document.getElementById("geminiModelSelect");

  let fallbackKeysList = [];

  async function loadSettings() {
    try {
      const res = await fetch("/api/settings");
      const cfg = await res.json();
      geminiApiKeyInput.value = cfg.gemini_api_key_masked || "";
      geminiProxyInput.value = cfg.gemini_proxy || "";
      geminiModelSelect.value = cfg.gemini_text_model || "gemini-3.5-flash";
      fallbackKeysList = cfg.fallback_keys || [];
      renderFallbackKeys();
    } catch (err) {
      console.error(err);
    }
  }

  toggleKeyVisBtn.addEventListener("click", () => {
    if (geminiApiKeyInput.type === "password") {
      geminiApiKeyInput.type = "text";
      toggleKeyVisBtn.innerText = "Hide";
    } else {
      geminiApiKeyInput.type = "password";
      toggleKeyVisBtn.innerText = "Show";
    }
  });

  testKeyBtn.addEventListener("click", async () => {
    const key = geminiApiKeyInput.value.trim();
    testKeyBtn.disabled = true;
    keyTestResult.className = "test-result-box";
    keyTestResult.innerText = "Testing key against Gemini API...";
    keyTestResult.classList.remove("hidden");

    try {
      const res = await fetch("/api/settings/test-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key, proxy: geminiProxyInput.value.trim() }),
      });
      const data = await res.json();
      keyTestResult.className = `test-result-box ${data.ok ? 'success' : 'error'}`;
      keyTestResult.innerText = data.message;
    } catch (err) {
      keyTestResult.className = "test-result-box error";
      keyTestResult.innerText = "Test request failed: " + err.message;
    } finally {
      testKeyBtn.disabled = false;
    }
  });

  addFallbackKeyBtn.addEventListener("click", () => {
    fallbackKeysList.push({ key: "", masked: "" });
    renderFallbackKeys();
  });

  function renderFallbackKeys() {
    fallbackKeysContainer.innerHTML = fallbackKeysList.map((item, idx) => `
      <div class="row-flex mb-2">
        <input type="text" class="fallback-key-input" data-idx="${idx}" placeholder="Project Key ${idx + 1}" value="${item.masked || item.key || ''}">
        <button type="button" class="btn btn-sm btn-danger del-fallback-btn" data-idx="${idx}">Remove</button>
      </div>
    `).join("");

    fallbackKeysContainer.querySelectorAll(".del-fallback-btn").forEach(b => {
      b.addEventListener("click", () => {
        fallbackKeysList.splice(parseInt(b.dataset.idx), 1);
        renderFallbackKeys();
      });
    });

    fallbackKeysContainer.querySelectorAll(".fallback-key-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        fallbackKeysList[parseInt(inp.dataset.idx)].key = e.target.value.trim();
      });
    });
  }

  settingsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      gemini_api_key: geminiApiKeyInput.value.trim(),
      gemini_proxy: geminiProxyInput.value.trim(),
      gemini_text_model: geminiModelSelect.value,
      fallback_keys: fallbackKeysList,
    };
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        alert("Settings saved successfully!");
        loadSettings();
      }
    } catch (err) {
      alert("Failed to save settings: " + err.message);
    }
  });

  // Helpers
  function formatSeconds(sec) {
    if (!sec || isNaN(sec)) return "00:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function formatDate(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function escapeHtml(str) {
    return (str || "").replace(/[&<>"']/g, m => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[m]);
  }

  // Initial load
  loadSources();
  loadJobs();
});
