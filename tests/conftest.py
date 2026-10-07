import sys
from pathlib import Path

# Let tests import the helper modules that sit next to them (fsbuilder,
# scenarios). The gpudoctor package itself comes from the installed copy or
# from pytest's ``pythonpath = src`` setting, never from a path hack here.
sys.path.insert(0, str(Path(__file__).parent))
