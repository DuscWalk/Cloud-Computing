"""Real neural-network tests: opt-in ONLY on GitHub CI / ECS, never local by default."""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageEnhance

from app.vision import FaceRejected, get_face_engine

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MODEL_TESTS") != "1", reason="Real inference runs on CI/ECS only"
)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def engine():
    return get_face_engine()


def test_verified_models_alignment_and_identity(engine, tmp_path):
    original = engine.encode(FIXTURES / "astronaut.png")
    with Image.open(FIXTURES / "astronaut.png") as image:
        variant = ImageEnhance.Brightness(
            image.rotate(2, resample=Image.Resampling.BICUBIC)
        ).enhance(0.9)
        variant.save(tmp_path / "variant.jpg", quality=90)
    same = engine.encode(tmp_path / "variant.jpg")
    unknown = engine.encode(FIXTURES / "grace_hopper.jpg")
    assert len(original.vector) == 128
    assert np.linalg.norm(original.vector) == pytest.approx(1, abs=1e-5)
    same_score = float(np.dot(original.vector, same.vector))
    different_score = float(np.dot(original.vector, unknown.vector))
    assert same_score > 0.5
    assert different_score < 0.5
    print(
        f"model smoke: same={same_score:.4f}, different={different_score:.4f}; "
        "not a classroom accuracy estimate"
    )


def test_no_face_and_multiple_faces(engine, tmp_path):
    blank = tmp_path / "blank.jpg"
    Image.new("RGB", (640, 480), "gray").save(blank)
    with pytest.raises(FaceRejected, match="no_face"):
        engine.encode(blank)
    with Image.open(FIXTURES / "astronaut.png") as source:
        canvas = Image.new("RGB", (1024, 512))
        canvas.paste(source, (0, 0))
        canvas.paste(source, (512, 0))
        canvas.save(tmp_path / "multiple.jpg", quality=95)
    with pytest.raises(FaceRejected, match="multiple_faces"):
        engine.encode(tmp_path / "multiple.jpg")
