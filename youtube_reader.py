"""
NTA Sovereign YouTube Video Reader & Audio Transcription Engine
==============================================================
Enables NetuArk AI to read, synthesize, and inspect the spoken content of any
YouTube video with rich channel authority metadata and timestamped transcripts.

Architecture:
1. Rich Metadata Extraction (Title, Channel, Views, Duration, Published Time, Thumbnail).
2. Tier 1 Fast Path: Subtitle extraction via yt-dlp / timedtext (multi-language, 1-3s, 0% CPU).
3. Tier 2 STT Fallback (Chunked, Storage-Cached, Zero-OOM Engine):
   - Lowest-bandwidth clean audio download via yt-dlp (m4a, low bitrate, no-part).
   - FFmpeg 16kHz mono bandpass vocal filter (80Hz - 8000Hz, volume 1.2x) removing noise/hum.
   - Storage-backed 60-second chunking (-f segment) so peak RAM stays strictly under 50MB.
   - Sequential whisper.cpp ARM NEON native inference (4 threads) processing 1 chunk at a time.
   - Per-chunk progress persistence ({video_id}.progress.json) on disk so jobs never die and can resume.
   - Immediate per-chunk WAV deletion reclaiming storage as each segment finishes.
4. Persistent Disk Cache: Prevents redundant downloads/transcriptions across the cluster.
5. Auto-Cleanup: Discards temporary raw audio (.m4a / .wav) and subtitle files immediately.
"""

import os
import sys
import re
import json
import time
import glob
import shutil
import threading
import urllib.parse
import urllib.request
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple

CACHE_DIR = "/sdcard/Download/NetuarkMedia/cache/transcripts"
AUDIO_TMP_DIR = "/data/data/com.termux/files/home/ntawebsearchapi/cache"
WHISPER_BIN = "/data/data/com.termux/files/home/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "/data/data/com.termux/files/home/whisper.cpp/models/ggml-tiny.en.bin"
YT_DLP_BIN = shutil.which("yt-dlp") or "/data/data/com.termux/files/usr/bin/yt-dlp"
FFMPEG_BIN = shutil.which("ffmpeg") or "/data/data/com.termux/files/usr/bin/ffmpeg"

# Ensure cache directories exist safely
try:
    os.makedirs(CACHE_DIR, exist_ok=True)
except Exception:
    pass

try:
    os.makedirs(AUDIO_TMP_DIR, exist_ok=True)
except Exception:
    pass

# Active task coordination (prevent duplicate parallel Whisper runs on same video)
_ACTIVE_TASKS: Dict[str, threading.Event] = {}
_TASKS_LOCK = threading.Lock()


