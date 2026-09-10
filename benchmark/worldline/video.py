"""Resumable OpenRouter video jobs and reproducible ffmpeg media evidence."""

import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = "https://openrouter.ai/api/v1"


class OpenRouterHTTPError(RuntimeError):
    def __init__(self, status, message, reason=None, retry_after=None):
        super().__init__("OpenRouter HTTP {}: {}".format(status, message))
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_hash(path):
    with Path(path).open("rb") as handle:
        result = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class VideoClient:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        self.api_key = api_key

    def request(self, endpoint, body=None, timeout=120):
        request = Request(API + endpoint,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json", "X-Title": "WorldLine Evaluation"},
            method="GET" if body is None else "POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            message = error.read().decode(errors="replace")[:1500].replace(self.api_key, "[REDACTED]")
            try:
                detail = json.loads(message).get("error", {})
                metadata = detail.get("metadata") or {}
                reason = metadata.get("reason")
                retry_after = error.headers.get("Retry-After") or (metadata.get("headers") or {}).get("Retry-After")
                retry_after = max(0, min(300, int(retry_after))) if retry_after else None
                message = json.dumps(detail, ensure_ascii=False)
            except (ValueError, TypeError, AttributeError):
                reason, retry_after = None, None
            raise OpenRouterHTTPError(error.code, message, reason, retry_after) from error

    def download(self, job_id, path):
        # Do not forward the authorization header to redirected CDN hosts.
        from urllib.request import HTTPRedirectHandler, build_opener
        class SafeRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
                if redirected:
                    redirected.remove_header("Authorization")
                return redirected
        from urllib.parse import quote
        request = Request(API + "/videos/" + quote(job_id, safe="") + "/content",
                          headers={"Authorization": "Bearer " + self.api_key})
        path = Path(path)
        temporary = path.with_suffix(".part")
        with build_opener(SafeRedirect()).open(request, timeout=300) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if temporary.stat().st_size < 1024:
            raise ValueError("Video download is empty or not a media file")
        media_info(temporary)
        temporary.replace(path)


def rejected_submission(job):
    """A definitive HTTP rejection is distinct from a timeout after accepting work."""
    if job.get("id"):
        return False
    # Recognize older conservatively marked records without overwriting their history.
    return job.get("status") == "rejected" or any(
        "OpenRouter HTTP {}:".format(code) in job.get("error", "") for code in (400, 401, 402, 403, 404, 422, 429))


def generate_video(client, directory, parameters, poll_seconds=20, max_wait=3600, retry_rejected=False):
    """Never automatically repeat a paid POST, including ambiguous submission failures."""
    directory = Path(directory)
    request_path, job_path = directory / "generation.request.json", directory / "generation.job.json"
    video_path = directory / "video.mp4"
    if request_path.exists() and read_json(request_path) != parameters:
        raise ValueError("Frozen generation parameters differ; use a new run directory")
    if not request_path.exists():
        write_json(request_path, parameters)
    job = read_json(job_path) if job_path.exists() else None
    if job and retry_rejected and rejected_submission(job):
        number = len(list(directory.glob("generation.rejected-*.json"))) + 1
        write_json(directory / ("generation.rejected-{:03d}.json".format(number)), job)
        job = None
    if job:
        if not job.get("id"):
            if rejected_submission(job):
                raise RuntimeError("Submission rejected (no job created); after resolving API access/credits use --retry-rejected")
            raise RuntimeError("Submission outcome uncertain; inspect generation.job.json before any resubmission")
    else:
        write_json(job_path, {"status": "submitting", "started_at": now()})
        try:
            job = client.request("/videos", parameters)
            if not job.get("id"):
                raise RuntimeError("Video API returned no job ID")
            write_json(job_path, job)
            print(directory.name + " submitted: " + job["id"], flush=True)
        except Exception as error:
            rejected = isinstance(error, OpenRouterHTTPError) and error.status in {400, 401, 402, 403, 404, 422, 429}
            write_json(job_path, {"status": "rejected" if rejected else "submission_uncertain",
                "http_status": error.status if isinstance(error, OpenRouterHTTPError) else None,
                "error": str(error), "updated_at": now()})
            raise
    started = time.monotonic()
    while job.get("status") not in {"completed", "failed", "cancelled"}:
        if time.monotonic() - started > max_wait:
            raise TimeoutError("Video still pending; rerun resumes the existing job without a new charge")
        try:
            from urllib.parse import quote
            job = client.request("/videos/" + quote(job["id"], safe=""))
            write_json(job_path, job)
        except Exception as error:
            write_json(directory / "generation.poll_error.json", {"error": str(error), "at": now()})
        if job.get("status") not in {"completed", "failed", "cancelled"}:
            time.sleep(poll_seconds)
    if job.get("status") != "completed":
        raise RuntimeError("Video generation failed: " + str(job.get("error", job.get("status"))))
    if not video_path.exists():
        client.download(job["id"], video_path)
    info = media_info(video_path)
    write_json(directory / "video.metadata.json", {**info, "sha256": file_hash(video_path), "job_id": job["id"]})
    print(directory.name + " video ready", flush=True)
    return video_path


def media_info(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True)
    info = json.loads(result.stdout)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"duration": float(info["format"]["duration"]), "width": stream["width"],
            "height": stream["height"], "frame_rate": stream["r_frame_rate"]}


