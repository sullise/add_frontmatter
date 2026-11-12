"""Check real encoder updates and failure reporting without opening a window."""
import queue
from types import SimpleNamespace

from add_frontmatter.core import get_ffmpeg_path
from add_frontmatter.progress import run_media


def test_live_progress_before_encoder_finishes():
    updates = []
    result = run_media([get_ffmpeg_path(), '-v', 'error', '-re', '-f', 'lavfi', '-i',
                        'color=blue:s=160x90:r=12:d=2', '-f', 'null', '-'], duration=2,
                       progress=lambda stage, value: updates.append((stage, value)), stage='Test encode')
    assert result.returncode == 0, result.stderr
    fractions = [value for _, value in updates]
    assert fractions[0] == 0
    assert any(0 < value < .9 for value in fractions)
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1
    assert 'frame=24' in result.stdout


def test_encoder_failure_does_not_report_success(tmp_path):
    updates = []
    result = run_media([get_ffmpeg_path(), '-v', 'error', '-i', str(tmp_path/'missing.mp4'),
                        '-f', 'null', '-'], duration=2,
                       progress=lambda stage, value: updates.append(value))
    assert result.returncode != 0
    assert result.stderr
    assert 1.0 not in updates


def test_background_exception_always_reports_failure_and_finishes():
    from add_frontmatter.gui import FrontmatterGUI
    def fail(*args):
        raise OSError('Test disk failure')
    fake = SimpleNamespace(result_queue=queue.Queue(), _process_files=fail)
    FrontmatterGUI._worker(fake)
    error = fake.result_queue.get_nowait()
    done = fake.result_queue.get_nowait()
    assert error == ('__ERROR__', 'Test disk failure', False)
    assert done == ('__DONE__', '', True)
