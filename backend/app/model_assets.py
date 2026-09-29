"""Pinned OpenCV Zoo weights. No downloads occur on API/worker startup."""

import argparse
import hashlib
import os
import urllib.request
from pathlib import Path

ZOO_COMMIT = "47534e27c9851bb1128ccc0102f1145e27f23f98"
MODEL_VERSION = "yunet-2023mar+sface-2021dec-opencv4.11-v1"
ASSETS = {
    "face_detection_yunet_2023mar.onnx": (
        "face_detection_yunet",
        232589,
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        "face_recognition_sface",
        38696353,
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def verify(directory: Path) -> None:
    for name, (_, size, checksum) in ASSETS.items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != size:
            raise RuntimeError(
                f"Missing or incomplete model: {name}; run python -m app.model_assets"
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError(f"Model checksum mismatch: {name}")


def download(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, (folder, size, checksum) in ASSETS.items():
        path = directory / name
        if path.exists() and path.stat().st_size == size:
            with path.open("rb") as source:
                if hashlib.sha256(source.read()).hexdigest() == checksum:
                    print(f"Verified {name}")
                    continue
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{ZOO_COMMIT}/models/{folder}/{name}"
        temporary = directory / (name + f".{os.getpid()}.part")
        try:
            with (
                urllib.request.urlopen(url, timeout=90) as response,
                temporary.open("wb") as output,
            ):
                while block := response.read(1024 * 1024):
                    output.write(block)
                    if output.tell() > size:
                        raise RuntimeError(f"Unexpected model size: {name}")
            if (
                temporary.stat().st_size != size
                or hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum
            ):
                raise RuntimeError(f"Downloaded model failed verification: {name}")
            temporary.replace(path)
            print(f"Downloaded and verified {name}")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    from app.config import get_settings

    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=get_settings().model_dir)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    (verify if args.verify_only else download)(args.directory)
