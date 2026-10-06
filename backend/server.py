#!/usr/bin/env python3
"""X2mate backend API — yt-dlp downloads for the Vercel frontend.

Host on Railway / Render / a VPS (not Vercel). Set CORS and point the
frontend config.js API base at this server.
"""

from __future__ import annotations

import atexit
import base64
import os
import platform
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError

    _YTDLP_OK = True
    _YTDLP_VER = getattr(yt_dlp.version, "__version__", "?")
except ImportError:
    yt_dlp = None  # type: ignore
    DownloadError = Exception  # type: ignore
    _YTDLP_OK = False
    _YTDLP_VER = "?"

try:
    from mutagen.mp4 import MP4

    _MUTAGEN_OK = True
except ImportError:
    MP4 = None  # type: ignore
    _MUTAGEN_OK = False

_FFMPEG = shutil.which("ffmpeg")
_FFMPEG_OK = bool(_FFMPEG and os.path.isfile(_FFMPEG))

APP_VERSION = "1.3.0"
VIDEO_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160)
AUDIO_BITRATES = (64, 96, 128, 160, 192, 256, 320)
_YOUTUBE_CLIENTS = [
    "android",
    "android_vr",
    "ios",
    "mweb",
    "web_safari",
    "web_embedded",
    "tv",
]
_COOKIE_FILE: str | None = None


def _init_youtube_cookies() -> str | None:
    """Write Netscape cookies from env to a temp file for yt-dlp cookiefile."""
    raw = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if not raw:
        b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
        if b64:
            try:
                raw = base64.b64decode(b64).decode("utf-8")
            except Exception as exc:
                print(f"⚠ YOUTUBE_COOKIES_B64 decode failed: {exc}")
                return None
    if not raw:
        return None
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if "Netscape" not in raw.split("\n", 1)[0] and not raw.lstrip().startswith("#"):
        # Accept files that start with cookie rows; yt-dlp wants Netscape header
        raw = "# Netscape HTTP Cookie File\n" + raw
    fd, path = tempfile.mkstemp(prefix="yt_cookies_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(raw if raw.endswith("\n") else raw + "\n")
        print(f"✓ YouTube cookies loaded ({len(raw)} bytes)")
        return path
    except Exception as exc:
        print(f"⚠ failed to write cookie file: {exc}")
        try:
            os.unlink(path)
        except OSError:
            pass
        return None


def _cleanup_cookie_file() -> None:
    if _COOKIE_FILE and os.path.isfile(_COOKIE_FILE):
        try:
            os.unlink(_COOKIE_FILE)
        except OSError:
            pass


def _is_bot_block(msg: str) -> bool:
    low = msg.lower()
    return any(
        x in low
        for x in (
            "sign in to confirm",
            "confirm you're not a bot",
            "confirm you’re not a bot",
            "not a bot",
            "bot detection",
        )
    )


def _ytdlp_error(msg: str) -> str:
    if _is_bot_block(msg):
        print("⚠ Server IP blocked by YouTube; refresh YOUTUBE_COOKIES on Railway.")
        return (
            "YouTube blocked this server (bot check). "
            "Set YOUTUBE_COOKIES on Railway with a fresh Netscape cookies.txt export."
        )
    return msg


app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_TEMP_ROOT = Path(tempfile.mkdtemp(prefix="x2mate_"))
_COOKIE_FILE = _init_youtube_cookies()


def _cleanup_temp_root() -> None:
    shutil.rmtree(_TEMP_ROOT, ignore_errors=True)


atexit.register(_cleanup_temp_root)
atexit.register(_cleanup_cookie_file)


def _format_bytes(n: int | float | None) -> str:
    if n is None or n <= 0:
        return "unknown"
    n = float(n)
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} B"


def _height_label(h: int) -> str:
    if h >= 2160:
        return f"{h}p (4K)"
    if h >= 1440:
        return f"{h}p (2K)"
    return f"{h}p"