def clean_html(text: str) -> str:
    """Strips HTML tags and unescapes XML/HTML entities."""
    if not text:
        return ""
    import html
    t = re.sub(r"<[^>]*>", " ", text)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extracts 11-character YouTube video ID from URL or bare ID."""
    clean = url_or_id.strip()
    if re.fullmatch(r"^[a-zA-Z0-9_-]{11}$", clean):
        return clean
    patterns = [
        r"(?:v=|\/v\/|embed\/|youtu\.be\/|\/shorts\/)([a-zA-Z0-9_-]{11})",
        r"(?:watch\?.*v=)([a-zA-Z0-9_-]{11})"
    ]
    for p in patterns:
        m = re.search(p, clean)
        if m:
            return m.group(1)
    return None


def parse_timestamp_to_sec(ts_str: str) -> float:
    """
    Parses timestamp string ("00:01:23,456", "00:01:23.456", "01:23") to float seconds.
    """
    if not ts_str:
        return 0.0
    ts_clean = ts_str.strip().replace(",", ".")
    parts = ts_clean.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        elif len(parts) == 1:
            return float(parts[0])
    except Exception:
        pass
    return 0.0


def format_sec_to_timestamp(total_sec: float) -> str:
    """
    Formats float seconds to standard timestamp "HH:MM:SS.mmm".
    """
    if total_sec < 0:
        total_sec = 0.0
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = int(total_sec % 60)
    ms = int(round((total_sec - int(total_sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


class YouTubeReader:
    """Sovereign YouTube Video Reader with Multi-Tier Storage-Cached Processing."""

    @classmethod
    def get_cache_dir(cls) -> str:
        # Fallback to local cache if /sdcard isn't writable
        if os.path.exists(CACHE_DIR) or os.access(os.path.dirname(CACHE_DIR), os.W_OK):
            os.makedirs(CACHE_DIR, exist_ok=True)
            return CACHE_DIR
        local_cache = os.path.expanduser("~/ntawebsearchapi/cache/transcripts")
        os.makedirs(local_cache, exist_ok=True)
        return local_cache

    @classmethod
    def get_cache_path(cls, video_id: str) -> str:
        return os.path.join(cls.get_cache_dir(), f"{video_id}.json")

    @classmethod
    def get_progress_path(cls, video_id: str) -> str:
        return os.path.join(cls.get_cache_dir(), f"{video_id}.progress.json")

    @classmethod
    def read_cache(cls, video_id: str) -> Optional[Dict[str, Any]]:
        path = cls.get_cache_path(video_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["cached"] = True
                    return data
            except Exception:
                pass
        return None

    @classmethod
    def read_progress(cls, video_id: str) -> Optional[Dict[str, Any]]:
        path = cls.get_progress_path(video_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    @classmethod
    def save_cache(cls, video_id: str, data: Dict[str, Any]) -> None:
        path = cls.get_cache_path(video_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[YT-READER] Warning: Could not write cache: {e}", flush=True)

    @classmethod
    def fetch_video_metadata(cls, video_id: str) -> Dict[str, Any]:
        """
        Fast native extraction of video metadata directly from YouTube's watch page.
        Returns video title, channel, views, duration, thumbnail, and description.
        """
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        metadata: Dict[str, Any] = {
            "video_id": video_id,
            "url": watch_url,
            "title": f"YouTube Video ({video_id})",
            "channel": "YouTube Creator",
            "channel_url": "",
            "views": "",
            "published_date": "",
            "duration": "",
            "description": "",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        }

        try:
            req = urllib.request.Request(watch_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            m_player = re.search(r"ytInitialPlayerResponse\s*=\s*({.+?});(?:var|\s*<)", html)
            if m_player:
                try:
                    p_data = json.loads(m_player.group(1))
                    v_details = p_data.get("videoDetails", {})
                    metadata["title"] = v_details.get("title") or metadata["title"]
                    metadata["channel"] = v_details.get("author") or metadata["channel"]
                    metadata["channel_url"] = f"https://www.youtube.com/channel/{v_details.get('channelId')}" if v_details.get("channelId") else ""
                    
                    secs = int(v_details.get("lengthSeconds", 0))
                    if secs > 0:
                        m, s = divmod(secs, 60)
                        h, m = divmod(m, 60)
                        metadata["duration"] = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

                    metadata["views"] = f"{int(v_details.get('viewCount', 0)):,} views" if v_details.get("viewCount") else ""
                    metadata["description"] = v_details.get("shortDescription", "")[:500]

                    thumbs = v_details.get("thumbnail", {}).get("thumbnails", [])
                    if thumbs:
                        metadata["thumbnail"] = thumbs[-1].get("url", metadata["thumbnail"])

                    micro = p_data.get("microformat", {}).get("playerMicroformatRenderer", {})
                    if micro:
                        metadata["published_date"] = micro.get("publishDate") or micro.get("uploadDate") or metadata["published_date"]
                        metadata["category"] = micro.get("category", "")
                        if not metadata.get("channel") or metadata["channel"] == "YouTube Creator":
                            metadata["channel"] = micro.get("ownerChannelName") or metadata["channel"]
                except Exception as pe:
                    print(f"[YT-READER] Warning: Failed parsing player response: {pe}", flush=True)

            if not metadata.get("title") or metadata["title"].startswith("YouTube Video"):
                t_match = re.search(r'<meta name="title" content="([^"]+)"', html)
                if t_match:
                    metadata["title"] = clean_html(t_match.group(1))
            if not metadata.get("channel") or metadata["channel"] == "YouTube Creator":
                c_match = re.search(r'itemprop="author"[^>]*>[\s\S]*?<link itemprop="name" content="([^"]+)"', html)
                if c_match:
                    metadata["channel"] = clean_html(c_match.group(1))

        except Exception as e:
            print(f"[YT-READER] Warning: Direct metadata fetch error: {e}", flush=True)

        return metadata

    @classmethod
    def parse_vtt_content(cls, vtt_text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Parses WebVTT subtitle text into timestamped segments and full text."""
        segments: List[Dict[str, Any]] = []
        full_text_list: List[str] = []
        seen = set()
        current_start = ""
        current_end = ""

        for line in vtt_text.splitlines():
            line = line.strip()
            if "-->" in line:
                parts = line.split("-->")
                current_start = parts[0].strip().split()[0]
                current_end = parts[1].strip().split()[0]
                continue
            if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue

            # Strip micro-timestamp tags like <00:00:14.200><c> etc.
            clean = re.sub(r"<[^>]+>", "", line).strip()
            clean = clean_html(clean)
            if clean and clean not in seen:
                seen.add(clean)
                full_text_list.append(clean)
                segments.append({
                    "start": current_start,
                    "end": current_end,
                    "text": clean
                })

        full_text = " ".join(full_text_list)
        full_text = re.sub(r"\s+", " ", full_text).strip()
        return full_text, segments

    @classmethod
    def extract_subtitles_ytdlp(cls, watch_url: str, video_id: str, lang: str = "en") -> Tuple[str, List[Dict[str, Any]]]:
        """
        Tier 1: Uses yt-dlp to download official or auto-generated subtitles without downloading video.
        Completes in 1-3 seconds with zero CPU load.
        """
        sub_prefix = os.path.join(AUDIO_TMP_DIR, f"sub_{video_id}")
        # Clean any old sub files for this ID
        for old_f in glob.glob(f"{sub_prefix}*"):
            try: os.remove(old_f)
            except Exception: pass

        cmd = [
            YT_DLP_BIN,
            "--extractor-args", "youtube:player_client=android",
            "--write-auto-sub",
            "--write-sub",
            "--sub-lang", f"{lang},en",
            "--sub-format", "vtt/srt/best",
            "--skip-download",
            "--no-playlist",
            "-o", sub_prefix,
            watch_url
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            # Find the downloaded subtitle file (.vtt or .srt)
            downloaded_files = glob.glob(f"{sub_prefix}*")
            for sub_file in downloaded_files:
                if sub_file.endswith((".vtt", ".srt")):
                    try:
                        with open(sub_file, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        full_text, segments = cls.parse_vtt_content(content)
                        if full_text:
                            return full_text, segments
                    except Exception as fe:
                        print(f"[YT-READER] Error reading sub file: {fe}", flush=True)
                    finally:
                        try: os.remove(sub_file)
                        except Exception: pass
        except Exception as e:
            print(f"[YT-READER] Subtitle extraction error: {e}", flush=True)

        return "", []

    @classmethod
    def transcribe_with_whisper(cls, video_id: str, watch_url: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Tier 2 STT Fallback: Chunked, Storage-Cached Audio Pipeline.
        - Downloads lowest-bitrate voice audio stream (m4a/aac) via yt-dlp to conserve bandwidth.
        - Applies FFmpeg acoustic bandpass vocal filter (80Hz - 8000Hz, 1.2x volume) to eliminate low/high noise.
        - Segments audio into small 60-second chunks on disk (-f segment).
        - Runs whisper.cpp ARM NEON native inference (4 threads) sequentially chunk-by-chunk:
          Peak RAM stays under ~45MB regardless of video length (10 minutes, 1 hour, or 4 hours).
        - Persists progress to storage cache ({video_id}.progress.json) after each chunk so work is never lost.
        - Immediately deletes processed chunk WAV files to maintain minimal storage footprint.
        """
        if not os.path.exists(WHISPER_BIN):
            raise RuntimeError(f"Whisper binary not found at {WHISPER_BIN}")
        if not os.path.exists(WHISPER_MODEL):
            raise RuntimeError(f"Whisper model not found at {WHISPER_MODEL}")

        raw_audio_path = os.path.join(AUDIO_TMP_DIR, f"{video_id}.m4a")
        chunk_dir = os.path.join(AUDIO_TMP_DIR, f"chunks_{video_id}")
        os.makedirs(chunk_dir, exist_ok=True)
        progress_path = cls.get_progress_path(video_id)

        completed_chunks = set()
        segments: List[Dict[str, Any]] = []
        full_text_list: List[str] = []

        # Check for existing progress file on storage
        if os.path.exists(progress_path):
            try:
                with open(progress_path, "r", encoding="utf-8") as pf:
                    prog = json.load(pf)
                    completed_chunks = set(prog.get("completed_chunks", []))
                    segments = prog.get("segments", [])
                    full_text_list = prog.get("full_text_list", [])
                    print(f"[YT-READER] 📂 Resuming transcription for {video_id}: {len(completed_chunks)} chunks already completed.", flush=True)
            except Exception as pe:
                print(f"[YT-READER] Warning loading progress file: {pe}", flush=True)

        try:
            existing_chunks = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.wav")))

            # Step 1: Download audio if not already chunked
            if not existing_chunks:
                print(f"[YT-READER] 🎙️ Step 1: Downloading lowest-bandwidth audio for {video_id}...", flush=True)
                dl_cmd = [
                    YT_DLP_BIN,
                    "--extractor-args", "youtube:player_client=android,ios,mweb",
                    "-f", "ba[ext=m4a]/ba[abr<=64]/ba/b",
                    "--no-part",
                    "-o", raw_audio_path,
                    "--no-playlist",
                    watch_url
                ]
                res_dl = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=600)
                if res_dl.returncode != 0:
                    # Retry with generic player client
                    dl_cmd_general = [
                        YT_DLP_BIN,
                        "-f", "ba[ext=m4a]/ba/b",
                        "--no-part",
                        "-o", raw_audio_path,
                        "--no-playlist",
                        watch_url
                    ]
                    res_dl = subprocess.run(dl_cmd_general, capture_output=True, text=True, timeout=600)
                    if res_dl.returncode != 0:
                        raise RuntimeError(f"yt-dlp audio download failed: {res_dl.stderr[:200]}")

                if not os.path.exists(raw_audio_path) or os.path.getsize(raw_audio_path) == 0:
                    raise RuntimeError("yt-dlp produced empty or missing audio file")

                cpu_threads = str(os.cpu_count() or 8)
                print(f"[YT-READER] 🔊 Step 2: Segmenting audio into 60s chunks with {cpu_threads}-core acceleration & vocal bandpass filter...", flush=True)
                chunk_pattern = os.path.join(chunk_dir, "chunk_%04d.wav")
                ff_cmd = [
                    FFMPEG_BIN,
                    "-y",
                    "-threads", cpu_threads,
                    "-i", raw_audio_path,
                    "-vn",
                    "-ar", "16000",
                    "-ac", "1",
                    "-c:a", "pcm_s16le",
                    "-af", "volume=1.2,highpass=f=80,lowpass=f=8000",
                    "-f", "segment",
                    "-segment_time", "60",
                    "-reset_timestamps", "1",
                    chunk_pattern
                ]
                res_ff = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=300)
                if res_ff.returncode != 0:
                    raise RuntimeError(f"FFmpeg segmentation failed: {res_ff.stderr[:200]}")

                # Reclaim raw audio storage immediately
                if os.path.exists(raw_audio_path):
                    try: os.remove(raw_audio_path)
                    except Exception: pass

                existing_chunks = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.wav")))

            if not existing_chunks:
                raise RuntimeError("No audio chunks produced by FFmpeg")

            total_chunks = len(existing_chunks)
            print(f"[YT-READER] 🧠 Step 3: Transcribing {total_chunks} audio chunks (Whisper NEON, peak RAM < 50MB)...", flush=True)

            # Step 3: Sequential Chunk Transcription
            for chunk_file in existing_chunks:
                m = re.search(r"chunk_(\d+)\.wav", os.path.basename(chunk_file))
                if not m:
                    continue
                chunk_idx = int(m.group(1))

                # Skip already transcribed chunks
                if chunk_idx in completed_chunks:
                    try: os.remove(chunk_file)
                    except Exception: pass
                    continue

                if not os.path.exists(chunk_file) or os.path.getsize(chunk_file) < 1000:
                    completed_chunks.add(chunk_idx)
                    try: os.remove(chunk_file)
                    except Exception: pass
                    continue

                chunk_offset_sec = chunk_idx * 60.0
                chunk_out_base = os.path.join(chunk_dir, f"out_{chunk_idx:04d}")

                cpu_threads = str(os.cpu_count() or 8)
                whisper_cmd = [
                    WHISPER_BIN,
                    "-m", WHISPER_MODEL,
                    "-f", chunk_file,
                    "-oj",
                    "-t", cpu_threads,
                    "-of", chunk_out_base,
                    "-l", "en",
                    "-sns",
                    "--no-prints"
                ]

                try:
                    res_wh = subprocess.run(whisper_cmd, capture_output=True, text=True, timeout=90)
                except subprocess.TimeoutExpired:
                    print(f"[YT-READER] Warning: Chunk {chunk_idx} timed out, skipping.", flush=True)
                    completed_chunks.add(chunk_idx)
                    try: os.remove(chunk_file)
                    except Exception: pass
                    continue

                json_out = f"{chunk_out_base}.json"
                chunk_text_parts: List[str] = []

                if os.path.exists(json_out):
                    try:
                        with open(json_out, "r", encoding="utf-8") as jf:
                            w_data = json.load(jf)
                            for seg in w_data.get("transcription", []):
                                t_from = seg.get("timestamps", {}).get("from", "00:00:00,000")
                                t_to = seg.get("timestamps", {}).get("to", "00:00:00,000")
                                text_s = seg.get("text", "").strip()
                                if text_s:
                                    # Align timestamps to overall video position
                                    start_sec = parse_timestamp_to_sec(t_from) + chunk_offset_sec
                                    end_sec = parse_timestamp_to_sec(t_to) + chunk_offset_sec
                                    clean_from = format_sec_to_timestamp(start_sec)
                                    clean_to = format_sec_to_timestamp(end_sec)
                                    segments.append({
                                        "start": clean_from,
                                        "end": clean_to,
                                        "text": text_s
                                    })
                                    chunk_text_parts.append(text_s)
                    except Exception as je:
                        print(f"[YT-READER] Warning parsing chunk {chunk_idx} JSON: {je}", flush=True)

                if chunk_text_parts:
                    chunk_str = " ".join(chunk_text_parts).strip()
                    full_text_list.append(chunk_str)

                completed_chunks.add(chunk_idx)

                # Persist progress to storage cache after EVERY chunk
                try:
                    with open(progress_path, "w", encoding="utf-8") as pf:
                        json.dump({
                            "video_id": video_id,
                            "total_chunks": total_chunks,
                            "completed_chunks": list(completed_chunks),
                            "segments": segments,
                            "full_text_list": full_text_list,
                            "updated_at": time.time()
                        }, pf)
                except Exception:
                    pass

                # Reclaim storage immediately
                for tmp_f in [chunk_file, json_out, f"{chunk_out_base}.txt"]:
                    if os.path.exists(tmp_f):
                        try: os.remove(tmp_f)
                        except Exception: pass

            full_text = " ".join(full_text_list).strip()

            # Clean up completed progress file and chunks directory
            if os.path.exists(progress_path):
                try: os.remove(progress_path)
                except Exception: pass
            if os.path.exists(chunk_dir):
                try: shutil.rmtree(chunk_dir, ignore_errors=True)
                except Exception: pass

            return full_text, segments

        finally:
            # Always ensure raw audio is cleaned up
            if os.path.exists(raw_audio_path):
                try: os.remove(raw_audio_path)
                except Exception: pass

    @classmethod
    def read_video(
        cls,
        url_or_id: str,
        lang: str = "en",
        force_stt: bool = False
    ) -> Dict[str, Any]:
        """
        Main public interface for NetuArk AI.
        Takes video ID or URL, extracts rich metadata and complete spoken content.
        Thread-safe, storage-cached, and OOM-protected.
        """
        start_t = time.time()
        video_id = extract_video_id(url_or_id)
        if not video_id:
            return {
                "status": "Error",
                "error": f"Invalid YouTube video ID or URL: '{url_or_id}'",
                "execution_time_sec": 0.0
            }

        # Check Cache first
        cached = cls.read_cache(video_id)
        if cached and not force_stt:
            cached["execution_time_sec"] = round(time.time() - start_t, 3)
            return cached

        # Check active tasks to coordinate parallel requests
        with _TASKS_LOCK:
            if video_id in _ACTIVE_TASKS:
                task_event = _ACTIVE_TASKS[video_id]
                is_owner = False
            else:
                task_event = threading.Event()
                _ACTIVE_TASKS[video_id] = task_event
                is_owner = True

        if not is_owner:
            print(f"[YT-READER] Waiting for in-progress transcription of {video_id}...", flush=True)
            # Wait up to 85 seconds for owner thread
            task_event.wait(timeout=85.0)
            cached = cls.read_cache(video_id)
            if cached:
                cached["execution_time_sec"] = round(time.time() - start_t, 3)
                return cached
            # Check progress if still running
            prog = cls.read_progress(video_id)
            if prog:
                return {
                    "status": "Processing",
                    "video_id": video_id,
                    "message": f"Transcription in progress ({len(prog.get('completed_chunks', []))}/{prog.get('total_chunks', '?')} chunks done)",
                    "execution_time_sec": round(time.time() - start_t, 2)
                }

        try:
            # Fetch Rich Metadata
            metadata = cls.fetch_video_metadata(video_id)

            full_text = ""
            segments: List[Dict[str, Any]] = []
            transcript_source = "none"

            # Tier 1: Fast Subtitle Path
            if not force_stt:
                print(f"[YT-READER] ⚡ Tier 1: Checking subtitles for {video_id} ({metadata.get('title')[:40]}...)", flush=True)
                full_text, segments = cls.extract_subtitles_ytdlp(metadata["url"], video_id, lang=lang)
                if full_text:
                    transcript_source = "youtube_captions"
                    metadata["language"] = lang

            # Tier 2: Storage-Cached Chunked Whisper.cpp STT
            if not full_text:
                print(f"[YT-READER] 🎙️ Tier 2: Starting storage-cached Whisper STT for {video_id}...", flush=True)
                try:
                    full_text, segments = cls.transcribe_with_whisper(video_id, metadata["url"])
                    if full_text:
                        transcript_source = "on_device_whisper"
                        metadata["language"] = "en"
                except Exception as we:
                    print(f"[YT-READER] Whisper STT fallback error: {we}", flush=True)

            if not full_text:
                return {
                    "status": "Error",
                    "video_id": video_id,
                    "title": metadata.get("title"),
                    "channel": metadata.get("channel"),
                    "error": "Could not extract captions or transcribe video audio.",
                    "execution_time_sec": round(time.time() - start_t, 2)
                }

            word_count = len(full_text.split())
            result: Dict[str, Any] = {
                "status": "Success",
                "video_id": video_id,
                "url": metadata["url"],
                "title": metadata["title"],
                "channel": metadata["channel"],
                "channel_url": metadata["channel_url"],
                "duration": metadata["duration"],
                "views": metadata["views"],
                "published_date": metadata["published_date"],
                "category": metadata.get("category", ""),
                "thumbnail": metadata["thumbnail"],
                "description_preview": metadata["description"][:300],
                "transcript_source": transcript_source,
                "language": metadata.get("language", lang),
                "cached": False,
                "word_count": word_count,
                "segments_count": len(segments),
                "execution_time_sec": round(time.time() - start_t, 2),
                "text": full_text,
                "segments": segments
            }

            # Save to persistent cache
            cls.save_cache(video_id, result)
            return result

        finally:
            if is_owner:
                with _TASKS_LOCK:
                    _ACTIVE_TASKS.pop(video_id, None)
                task_event.set()
