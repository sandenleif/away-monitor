"""Laedt das YuNet-Modell (~230 KB) aus dem offiziellen OpenCV-Zoo."""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
TARGET = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"


def main() -> int:
    if TARGET.exists() and hashlib.sha256(TARGET.read_bytes()).hexdigest() == SHA256:
        print(f"Modell ist bereits da: {TARGET}")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    print(f"Lade {URL} ...")
    with urllib.request.urlopen(URL, timeout=60) as response:  # noqa: S310 -- feste https-URL
        payload = response.read()

    digest = hashlib.sha256(payload).hexdigest()
    if digest != SHA256:
        print(f"Pruefsumme passt nicht!\n  erwartet: {SHA256}\n  bekommen: {digest}", file=sys.stderr)
        return 1

    TARGET.write_bytes(payload)
    print(f"Gespeichert: {TARGET} ({len(payload)} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