def sanitize(name: str) -> str:
    name = re.sub(r"\s*prod\.[A-Za-z0-9_-]+", "", name, flags=re.IGNORECASE)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "video")[:120]


def vid_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else "video"


def format_duration(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _vtt_to_lyrics(text: str) -> str:
    lines_out: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if line.startswith("NOTE") or line.startswith("STYLE") or line.startswith("REGION"):
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.search(r"\d{2}:\d{2}:\d{2}[\.,]\d{3}\s*-->", line):
            continue
        if re.search(r"\d{2}:\d{2}[\.,]\d{3}\s*-->", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        lines_out.append(clean)
    return "\n".join(lines_out).strip()


def _subtitle_paths_from_info(info: dict | None) -> list[Path]:
    paths: list[Path] = []
    if not info:
        return paths
    requested = info.get("requested_subtitles") or {}
    if isinstance(requested, dict):
        for _lang, meta in requested.items():
            if not isinstance(meta, dict):
                continue
            fp = meta.get("filepath") or meta.get("file")
            if fp and os.path.isfile(fp):
                paths.append(Path(fp))
    return paths


def _find_subtitle_file(
    out_dir: str, dest_base: str, info: dict | None = None
) -> Path | None:
    from_info = _subtitle_paths_from_info(info)
    if from_info:
        from_info.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return from_info[0]

    base = Path(out_dir)
    exts = (".vtt", ".srt", ".ttml", ".srv3")
    found: list[Path] = []
    for pat in (
        f"{dest_base}*.vtt",
        f"{dest_base}*.srt",
        f"{dest_base}*.ttml",
        f"{dest_base}*.srv3",
    ):
        found.extend(base.glob(pat))
    if not found:
        try:
            cutoff = time.time() - 600
            for p in base.iterdir():
                if (
                    p.is_file()
                    and p.suffix.lower() in exts
                    and p.stat().st_mtime >= cutoff
                ):
                    found.append(p)
        except OSError:
            pass
    if not found:
        return None

    def _rank(p: Path) -> tuple[int, float]:
        name = p.name.lower()
        auto = 1 if (".auto." in name or name.endswith(".auto.vtt")) else 0
        return (auto, -p.stat().st_mtime)

    found.sort(key=_rank)
    return found[0]


def _embed_lyrics_m4a(m4a_path: str, lyrics: str, log) -> bool:
    if not lyrics.strip():
        return False
    if not _MUTAGEN_OK or MP4 is None:
        log("⚠ mutagen missing — cannot embed lyrics")
        return False
    try:
        audio = MP4(m4a_path)
        audio["\xa9lyr"] = [lyrics]
        audio.save()
        return True
    except Exception as e:
        log(f"⚠ lyrics embed failed: {e}")
        return False


def _embed_lyrics_after_download(
    out_dir: str,
    dest_base: str,
    final: str,
    log,
    info: dict | None = None,
) -> None:
    sub = _find_subtitle_file(out_dir, dest_base, info=info)
    if not sub:
        log("⚠ no lyrics/captions found")
        return
    try:
        raw = sub.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        log(f"⚠ could not read captions: {e}")
        return
    lyrics = _vtt_to_lyrics(raw)
    if not lyrics:
        log("⚠ captions empty after cleanup")
        return
    if _embed_lyrics_m4a(final, lyrics, log):
        log(f"── lyrics embedded ({sub.name})")
    try:
        for p in Path(out_dir).glob(f"{dest_base}.*"):
            if p.suffix.lower() in (".vtt", ".srt", ".ttml", ".srv3"):
                p.unlink(missing_ok=True)
        if sub.exists() and sub.suffix.lower() in (".vtt", ".srt", ".ttml", ".srv3"):
            sub.unlink(missing_ok=True)
    except Exception:
        pass


def _base_opts(*, skip_download: bool = True) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": list(_YOUTUBE_CLIENTS)}},
    }
    if skip_download:
        opts["skip_download"] = True
    if _COOKIE_FILE:
        opts["cookiefile"] = _COOKIE_FILE
    if _FFMPEG:
        opts["ffmpeg_location"] = os.path.dirname(_FFMPEG)
    return opts


def _format_selector(fmt: str, quality: str) -> tuple[str, list[str] | None]:
    if fmt == "mp3":
        return "bestaudio[ext=m4a]/bestaudio/best", [f"abr~{quality}", "abr"]
    h = int(quality)
    sel = (
        f"bestvideo[height<={h}][ext=mp4][protocol^=http]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={h}][protocol^=http]+bestaudio/"
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={h}]+bestaudio/"
        f"best[height<={h}]/best"
    )
    return sel, None


