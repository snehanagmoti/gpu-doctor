import sys
from pathlib import Path

# Let tests import the helper modules that sit next to them (fsbuilder,
# scenarios).
sys.path.insert(0, str(Path(__file__).parent))

# In a git checkout, fall back to src/ so the tests run without installing.
# Appended, not prepended: during the Debian build and under autopkgtest the
# built or installed copy must win, because that is what is being tested.
# (pytest's `pythonpath` ini option would do this too, but only from pytest
# 7; Ubuntu 22.04 ships pytest 6.2.)
_src = Path(__file__).resolve().parent.parent / "src"
if _src.is_dir():
    sys.path.append(str(_src))
