import hashlib
import pathlib
import subprocess
import sys

LIBRARY = pathlib.Path("examples/incidents")


def digests(path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.iterdir())}


def test_committed_library_matches_generator(tmp_path):
    subprocess.run([sys.executable, "tools/synth_library.py", "--out", str(tmp_path)],
                   check=True, capture_output=True)
    assert digests(tmp_path) == digests(LIBRARY)