class _Abort(Exception):
    pass


def estimate_size_from_info(info: dict | None, fmt: str, quality: str) -> int | None:
    """Estimate bytes from an already-fetched yt-dlp info dict (no network)."""
    if not info:
        return None
    try:
        duration = float(info.get("duration") or 0) or 0.0
    except (TypeError, ValueError):
        duration = 0.0

    def _one(entry: dict | None) -> int:
        if not entry:
            return 0
        n = entry.get("filesize") or entry.get("filesize_approx") or 0
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return n
        try:
            tbr = float(entry.get("tbr") or 0)
        except (TypeError, ValueError):
            tbr = 0.0
        try:
            dur = float(entry.get("duration") or 0) or duration
        except (TypeError, ValueError):
            dur = duration
        if tbr > 0 and dur > 0:
            return int(tbr * 1000.0 / 8.0 * dur)
        return 0

    formats = info.get("formats") or []
    if fmt == "mp3":
        try:
            want = int(quality)
        except (TypeError, ValueError):
            want = 160
        best = None
        best_abr = -1.0
        for f in formats:
            acodec = f.get("acodec") or "none"
            vcodec = f.get("vcodec") or "none"
            if acodec == "none":
                continue
            if vcodec != "none" and f.get("height"):
                continue
            try:
                abr = float(f.get("abr") or f.get("tbr") or 0)
            except (TypeError, ValueError):
                abr = 0.0
            if abr <= want + 32 and abr >= best_abr:
                best_abr = abr
                best = f
        n = _one(best)
        if n > 0:
            return n
        if want > 0 and duration > 0:
            return int(want * 1000.0 / 8.0 * duration)
        return None

    try:
        want_h = int(quality)
    except (TypeError, ValueError):
        want_h = 1080
    best_v = None
    best_h = -1
    best_a = None
    best_abr = -1.0
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        if isinstance(h, int) and h > 0 and h <= want_h and vcodec != "none":
            if h >= best_h:
                best_h = h
                best_v = f
        if acodec != "none" and (vcodec == "none" or not f.get("height")):
            try:
                abr = float(f.get("abr") or f.get("tbr") or 0)
            except (TypeError, ValueError):
                abr = 0.0
            if abr >= best_abr:
                best_abr = abr
                best_a = f
    total = _one(best_v) + _one(best_a)
    if total > 0:
        return total
    if best_v:
        n = _one(best_v)
        if n > 0:
            return n
    return None


def estimate_download_size(yt_url: str, fmt: str, quality: str) -> int | None:
    if not _YTDLP_OK:
        raise RuntimeError("yt-dlp is not installed.")
    caps = probe_capabilities(yt_url)
    return estimate_size_from_info(caps.get("info"), fmt, quality)


