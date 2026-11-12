"""Decode real output to check bookend order and synchronized fades."""
import math
from pathlib import Path
import struct
import subprocess

import pytest

from add_frontmatter.core import get_ffmpeg_path, process_video, probe_streams
from add_frontmatter.sequence import main_fade_times
from add_frontmatter.title_card import TitleCard


def _clip(ffmpeg, path, color, duration, audio, size='320x180'):
    args = [ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i',
            f'color={color}:s={size}:r=12:d={duration}']
    if audio:
        args += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={duration}', '-c:a', 'aac']
    args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)]
    subprocess.run(args, check=True, capture_output=True)


def _pixel(ffmpeg, path, seconds):
    data = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-ss', str(seconds),
                           '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                          check=True, capture_output=True).stdout
    middle = (90 * 320 + 160) * 3
    return data[middle:middle + 3]


def _rms(ffmpeg, path, seconds):
    data = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-ss', str(seconds),
                           '-t', '0.1', '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                          check=True, capture_output=True).stdout
    values = struct.unpack('<' + 'h' * (len(data)//2), data)
    return math.sqrt(sum(v*v for v in values) / len(values))


@pytest.mark.parametrize('closing_enabled,main_audio,closing_audio', [
    (True, True, True), (False, True, False), (True, False, True), (True, False, False),
])
def test_main_fades_and_optional_closing(tmp_path, closing_enabled, main_audio, closing_audio):
    ffmpeg = get_ffmpeg_path()
    opening, main, closing = (tmp_path / name for name in ['opening.mp4', 'main.mp4', 'closing.mp4'])
    _clip(ffmpeg, opening, 'red', 1, False)
    _clip(ffmpeg, main, 'blue', 8, main_audio)
    # Different aspect ratio exercises conformance and padding of the closing.
    _clip(ffmpeg, closing, 'lime', 1, closing_audio, '160x160')
    updates = []
    ok, msg = process_video(ffmpeg, opening, main, tmp_path,
                            title_card=TitleCard('Sean Sullivan - Presentation', 'November 12'),
                            closing=closing if closing_enabled else None,
                            progress=lambda stage, fraction: updates.append((stage, fraction)))
    assert ok, msg
    stages = {stage for stage, _ in updates}
    assert {'Preparing opening', 'Creating title and date', 'Building main video',
            'Joining video segments', 'Saving final video'} <= stages
    assert all(fraction is None or 0 <= fraction <= 1 for _, fraction in updates)
    assert updates[-1] == ('Saving final video', 1.0)
    output = tmp_path / 'main_FMAdded.mp4'
    info = probe_streams(ffmpeg, output)
    assert info['duration'] == pytest.approx(16 if closing_enabled else 15, abs=.1)
    assert info['has_audio'] == (main_audio or (closing_enabled and closing_audio))
    assert (info['width'], info['height'], info['fps']) == (320, 180, 12)
    assert _pixel(ffmpeg, output, .5)[0] > 230
    assert max(_pixel(ffmpeg, output, 7)) < 10  # main starts black
    assert 5 < _pixel(ffmpeg, output, 7.5)[2] < 80
    assert _pixel(ffmpeg, output, 10.5)[2] > 230
    if closing_enabled:
        assert _pixel(ffmpeg, output, 14.5)[2] < 80
        assert _pixel(ffmpeg, output, 15.5)[1] > 230
    else:
        assert _pixel(ffmpeg, output, 14.5)[2] > 230
    if main_audio:
        steady = _rms(ffmpeg, output, 10.5)
        assert steady > 1000
        assert _rms(ffmpeg, output, 7.2) < steady * .15
        if closing_enabled:
            assert _rms(ffmpeg, output, 14.7) < steady * .15
    elif closing_audio:
        assert _rms(ffmpeg, output, 10.5) < 15
    if closing_enabled and closing_audio:
        assert _rms(ffmpeg, output, 15.2) > 1000


def test_short_clip_fades_do_not_overlap():
    assert main_fade_times(2, True, True) == (1, 1)
    assert main_fade_times(8, True, True) == (3, 3)
    assert main_fade_times(8, True, False) == (3, 0)


def test_closing_settings_survive_other_settings_updates(tmp_path, monkeypatch):
    from add_frontmatter import config
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.json')
    config.save_config('target', 'opening.mp4', None, closing='closing.mp4', use_closing=True)
    config.save_config('target', 'opening.mp4', 'output')
    assert config.load_config()['closing'] == 'closing.mp4'
    assert config.load_config()['use_closing'] is True
    config.save_config('target', 'opening.mp4', 'output', use_closing=False)
    assert config.load_config()['closing'] == 'closing.mp4'
    assert config.load_config()['use_closing'] is False
