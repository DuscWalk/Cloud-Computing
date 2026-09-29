"""CPU YuNet detection, five-landmark alignment and normalized SFace embeddings."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import numpy as np

from app.config import get_settings
from app.model_assets import MODEL_VERSION, verify


class FaceRejected(Exception):
    def __init__(self, code: str, faces: int = 0):
        super().__init__(code)
        self.code = code
        self.faces = faces


@dataclass
class Encoding:
    vector: list[float]
    inference_ms: float
    faces: int = 1
    model_version: str = MODEL_VERSION


class FaceEngine:
    def __init__(self):
        import cv2

        self.cv = cv2
        settings = get_settings()
        verify(settings.model_dir)
        cv2.setNumThreads(settings.opencv_threads)
        cv2.ocl.setUseOpenCL(False)
        self.detector = cv2.FaceDetectorYN.create(
            str(settings.model_dir / "face_detection_yunet_2023mar.onnx"),
            "",
            (640, 640),
            settings.detection_threshold,
            0.3,
            5000,
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        self.encoder = cv2.FaceRecognizerSF.create(
            str(settings.model_dir / "face_recognition_sface_2021dec.onnx"),
            "",
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )

    def encode(self, path: Path) -> Encoding:
        cv = self.cv
        start = perf_counter()
        image = cv.imread(str(path))
        if image is None:
            raise FaceRejected("invalid_image")
        height, width = image.shape[:2]
        scale = min(1.0, 640 / max(width, height))
        resized = cv.resize(image, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((resized.shape[1], resized.shape[0]))
        _, detections = self.detector.detect(resized)
        count = 0 if detections is None else len(detections)
        if count == 0:
            raise FaceRejected("no_face")
        if count != 1:
            raise FaceRejected("multiple_faces", count)
        face = detections[0].copy()
        face[:14] /= scale
        x, y, w, h = face[:4]
        if min(w, h) < get_settings().min_face_size:
            raise FaceRejected("face_too_small", 1)
        left, top = max(0, int(x)), max(0, int(y))
        right, bottom = min(width, int(x + w)), min(height, int(y + h))
        crop = image[top:bottom, left:right]
        if not crop.size:
            raise FaceRejected("invalid_image", 1)
        blur = cv.Laplacian(cv.cvtColor(crop, cv.COLOR_BGR2GRAY), cv.CV_64F).var()
        if blur < get_settings().min_blur_score:
            raise FaceRejected("blurry_face", 1)
        aligned = self.encoder.alignCrop(image, face)
        raw = self.encoder.feature(aligned).reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(raw))
        if raw.size != 128 or not np.isfinite(raw).all() or norm < 1e-8:
            raise RuntimeError("Invalid SFace output")
        return Encoding((raw / norm).tolist(), (perf_counter() - start) * 1000)


@lru_cache(maxsize=1)
def get_face_engine() -> FaceEngine:
    return FaceEngine()


def rank_identities(vector: list[float], templates) -> list[tuple[str, str, float]]:
    """Return one best score per USER, not per photo, preventing false ambiguity."""
    query = np.asarray(vector, dtype=np.float32)
    if query.shape != (128,) or not np.isfinite(query).all():
        raise RuntimeError("Invalid query vector")
    query_norm = float(np.linalg.norm(query))
    if query_norm < 1e-8:
        raise RuntimeError("Empty query vector")
    best = {}
    for photo in templates:
        if photo.model_version != MODEL_VERSION or photo.embedding is None:
            continue
        candidate = np.asarray(photo.embedding, dtype=np.float32)
        if candidate.shape != (128,) or not np.isfinite(candidate).all():
            continue
        norm = float(np.linalg.norm(candidate))
        if norm < 1e-8:
            continue
        score = float(np.clip(np.dot(query, candidate) / (query_norm * norm), -1, 1))
        if photo.user_id not in best or score > best[photo.user_id][2]:
            best[photo.user_id] = (photo.user_id, photo.id, score)
    return sorted(best.values(), key=lambda item: item[2], reverse=True)
