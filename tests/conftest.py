import os

# Qt tests run without a display, locally and in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
