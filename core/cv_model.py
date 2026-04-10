from __future__ import annotations

import numpy as np
from PIL import Image


def analyze_blockage(image: Image.Image) -> dict:
    """
    Heuristic blockage detection:
    - Dark ratio approximates mud/waste coverage.
    - Low edge density approximates reduced visible drain structure.
    """
    arr = np.asarray(image.resize((320, 320)), dtype=np.float32)

    # Convert to grayscale luminance.
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]

    dark_ratio = float((gray < 85).mean())

    # Very lightweight edge estimate using gradients.
    gx = np.diff(gray, axis=1)
    gy = np.diff(gray, axis=0)
    edge_strength = np.sqrt(gx[:-1, :] ** 2 + gy[:, :-1] ** 2)
    edge_density = float((edge_strength > 25).mean())

    # Combine features to a 0-100 blockage score.
    score = (dark_ratio * 75) + ((1 - edge_density) * 25)
    blockage_score = max(0.0, min(100.0, score * 100 / 100))

    if blockage_score >= 70:
        label = "Severely Blocked"
    elif blockage_score >= 40:
        label = "Partially Blocked"
    else:
        label = "Mostly Clear"

    return {
        "blockage_score": blockage_score,
        "label": label,
        "dark_ratio": dark_ratio,
        "edge_density": edge_density,
    }

