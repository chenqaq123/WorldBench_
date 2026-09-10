"""Local integration checks using a synthetic three-cut fixture, not scored benchmark data."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from worldline.judge import align_video, build_evidence
from worldline.video import detect_cuts, extract_frame, media_info


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required for media integration tests")
class MediaTests(unittest.TestCase):
    def test_real_cut_detection_and_readout_do_not_use_equal_or_llm_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "fixture.mp4"
            command = ["ffmpeg", "-v", "error"]
            for color, duration in (("black", 1), ("white", 2), ("black", 1)):
                command += ["-f", "lavfi", "-i", "color=c={}:s=160x96:r=24:d={}".format(color, duration)]
            command += ["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]", "-map", "[out]",
                        "-c:v", "libx264", "-threads", "1", str(video)]
            subprocess.run(command, check=True, capture_output=True)
            self.assertAlmostEqual(media_info(video)["duration"], 4, places=2)
            result = detect_cuts(video)
            self.assertEqual(len(result["segments"]), 3)
            self.assertAlmostEqual(result["cut_times"][0], 1, places=2)
            self.assertAlmostEqual(result["cut_times"][1], 3, places=2)
            client = Mock()
            alignment = align_video(client, root, {"shots": [{"index": i} for i in (1, 2, 3)]}, {}, {}, video)
            self.assertEqual([s["start"] for s in alignment["shots"]], [0, 1, 3])
            client.request.assert_not_called()
            frame = extract_frame(video, 3.5, root / "final.jpg")
            self.assertTrue(Path(frame["path"]).exists())
            self.assertEqual(frame["time"], 3.5)
            # The probe is the actual final range [3, 4], not a prescribed
            # three-second bin. Reference frames remain separate from scoring.
            shutil.copy2(video, root / "video.mp4")
            evidence = build_evidence(root, root / "video.mp4", alignment, {"identity_anchor_shots": {"A": 1}})
            readouts = [f for f in evidence if f["role"] == "readout"]
            self.assertEqual([f["time"] for f in readouts], [3.25, 3.75])
            self.assertEqual([f["fraction"] for f in readouts], [0.25, 0.75])
            self.assertEqual(len([f for f in evidence if f["role"] == "anchor"]), 3)


if __name__ == "__main__":
    unittest.main()
