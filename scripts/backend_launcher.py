"""PyInstaller entry for the bundled backend: same CLI as `python -m aiassetstudio`, plus a `selftest`
command that imports the heavy audio stack (librosa/numba/soundfile/scipy) which `serve` alone never
touches, so a broken freeze fails at build time instead of on the first BGM job.

Measured in docs/plans/notes/studio-pyinstaller-freeze.md (2026-11-07).
"""

import sys


def _selftest() -> int:
    import numpy

    print("numpy", numpy.__version__)
    import scipy

    print("scipy", scipy.__version__)
    import soundfile

    print("soundfile", soundfile.__version__, "libsndfile", soundfile.__libsndfile_version__)
    import numba

    print("numba", numba.__version__)
    import librosa

    print("librosa", librosa.__version__)
    import reportlab

    print("reportlab", reportlab.Version)
    # a real librosa call that compiles numba kernels
    y = numpy.zeros(22050, dtype=numpy.float32)
    librosa.beat.beat_track(y=y, sr=22050)
    print("librosa.beat.beat_track OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(_selftest())
    from aiassetstudio.cli import main

    main()
