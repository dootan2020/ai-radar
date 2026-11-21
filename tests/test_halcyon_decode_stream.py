"""stream_raw / read_raw_frames: the incremental ffmpeg stdout reader of video/halcyon/dung-video-gpu.py. The builder needs a GPU and torch, so
the function is lifted from its source and run against small Python child processes standing in for ffmpeg."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / 'video' / 'halcyon' / 'dung-video-gpu.py').read_text(encoding='utf-8')
HAS_NUMPY = importlib.util.find_spec('numpy') is not None     # the GPU interpreter has numpy; the CI Python does not (torch is not needed here)
NS = {'subprocess': subprocess, 'tempfile': tempfile}
if HAS_NUMPY:
    import numpy as np
    NS['np'] = np
    exec(SRC[SRC.index('def stream_raw'):SRC.index('def read_raw_frames_gpu')], NS)
    read_raw_frames = NS['read_raw_frames']


def child(code):
    return [sys.executable, '-I', '-c', code]


@unittest.skipUnless(HAS_NUMPY, 'the incremental reader needs numpy (the GPU interpreter has it, the CI Python does not)')
class ReadRawFrames(unittest.TestCase):
    def test_reads_known_bytes_across_chunks(self):
        code = "import sys; sys.stdout.buffer.write(bytes(range(256)) * 40)"
        got, rc, err = read_raw_frames(child(code), 256 * 40, chunk=1000)
        self.assertEqual(rc, 0)
        self.assertEqual(got.tobytes(), bytes(range(256)) * 40)
        self.assertEqual(err, b'')

    def test_stderr_larger_than_a_pipe_does_not_block(self):
        code = ("import sys; sys.stderr.write('x' * 3_000_000); sys.stderr.flush();"
                "sys.stdout.buffer.write(b'ab' * 1000)")
        got, rc, err = read_raw_frames(child(code), 2000)
        self.assertEqual((rc, got.tobytes()), (0, b'ab' * 1000))
        self.assertEqual(len(err), 3_000_000)

    def test_short_output_returns_what_was_read(self):
        got, rc, _ = read_raw_frames(child("import sys; sys.stdout.buffer.write(b'z' * 700)"), 2000)
        self.assertEqual((rc, len(got)), (0, 700))

    def test_failure_keeps_exit_code_and_stderr(self):
        code = "import sys; sys.stderr.write('boom'); sys.exit(3)"
        got, rc, err = read_raw_frames(child(code), 100)
        self.assertEqual((rc, len(got), err), (3, 0, b'boom'))

    def test_extra_output_is_drained_not_returned(self):
        code = "import sys; sys.stdout.buffer.write(b'q' * 50_000)"
        got, rc, _ = read_raw_frames(child(code), 1000, chunk=500)
        self.assertEqual((rc, got.tobytes()), (0, b'q' * 1000))

    def test_result_is_one_preallocated_array(self):
        got, _, _ = read_raw_frames(child("import sys; sys.stdout.buffer.write(b'1' * 64)"), 64)
        self.assertIsInstance(got, np.ndarray)
        self.assertEqual(got.dtype, np.uint8)

    def test_stream_raw_hands_over_pieces_with_offsets(self):
        seen = []
        got, rc, _ = NS['stream_raw'](child("import sys; sys.stdout.buffer.write(bytes(range(100)))"), 100,
                                      lambda view, off: seen.append((off, bytes(view))), chunk=30)
        self.assertEqual((got, rc), (100, 0))
        self.assertEqual(b''.join(piece for _, piece in seen), bytes(range(100)))
        self.assertEqual([off for off, _ in seen], sorted(off for off, _ in seen))
        self.assertEqual(seen[0][0], 0)


class BuilderWiring(unittest.TestCase):
    def test_clips_stream_to_the_gpu_without_a_host_copy(self):
        self.assertNotIn('raw[lo:need_n]', SRC)
        self.assertEqual(SRC.count('buf, cmd = decode_nv12_gpu('), 2)
        gpu = SRC[SRC.index('def read_raw_frames_gpu'):SRC.index('def nv12_cmd')]
        self.assertIn('torch.empty(total - skip', gpu)
        self.assertIn('stream_raw(', gpu)

    def test_no_decode_goes_through_capture_output(self):
        self.assertNotIn('capture_output=True', SRC[SRC.index('def nv12_cmd'):SRC.index('def nv12_to_rgb')])
        self.assertIn('read_raw_frames(cmd, nframes * fb)', SRC)

    def test_error_messages_are_kept(self):
        for needle in ("'NVDEC decode failed: '", "decoded only {n} of {nframes} frames from {webm}"):
            self.assertIn(needle, SRC)

if __name__ == '__main__':
    unittest.main()