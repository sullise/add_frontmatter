"""Video joins and sample-aligned audio for optional closing sequences."""
from __future__ import annotations

from pathlib import Path
from .progress import Progress, run_media


def main_fade_times(duration: float, fade_in: bool, fade_out: bool) -> tuple[float, float]:
    requested = int(fade_in) + int(fade_out)
    length = min(3.0, duration / requested) if requested else 0.0
    return (length if fade_in else 0.0, length if fade_out else 0.0)


def join_picture_tracks(ffmpeg: str, pictures: list[Path], output: Path, listing: Path, duration: float | None = None,
                        progress: Progress | None = None) -> tuple[bool, str]:
    listing.write_text("".join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'\n"
                               for p in pictures), encoding="utf-8")
    result = run_media([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                             "-f", "concat", "-safe", "0", "-i", str(listing),
                             "-map", "0:v:0", "-c:v", "copy", "-an", str(output)],
                            duration, progress, "Joining video segments")
    ok = result.returncode == 0 and output.exists()
    return ok, "ok" if ok else result.stderr[-800:]


def build_sequence_audio(ffmpeg: str, segments: list[tuple[Path | None, float, float, float]],
                         target: dict, tmp_dir: Path, progress: Progress | None = None) -> tuple[Path | None, str]:
    from .core import probe_streams
    infos = [probe_streams(ffmpeg, source) if source is not None else {} for source, *_ in segments]
    if not any(info.get("has_audio") for info in infos):
        return None, "ok"
    rate = target.get("sample_rate") or next(
        (info["sample_rate"] for info in infos if info.get("sample_rate")), 48000)
    channels = target.get("channels") or next(
        (info["channels"] for info in infos if info.get("channels")), 2)
    layout = "mono" if channels == 1 else "stereo" if channels == 2 else f"{channels}c"
    inputs, filters, labels = [], [], []
    input_index = 0
    for index, ((source, duration, fade_in, fade_out), info) in enumerate(zip(segments, infos)):
        if info.get("has_audio"):
            inputs += ["-i", str(source)]
            chain = (f"[{input_index}:a:0]asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0,"
                     f"aformat=sample_rates={rate}:channel_layouts={layout},apad,")
            input_index += 1
        else:
            chain = f"anullsrc=r={rate}:cl={layout},"
        chain += f"atrim=duration={duration:.9f},asetpts=PTS-STARTPTS"
        if fade_in:
            chain += f",afade=t=in:st=0:d={fade_in:.9f}"
        if fade_out:
            chain += f",afade=t=out:st={max(0, duration-fade_out):.9f}:d={fade_out:.9f}"
        label = f"[segment{index}]"
        filters.append(chain + label)
        labels.append(label)
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[outa]")
    output = tmp_dir / "sequence_audio.m4a"
    result = run_media([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *inputs,
                             "-filter_complex", ";".join(filters), "-map", "[outa]",
                             "-c:a", "aac", "-ar", str(rate), "-ac", str(channels), str(output)],
                            sum(segment[1] for segment in segments), progress, "Building audio")
    if result.returncode == 0 and output.exists():
        return output, "ok"
    return None, result.stderr[-800:] or "could not encode sequence audio"