def extract_frame(video, seconds, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-ss", "{:.6f}".format(seconds), "-i", str(video),
                        "-frames:v", "1", "-q:v", "2", "-threads", "1", str(output)], check=True, capture_output=True)
    if not output.exists():
        raise ValueError("No frame at timestamp {}".format(seconds))
    return {"path": str(output.resolve()), "time": round(seconds, 6), "sha256": file_hash(output)}


def contact_sheet(frames, output, columns=4):
    """Evidence thumbnail montage, not synthetic imagery or image editing."""
    from PIL import Image, ImageDraw
    width, height = 320, 205
    sheet = Image.new("RGB", (width * columns, height * ((len(frames) + columns - 1) // columns)), "#111827")
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        with Image.open(frame["path"]) as picture:
            picture.thumbnail((width, 180))
            x, y = (index % columns) * width, (index // columns) * height
            sheet.paste(picture, (x, y))
            draw.text((x + 6, y + 183), "{} | {:.3f}s".format(frame.get("label", "frame"), frame["time"]), fill="white")
    sheet.save(output)


def prepare_overview(directory):
    """Local-only media preparation. No judge, upload, or automatic score."""
    directory = Path(directory)
    video = directory / "video.mp4"
    duration = media_info(video)["duration"]
    frames = []
    for index in range(int(duration * 2)):
        second = (index + 0.5) / 2
        frame = extract_frame(video, second, directory / "overview" / ("{:03d}.jpg".format(index)))
        frames.append({**frame, "label": "overview"})
    write_json(directory / "overview.frames.json", frames)
    contact_sheet(frames, directory / "overview.jpg")
    return frames


def detect_cuts(video, threshold=0.30):
    """Physical hard-cut candidates in stream time; no world-state information."""
    result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf",
        "select='gt(scene,{:.2f})',showinfo".format(threshold), "-an", "-f", "null", "-"],
        check=True, capture_output=True, text=True)
    duration = media_info(video)["duration"]
    candidates = sorted(set(float(t) for t in re.findall(r"pts_time:([0-9.]+)", result.stderr)))
    cuts = [t for t in candidates if 0.15 < t < duration - 0.15]
    bounds = [0.0] + cuts + [duration]
    return {"method": "ffmpeg_scene_difference", "threshold": threshold, "duration": duration,
            "cut_times": cuts, "segments": [{"index": i + 1, "start": start, "end": end}
                for i, (start, end) in enumerate(zip(bounds, bounds[1:]))]}
