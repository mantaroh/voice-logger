from __future__ import annotations

from pathlib import Path


def find_usb_mount(device_name: str, mount_roots: list[Path]) -> Path | None:
    target = device_name.lower()
    for root in mount_roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                name = child.name.lower()
                if name == target or target in name:
                    return child
        except PermissionError:
            continue
    return None


def collect_audio_files(mount: Path, source_subdir: str, audio_extensions: tuple[str, ...]) -> list[Path]:
    root = mount / source_subdir if source_subdir else mount
    if not root.exists() or not root.is_dir():
        return []

    files: list[Path] = []
    for ext in audio_extensions:
        files.extend(root.rglob(f"*{ext}"))
        files.extend(root.rglob(f"*{ext.upper()}"))

    unique: dict[str, Path] = {str(p): p for p in files if p.is_file()}
    return sorted(unique.values())
