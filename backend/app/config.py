"""Path & runtime configuration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TENNIS_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
FRAMES_DIR = DATA_DIR / "frames"
CLIPS_DIR = DATA_DIR / "clips"
EXPORTS_DIR = DATA_DIR / "exports"
THUMBS_DIR = DATA_DIR / "thumbs"

for d in (UPLOAD_DIR, FRAMES_DIR, CLIPS_DIR, EXPORTS_DIR, THUMBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Analysis parameters
ANALYSIS_FPS = 5            # coarse scan frame rate
REFINE_FPS = 20             # boundary refinement frame rate
REFINE_WINDOW = 3.0         # seconds around a candidate boundary to refine
BALL_PRESENT_RATIO = 0.25   # min fraction of frames with ball in a rally window
MIN_RALLY_SEC = 2.0         # minimum rally duration
MAX_GAP_SEC = 3.5           # gap longer than this splits two clips
CLIP_PAD_START = 0.8        # seconds of context before rally start (serve toss)
CLIP_PAD_END = 1.0          # seconds after rally end

CLIP_SCALE = 1280           # export width
CLIP_CRF = 21
CLIP_PRESET = "veryfast"
