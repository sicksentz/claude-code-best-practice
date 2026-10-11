"""Tests for the file-handling pipeline. Demucs is replaced with a fake separator."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stem_stripper as ss  # noqa: E402


def fake_separator(src, work_dir, model, device):
    out = work_dir / model / "other.wav"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"OTHER:" + src.read_bytes())
    return out


def failing_separator(src, work_dir, model, device):
    raise RuntimeError("boom")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.incoming, self.output, self.archive = (root / n for n in ("in", "out", "arch"))
        for d in (self.incoming, self.output, self.archive):
            d.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_pipeline(self, separator=fake_separator, dry_run=False):
        return ss.run_once(self.incoming, self.output, self.archive, "htdemucs", "cpu",
                           dry_run=dry_run, separator=separator)

    def test_exports_stem_and_archives_original(self):
        (self.incoming / "loop.wav").write_bytes(b"audio")
        self.assertEqual(self.run_pipeline(), (1, 0))
        self.assertEqual((self.output / "loop_other.wav").read_bytes(), b"OTHER:audio")
        self.assertEqual((self.archive / "loop.wav").read_bytes(), b"audio")
        self.assertEqual(list(self.incoming.iterdir()), [])

    def test_ignores_non_audio_and_hidden_files(self):
        (self.incoming / "notes.txt").write_text("x")
        (self.incoming / ".DS_Store").write_text("x")
        (self.incoming / "._loop.wav").write_bytes(b"x")  # macOS resource fork
        self.assertEqual(self.run_pipeline(), (0, 0))
        self.assertEqual(len(list(self.incoming.iterdir())), 3)

    def test_handles_mixed_case_extensions(self):
        (self.incoming / "Chop.AIFF").write_bytes(b"a")
        (self.incoming / "sample.Mp3").write_bytes(b"b")
        self.assertEqual(self.run_pipeline(), (2, 0))
        self.assertTrue((self.output / "Chop_other.wav").exists())
        self.assertTrue((self.output / "sample_other.wav").exists())

    def test_never_overwrites_existing_files(self):
        (self.output / "loop_other.wav").write_bytes(b"old export")
        (self.archive / "loop.wav").write_bytes(b"old original")
        (self.incoming / "loop.wav").write_bytes(b"new")
        self.run_pipeline()
        self.assertEqual((self.output / "loop_other.wav").read_bytes(), b"old export")
        self.assertEqual((self.output / "loop_other (2).wav").read_bytes(), b"OTHER:new")
        self.assertEqual((self.archive / "loop (2).wav").read_bytes(), b"new")

    def test_failure_leaves_original_in_place(self):
        (self.incoming / "loop.wav").write_bytes(b"audio")
        self.assertEqual(self.run_pipeline(failing_separator), (0, 1))
        self.assertTrue((self.incoming / "loop.wav").exists())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_one_failure_does_not_stop_the_batch(self):
        (self.incoming / "a.wav").write_bytes(b"bad")
        (self.incoming / "b.wav").write_bytes(b"good")

        def picky(src, work_dir, model, device):
            if src.name == "a.wav":
                raise RuntimeError("corrupt")
            return fake_separator(src, work_dir, model, device)

        self.assertEqual(self.run_pipeline(picky), (1, 1))
        self.assertTrue((self.incoming / "a.wav").exists())
        self.assertTrue((self.output / "b_other.wav").exists())

    def test_dry_run_changes_nothing(self):
        (self.incoming / "loop.wav").write_bytes(b"audio")
        self.run_pipeline(dry_run=True)
        self.assertTrue((self.incoming / "loop.wav").exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_main_rejects_same_folder_twice(self):
        code = ss.main(["--incoming", str(self.incoming), "--output", str(self.incoming),
                        "--archive", str(self.archive), "--dry-run"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
