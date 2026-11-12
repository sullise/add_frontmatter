"""Portable title cards, redrawn from scalable font outlines at every size."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from .progress import Progress


@dataclass(frozen=True)
class TitleCard:
    title: str
    date: str
    animate: bool = True
    duration: float = 6.0

    def __post_init__(self):
        if not self.title.strip() or not self.date.strip():
            raise ValueError("Enter both a video title and a date.")
        if len(self.title) > 300 or len(self.date) > 100:
            raise ValueError("Use at most 300 characters for the title and 100 for the date.")
        if not math.isfinite(self.duration) or not 2 <= self.duration <= 30:
            raise ValueError("Title card duration must be between 2 and 30 seconds.")


def _wrap(text: str, font, max_width: int) -> list[str]:
    lines, line = [], ""
    # Break long words as well as ordinary phrases, so nothing clips.
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if font.getlength(candidate) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        for char in word:
            if line and font.getlength(line + char) > max_width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def _layout(card: TitleCard, width: int, height: int):
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_parts = [part.strip() for part in re.split(r"\s+[-–—]\s+|\n+", card.title) if part.strip()]
    max_width = int(width * .84)
    for size in range(max(2, int(height * .20)), 1, -1):
        title_font = ImageFont.load_default(size=size)
        date_font = ImageFont.load_default(size=max(1, round(size * .55)))
        # Prefer one line per dash-separated part. Extra-long parts still
        # wrap rather than shrinking the lettering until it is unreadable.
        if len(title_parts) > 1 and size > max(2, int(height * .06)):
            if any(title_font.getlength(part) > max_width for part in title_parts):
                continue
        title_lines = [line for part in title_parts for line in _wrap(part, title_font, max_width)]
        date_lines = _wrap(card.date, date_font, int(width * .84))
        rows = [(line, size, "white") for line in title_lines]
        rows += [(line, max(1, round(size * .55)), "#d9d9d9") for line in date_lines]
        heights = [draw.textbbox((0, 0), line, font=ImageFont.load_default(size=s))[3] -
                   draw.textbbox((0, 0), line, font=ImageFont.load_default(size=s))[1]
                   for line, s, _ in rows]
        gap = max(2, round(size * .3))
        total = sum(heights) + gap * (len(rows) - 1)
        if total <= height * .76:
            return rows, heights, gap, total
    raise ValueError("Title and date are too long to fit this video's frame.")


def render_title_frame(card: TitleCard, width: int, height: int, seconds: float, layout=None) -> Image.Image:
    rows, heights, gap, total = layout or _layout(card, width, height)
    frame = Image.new("RGB", (width, height), "black")
    fade_seconds = min(3.0, card.duration / 2)
    opacity = max(0.0, min(1.0, seconds / fade_seconds,
                           (card.duration - seconds) / fade_seconds))
    progress = min(1.0, max(0.0, seconds / fade_seconds)) if card.animate else 1.0
    scale = 1 - (1 - progress) ** 3
    if scale == 0 or opacity == 0:
        return frame
    draw = ImageDraw.Draw(frame)
    y = (height - total * scale) / 2
    for (line, size, color), row_height in zip(rows, heights):
        font = ImageFont.load_default(size=max(1, round(size * scale)))
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (right - left)) / 2 - left, y - top), line, font=font, fill=color)
        y += (row_height + gap) * scale
    return ImageEnhance.Brightness(frame).enhance(opacity)


def create_title_video(ffmpeg: str, card: TitleCard, target: dict, tmp_dir: Path,
                       encoder: str, progress: Progress | None = None) -> tuple[Path | None, float, str]:
    width, height = target["width"] or 1920, target["height"] or 1080
    fps = target["fps"] or 30
    count = round(card.duration * fps)
    output = tmp_dir / "title_video_only.mp4"
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", encoder,
               "-crf", "18", "-preset", "medium", "-bf", "2",
               "-pix_fmt", target["pix_fmt"] or "yuv420p"]
    if target["tbn"]:
        command += ["-video_track_timescale", str(target["tbn"])]
    command += [str(output)]
    try:
        if progress:
            progress("Creating title and date", 0.0)
        layout = _layout(card, width, height)
        # stderr goes to a file so encoder diagnostics cannot block the input pipe.
        with tempfile.TemporaryFile() as errors:
            with subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors) as process:
                try:
                    for index in range(count):
                        # End on black as well as starting on black, without
                        # changing the encoded card's six-second duration.
                        seconds = card.duration if index == count - 1 else index / fps
                        frame = render_title_frame(card, width, height, seconds, layout)
                        process.stdin.write(frame.tobytes())
                        if progress and index % max(1, round(fps / 2)) == 0:
                            progress("Creating title and date", (index + 1) / count)
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()
                code = process.wait()
            errors.seek(0)
            error = errors.read().decode("utf-8", errors="replace")
        if code or not output.exists():
            return None, 0.0, error[-800:] or "ffmpeg could not encode the title card"
        if progress:
            progress("Creating title and date", 1.0)
        return output, count / fps, "ok"
    except (OSError, ValueError) as exc:
        return None, 0.0, str(exc)