def probe_capabilities(yt_url: str) -> dict:
    if not _YTDLP_OK:
        raise RuntimeError("yt-dlp is not installed.")
    opts = _base_opts()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
    except DownloadError as e:
        raise RuntimeError(_ytdlp_error(str(e))) from e
    formats = (info or {}).get("formats") or []
    heights: set[int] = set()
    abrs: list[float] = []
    for f in formats:
        h = f.get("height")
        if isinstance(h, int) and h > 0:
            heights.add(h)
        acodec = f.get("acodec") or "none"
        vcodec = f.get("vcodec") or "none"
        abr = f.get("abr") or f.get("tbr")
        if acodec != "none" and (vcodec == "none" or not f.get("height")):
            try:
                abrs.append(float(abr))
            except (TypeError, ValueError):
                pass
    max_h = max(heights) if heights else 0
    max_abr = max(abrs) if abrs else 0.0
    return {
        "title": (info or {}).get("title") or "",
        "heights": sorted(heights),
        "max_height": max_h,
        "max_abr": max_abr,
        "info": info,
    }


def resolve_quality_from_caps(caps: dict, fmt: str, quality: str) -> tuple[str, str | None]:
    if fmt == "mp3":
        want = int(quality)
        max_abr = caps["max_abr"]
        if max_abr <= 0:
            return quality, None
        available = [b for b in AUDIO_BITRATES if b <= max_abr + 32]
        if not available:
            available = list(AUDIO_BITRATES)
        best = max(available)
        if want > best:
            return str(best), (
                f"{want} kbps is not available for this video.\n"
                f"Highest available audio quality: {best} kbps."
            )
        return quality, None

    want_h = int(quality)
    max_h = int(caps["max_height"] or 0)
    if max_h <= 0:
        return quality, None
    ladder = [h for h in VIDEO_HEIGHTS if h <= max_h]
    if not ladder:
        ladder = [max_h]
    best = max(ladder)
    if max_h > best:
        best = max_h
    if want_h > max_h:
        return str(best), (
            f"{_height_label(want_h)} is not available for this video.\n"
            f"Highest available quality: {_height_label(best)}."
        )
    return quality, None


def resolve_quality(yt_url: str, fmt: str, quality: str) -> tuple[str, str | None]:
    caps = probe_capabilities(yt_url)
    return resolve_quality_from_caps(caps, fmt, quality)


def get_title(yt_url: str, log) -> str:
    if not _YTDLP_OK:
        return ""
    try:
        opts = _base_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
        title = (info or {}).get("title") or ""
        return sanitize(title)
    except Exception as e:
        log(f"⚠ title lookup failed: {e}")
        return ""


def search(query: str, limit: int = 12) -> list[dict]:
    if not _YTDLP_OK:
        raise RuntimeError("yt-dlp is not installed.")
    q = (query or "").strip()
    if not q:
        raise ValueError("empty search query")
    opts = _base_opts()
    opts["extract_flat"] = "in_playlist"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)
    except DownloadError as e:
        raise RuntimeError(_ytdlp_error(str(e))) from e
    out: list[dict] = []
    for e in (info or {}).get("entries") or []:
        if not e:
            continue
        vid = e.get("id") or ""
        if not vid or len(vid) != 11:
            url = e.get("url") or e.get("webpage_url") or ""
            m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
            vid = m.group(1) if m else ""
        if not vid:
            continue
        thumb = None
        thumbs = e.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url")
        if not thumb:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        out.append(
            {
                "id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": sanitize(e.get("title") or "Untitled"),
                "uploader": e.get("uploader") or e.get("channel") or "",
                "duration": e.get("duration"),
                "thumbnail": thumb,
            }
        )
    return out


