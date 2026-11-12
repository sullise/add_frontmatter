"""Verify real output ordering, animation, main-video fades and audio timing."""
import math
import struct
import subprocess

import pytest
from PIL import ImageChops

from add_frontmatter.core import get_ffmpeg_path, process_video, probe_streams
from add_frontmatter.title_card import TitleCard, render_title_frame, _layout


def test_text_grows_from_blank_and_stops_inside_frame():
    card = TitleCard("A photographer's title: 50% & more", "November 12, 2026")
    first = render_title_frame(card, 640, 360, 0)
    early = render_title_frame(card, 640, 360, .1)
    held = render_title_frame(card, 640, 360, 3.0)
    assert first.getbbox() is None
    assert early.getbbox()[2] - early.getbbox()[0] < held.getbbox()[2] - held.getbbox()[0]
    assert ImageChops.difference(held, render_title_frame(card, 640, 360, 2)).getbbox() is not None
    assert card.duration == 6.0
    x0, y0, x1, y1 = held.getbbox()
    assert 0 < x0 < x1 < 640 and 0 < y0 < y1 < 360
    fading = render_title_frame(card, 640, 360, 4.5)
    assert fading.getbbox() == held.getbbox()
    assert max(fading.tobytes()) == pytest.approx(127, abs=1)
    assert max(held.tobytes()) == 255
    assert render_title_frame(card, 640, 360, 6).getbbox() is None
    static = TitleCard("Static title", "November 12", animate=False)
    assert max(render_title_frame(static, 640, 360, 1.5).tobytes()) == pytest.approx(127, abs=1)
    assert render_title_frame(static, 640, 360, 0).getbbox() is None
    long = TitleCard("Long title " * 25, "Date " * 15, animate=False)
    assert render_title_frame(long, 180, 320, 3).getbbox() is not None


@pytest.mark.parametrize("audio,bframes,fps,opening_audio", [
    (True, 2, 10, True), (False, 0, 10, False), (True, 0, 29.97, False),
])
def test_title_between_opening_and_main_with_audio_in_sync(tmp_path, audio, bframes, fps, opening_audio):
    ffmpeg = get_ffmpeg_path()
    opening, main = tmp_path / 'opening.mp4', tmp_path / 'main.mp4'
    for output, color, duration in [(opening, 'red', .5), (main, 'blue', 1)]:
        cmd = [ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i',
               f'color={color}:s=320x180:r={fps}:d={duration}']
        if audio and (output == main or opening_audio):
            # The opening audio intentionally ends before its video.
            tone_duration = .2 if output == opening else 1
            cmd += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={tone_duration}',
                    '-c:a', 'aac']
        cmd += ['-c:v', 'libx264', '-bf', str(bframes), '-pix_fmt', 'yuv420p', str(output)]
        subprocess.run(cmd, check=True, capture_output=True)
    card = TitleCard("Camera Club", "November 12, 2026", animate=audio)
    ok, msg = process_video(ffmpeg, opening, main, tmp_path, title_card=card)
    assert ok, msg
    result = tmp_path / 'main_FMAdded.mp4'
    info = probe_streams(ffmpeg, result)
    assert info['duration'] == pytest.approx(7.5, abs=.15)
    assert info['has_audio'] == audio

    def frame(at):
        return subprocess.run([ffmpeg, '-v', 'error', '-i', str(result), '-ss', str(at),
                               '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                              capture_output=True, check=True).stdout
    red = frame(.1)
    blue = frame(6.8)
    assert red[0] > 200 and red[2] < 20
    assert 20 < blue[2] < 150 and blue[0] < 20
    title = frame(3)
    assert title[0:3] == b'\x00\x00\x00'
    assert max(title) > 200
    assert max(frame(4.5)) < max(frame(3.5))
    assert max(frame(6.3)) < 35

    if audio:
        def rms(at):
            data = subprocess.run([ffmpeg, '-v', 'error', '-i', str(result), '-ss', str(at),
                                   '-t', '0.1', '-vn', '-ac', '1', '-ar', '8000',
                                   '-f', 's16le', '-'], capture_output=True, check=True).stdout
            values = struct.unpack('<' + 'h' * (len(data)//2), data)
            return math.sqrt(sum(v*v for v in values) / len(values))
        assert rms(.35) < 15  # short opening audio padded before title
        assert rms(3) < 15    # title is silent
        assert 100 < rms(6.7) < rms(7.2)  # main sound fades in with its picture


def test_blank_title_and_date_rejected():
    with pytest.raises(ValueError):
        TitleCard(' ', 'November 12')
    with pytest.raises(ValueError):
        TitleCard('Title', '')


@pytest.mark.parametrize("dash", [" - ", " – ", " — "])
def test_title_breaks_at_spaced_dash_and_preserves_word_hyphens(dash):
    card = TitleCard("Sean Sullivan" + dash + "This is My Presentation", "November 12, 2026")
    rows, _, _, _ = _layout(card, 1280, 720)
    assert [text for text, _, _ in rows] == [
        "Sean Sullivan", "This is My Presentation", "November 12, 2026"]
    rows, _, _, _ = _layout(TitleCard("Award-winning Photography", "November 12"), 1280, 720)
    assert "Award-winning" in " ".join(text for text, _, _ in rows)
