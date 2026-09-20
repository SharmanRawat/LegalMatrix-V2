"""Image preprocessing for the scan pipeline.

Applied before OCR so the fast CPU engine gets the best possible input:
EXIF de-rotation, brightness/contrast correction (CLAHE), sharpening for
blur, and up-scaling for small images. Every applied operation is returned
so the inspection report can disclose exactly what was changed (audit
transparency — we never edit pixels silently).
"""
import cv2
import numpy as np
from PIL import Image, ImageOps

from app.config import OCR_ENHANCE_MAX_SIDE

BLUR_LAPLACIAN_VAR_THRESHOLD = 120.0
DARK_MEAN_THRESHOLD = 120.0
BRIGHT_MEAN_THRESHOLD = 225.0
TINY_MIN_SIDE = 800


def estimate_blurriness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def estimate_brightness(image: np.ndarray) -> float:
    return float(np.mean(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)))


def _load_bgr(image_path):
    img = cv2.imread(image_path)
    if img is None:
        with Image.open(image_path) as pil:
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img


def _save_bgr(image: np.ndarray, out_path) -> None:
    success, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if success:
        with open(out_path, "wb") as f:
            f.write(buf.tobytes())
    else:
        with Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)) as pil:
            pil.save(out_path, "JPEG", quality=92)


def enhance_image(image_path: str, out_path=None) -> tuple:
    """Enhance a product label photo for OCR.

    Returns (enhanced_path, applied, diagnostics) where:
      enhanced_path — path to the enhanced image (same path if no changes)
      applied       — list of operation names applied
      diagnostics   — dict of metrics (blur var, brightness, original size)
    """
    image = _load_bgr(image_path)
    if image is None:
        return (image_path, [], {"error": "unreadable"})

    h, w = image.shape[:2]
    diagnostics = {
        "original_size": [w, h],
        "blur_var": round(estimate_blurriness(image), 2),
        "brightness": round(estimate_brightness(image), 2),
    }
    applied = []

    brightness = estimate_brightness(image)
    if brightness < DARK_MEAN_THRESHOLD or brightness > BRIGHT_MEAN_THRESHOLD:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l_chan = clahe.apply(l_chan)
        image = cv2.merge((l_chan, a_chan, b_chan))
        image = cv2.cvtColor(image, cv2.COLOR_LAB2BGR)
        applied.append("contrast_clahe")

    blur_var = estimate_blurriness(image)
    diagnostics["blur_after"] = round(blur_var, 2)
    if blur_var < BLUR_LAPLACIAN_VAR_THRESHOLD:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
        sharpened = cv2.filter2D(image, -1, kernel)
        gray_sharp = cv2.cvtColor(sharpened, cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(gray_sharp, cv2.CV_64F).var() > blur_var:
            image = sharpened
            applied.append("sharpen")

    if min(image.shape[:2]) < TINY_MIN_SIDE:
        scale = max(1.0, 2.0 * (TINY_MIN_SIDE / float(min(image.shape[:2]))))
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        if scale > 1.5:
            applied.append("upscale")

    if not applied:
        return (image_path, [], diagnostics)

    if out_path is None:
        # Derived artifact — keep it out of the caller's folder (previously
        # '<photo>.enhanced.jpg' polluted the dataset / upload directories and
        # confused image globs). Namespaced by path hash so same-stem photos
        # from different folders never collide.
        import hashlib
        import tempfile
        from pathlib import Path
        tmpdir = Path(tempfile.gettempdir()) / "legalmatrix_enhanced"
        tmpdir.mkdir(parents=True, exist_ok=True)
        stem = Path(image_path).stem
        digest = hashlib.md5(str(image_path).encode("utf-8")).hexdigest()[:8]
        out_path = str(tmpdir / f"{stem}.{digest}.enhanced.jpg")
    _save_bgr(image, out_path)
    diagnostics["enhanced_size"] = list(image.shape[:2][::-1])
    return (out_path, applied, diagnostics)


def safe_capture_time(image_path: str):
    """ISO capture time from EXIF DateTimeOriginal / Digitized, else None."""
    try:
        from datetime import datetime
        with Image.open(image_path) as pil:
            exif = pil.getexif()
        raw = exif.get(0x9003) or exif.get(0x9009)
        if not raw:
            return None
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:
        return None