def download_file(
    yt_url: str,
    fmt: str,
    quality: str,
    out_dir: str,
    dest_base: str,
    prog,
    log,
    stop: threading.Event,
) -> str:
    if not _YTDLP_OK:
        raise RuntimeError("yt-dlp is not installed.")
    if stop.is_set():
        raise InterruptedError

    outtmpl = os.path.join(out_dir, dest_base + ".%(ext)s")
    opts = _base_opts(skip_download=False)
    opts.update(
        {
            "outtmpl": outtmpl,
            "noprogress": True,
            "retries": 3,
            "fragment_retries": 3,
            "overwrites": True,
            "writethumbnail": True,
            "concurrent_fragment_downloads": 8,
        }
    )

    thumb_pps = [{"key": "FFmpegThumbnailsConvertor", "format": "jpg"}]
    meta_then_cover = [
        {"key": "FFmpegMetadata"},
        {"key": "EmbedThumbnail"},
    ]

    if fmt == "mp3":
        selector, sort = _format_selector(fmt, quality)
        opts["format"] = selector
        opts["format_sort"] = sort
        opts["postprocessors"] = thumb_pps + meta_then_cover
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["en", "en-US", "en-GB", "ar", "ar-SA"]
        opts["subtitlesformat"] = "vtt/best"
        opts["sleep_interval_subtitles"] = 1
        opts["ignoreerrors"] = True
        log("── audio container: m4a (cover + lyrics)")
    else:
        selector, _ = _format_selector(fmt, quality)
        opts["format"] = selector
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = thumb_pps + meta_then_cover

    def hook(d: dict):
        if stop.is_set():
            raise _Abort("cancelled")
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                prog(int(done / total * 70) + 5)
        elif status == "finished":
            prog(76)
            log(f"── downloaded: {os.path.basename(d.get('filename') or '')}")

    opts["progress_hooks"] = [hook]
    log(f"── yt-dlp starting ({'M4A' if fmt == 'mp3' else 'MP4'} @ {quality})")
    prog(2)

    info: dict | None = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=True)
            if stop.is_set():
                raise InterruptedError
            final = ydl.prepare_filename(info)
            if fmt == "mp3":
                root = os.path.splitext(final)[0]
                for ext in (".m4a", ".mp4", ".aac"):
                    candidate = root + ext
                    if os.path.isfile(candidate):
                        final = candidate
                        break
                else:
                    final = root + ".m4a"
            elif fmt == "mp4":
                root, _ = os.path.splitext(final)
                candidate = root + ".mp4"
                if os.path.isfile(candidate):
                    final = candidate
    except _Abort:
        raise InterruptedError
    except DownloadError as e:
        msg = str(e)
        if stop.is_set() or "abort" in msg.lower():
            raise InterruptedError
        raise RuntimeError(_ytdlp_error(msg)) from e

    if not os.path.isfile(final):
        matches = sorted(
            Path(out_dir).glob(dest_base + ".*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        matches = [
            p
            for p in matches
            if p.suffix.lower() in (".m4a", ".mp4", ".mp3", ".webm", ".aac")
        ]
        if matches:
            final = str(matches[0])
        else:
            raise RuntimeError(f"Download finished but file not found:\n{final}")

    if fmt == "mp3":
        prog(97)
        _embed_lyrics_after_download(out_dir, dest_base, final, log, info=info)

    # Rename from video-id basename to sanitized title when available
    title = sanitize((info or {}).get("title") or "")
    if title and title != dest_base:
        ext = Path(final).suffix
        target = Path(out_dir) / (title + ext)
        if not target.exists():
            try:
                Path(final).rename(target)
                final = str(target)
                log(f"── renamed: {target.name}")
            except OSError:
                pass

    prog(100)
    return final


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _cleanup_job_dir(job: dict) -> None:
    d = job.get("workdir")
    if d and Path(d).is_dir():
        shutil.rmtree(d, ignore_errors=True)
    job["dest"] = None
    job["workdir"] = None


@app.get("/api/status")
def system_status():
    return jsonify(
        {
            "version": APP_VERSION,
            "ytdlp_ok": _YTDLP_OK,
            "ytdlp_ver": _YTDLP_VER,
            "ffmpeg_ok": _FFMPEG_OK,
            "cookies_loaded": bool(_COOKIE_FILE),
            "python": platform.python_version(),
        }
    )


@app.post("/api/search")
def api_search():
    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "empty search query"}), 400
    try:
        results = search(query, limit=12)
        for r in results:
            r["duration_label"] = format_duration(r.get("duration"))
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/probe")
def api_probe():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    fmt = data.get("fmt") or "mp3"
    quality = str(data.get("quality") or ("320" if fmt == "mp3" else "1080"))
    if not url:
        return jsonify({"error": "missing url"}), 400
    try:
        caps = probe_capabilities(url)
        eff_q, downgrade_msg = resolve_quality_from_caps(caps, fmt, quality)
        size = estimate_size_from_info(caps.get("info"), fmt, eff_q)
        if fmt == "mp3":
            q_txt = f"{eff_q} kbps (M4A)"
        else:
            q_txt = _height_label(int(eff_q)) + " (MP4)"
        return jsonify(
            {
                "quality": eff_q,
                "downgrade_msg": downgrade_msg,
                "title": sanitize(caps.get("title") or ""),
                "size": size,
                "size_label": _format_bytes(size),
                "quality_label": q_txt,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/estimate")
def api_estimate():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    fmt = data.get("fmt") or "mp3"
    quality = str(data.get("quality") or ("320" if fmt == "mp3" else "1080"))
    if not url:
        return jsonify({"error": "missing url"}), 400
    try:
        size = estimate_download_size(url, fmt, quality)
        if fmt == "mp3":
            q_txt = f"{quality} kbps (M4A)"
        else:
            q_txt = _height_label(int(quality)) + " (MP4)"
        return jsonify(
            {
                "size": size,
                "size_label": _format_bytes(size),
                "quality_label": q_txt,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _run_download(job_id: str, url: str, fmt: str, quality: str):
    job = _get_job(job_id)
    if not job:
        return
    stop: threading.Event = job["stop"]
    workdir = Path(job["workdir"])

    def log(msg: str):
        job["logs"].append(msg)

    def prog(v: float):
        job["progress"] = float(v)

    try:
        name = vid_id(url)
        dest = download_file(
            url, fmt, quality, str(workdir), name, prog=prog, log=log, stop=stop
        )
        job["status"] = "done"
        job["dest"] = dest
        job["filename"] = Path(dest).name
        log("✓ ready — your browser will save the file to Downloads")
    except InterruptedError:
        job["status"] = "cancelled"
        log("⚠ cancelled by user")
        _cleanup_job_dir(job)
    except Exception as e:
        job["status"] = "error"
        log(f"✗ {e}")
        _cleanup_job_dir(job)
    finally:
        job["progress"] = 0 if job["status"] != "done" else 100


@app.post("/api/download")
def start_download():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    fmt = data.get("fmt") or "mp3"
    quality = str(data.get("quality") or ("320" if fmt == "mp3" else "1080"))
    if not url:
        return jsonify({"error": "missing url"}), 400

    job_id = uuid.uuid4().hex
    workdir = _TEMP_ROOT / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "logs": [],
        "dest": None,
        "filename": None,
        "workdir": str(workdir),
        "created": time.time(),
        "stop": threading.Event(),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run_download,
        args=(job_id, url, fmt, quality),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.get("/api/download/<job_id>")
def download_status(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    return jsonify(
        {
            "status": job["status"],
            "progress": job["progress"],
            "logs": job["logs"],
            "filename": job.get("filename"),
        }
    )


@app.get("/api/download/<job_id>/file")
def download_file_route(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    dest = job.get("dest")
    if job["status"] != "done" or not dest or not Path(dest).is_file():
        return jsonify({"error": "file not ready"}), 404
    path = Path(dest)
    resp = send_file(
        path,
        as_attachment=True,
        download_name=path.name,
        mimetype="application/octet-stream",
    )

    @resp.call_on_close
    def _after():
        _cleanup_job_dir(job)

    return resp


@app.post("/api/download/<job_id>/stop")
def stop_download(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    job["stop"].set()
    return jsonify({"ok": True})


@app.get("/")
def root():
    return jsonify(
        {
            "service": "X2mate backend",
            "version": APP_VERSION,
            "docs": "Point the Vercel frontend API base at this host.",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    print(f"X2mate backend v{APP_VERSION} on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
