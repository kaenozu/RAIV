from __future__ import annotations

import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from exceptions import ArchiveExtractionError, ArchiveToolNotFoundError, UnsupportedArchiveFormatError
from helpers import archive_display_name, natural_sort_key, safe_archive_member_parts

ArchiveResult = tuple[list[Path], dict[Path, str]]
SEVEN_ZIP_COMMAND_NAMES = ("7z", "7za", "7zr")


def find_unsafe_archive_members(member_names: Iterable[str]) -> list[str]:
    return [name for name in member_names if safe_archive_member_parts(name) is None]


def list_7z_members(tool: Path, archive_path: Path) -> list[str]:
    completed = subprocess.run(
        [str(tool), "l", "-slt", str(archive_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode != 0:
        raise ArchiveExtractionError(completed.stdout.strip())
    members: list[str] = []
    header_path_skipped = False
    for line in completed.stdout.splitlines():
        if not line.startswith("Path = "):
            continue
        value = line[7:].strip()
        if not value:
            continue
        # `7z l -slt` emits the archive path as the first `Path = ...` header.
        if not header_path_skipped:
            header_path_skipped = True
            continue
        if value.endswith("/") or value.endswith("\\"):
            continue
        members.append(value)
    return members


def archive_member_output_path(temp_dir: Path, member_name: str) -> Path | None:
    parts = safe_archive_member_parts(member_name)
    return temp_dir.joinpath(*parts) if parts else None


def collect_archive_outputs(temp_dir: Path, is_image: Callable[[Path], bool]) -> ArchiveResult:
    images = sorted(
        [path.resolve() for path in temp_dir.rglob("*") if path.is_file() and is_image(path)],
        key=lambda path: natural_sort_key(archive_display_name(str(path.relative_to(temp_dir)))),
    )
    names = {path: archive_display_name(str(path.relative_to(temp_dir))) for path in images}
    return images, names


def find_7z() -> Path | None:
    for name in SEVEN_ZIP_COMMAND_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in (
        Path(os.environ.get("ProgramFiles", "")) / "7-Zip" / "7z.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "7-Zip" / "7z.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def extract_zip_images(archive_path: Path, temp_dir: Path, is_image: Callable[[Path], bool]) -> ArchiveResult:
    images: list[Path] = []
    names: dict[Path, str] = {}
    with zipfile.ZipFile(archive_path) as archive:
        members = sorted(
            [info for info in archive.infolist() if not info.is_dir() and is_image(Path(info.filename))],
            key=lambda item: natural_sort_key(archive_display_name(item.filename)),
        )
        for info in members:
            output = archive_member_output_path(temp_dir, info.filename)
            if output is None:
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            resolved = output.resolve()
            images.append(resolved)
            names[resolved] = archive_display_name(info.filename)
    return images, names


def extract_rar_images(archive_path: Path, temp_dir: Path, is_image: Callable[[Path], bool], rarfile_module: object) -> ArchiveResult:
    images: list[Path] = []
    names: dict[Path, str] = {}
    with rarfile_module.RarFile(archive_path) as archive:
        members = sorted(
            [info for info in archive.infolist() if not info.isdir() and is_image(Path(info.filename))],
            key=lambda item: natural_sort_key(archive_display_name(item.filename)),
        )
        for info in members:
            output = archive_member_output_path(temp_dir, info.filename)
            if output is None:
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            resolved = output.resolve()
            images.append(resolved)
            names[resolved] = archive_display_name(info.filename)
    return images, names


def extract_with_7z_command(archive_path: Path, temp_dir: Path, is_image: Callable[[Path], bool]) -> ArchiveResult:
    tool = find_7z()
    if tool is None:
        raise ArchiveToolNotFoundError("この形式を開くには py7zr/rarfile または 7z/7za/7zr が必要です。")
    unsafe = find_unsafe_archive_members(list_7z_members(tool, archive_path))
    if unsafe:
        raise ArchiveExtractionError(f"Archive contains unsafe member paths: {unsafe[0]}")
    completed = subprocess.run(
        [str(tool), "x", "-y", f"-o{temp_dir}", str(archive_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode != 0:
        raise ArchiveExtractionError(completed.stdout.strip())
    return collect_archive_outputs(temp_dir, is_image)


def extract_archive_images(
    archive_path: Path,
    temp_dir: Path,
    is_image: Callable[[Path], bool],
    py7zr_module: object | None,
    rarfile_module: object | None,
) -> ArchiveResult:
    suffix = archive_path.suffix.lower()
    if suffix in {".zip", ".cbz"}:
        return extract_zip_images(archive_path, temp_dir, is_image)
    if suffix in {".7z", ".cb7"}:
        if py7zr_module is not None:
            with py7zr_module.SevenZipFile(archive_path, mode="r") as archive:
                unsafe = find_unsafe_archive_members(archive.getnames())
                if unsafe:
                    raise ArchiveExtractionError(f"Archive contains unsafe member paths: {unsafe[0]}")
                archive.extractall(path=temp_dir)
            return collect_archive_outputs(temp_dir, is_image)
        return extract_with_7z_command(archive_path, temp_dir, is_image)
    if suffix in {".rar", ".cbr"}:
        if rarfile_module is not None:
            try:
                return extract_rar_images(archive_path, temp_dir, is_image, rarfile_module)
            except Exception as exc:
                logging.getLogger(__name__).warning("RAR extraction failed for %s, falling back to 7z: %s", archive_path, exc)
                return extract_with_7z_command(archive_path, temp_dir, is_image)
        return extract_with_7z_command(archive_path, temp_dir, is_image)
    raise UnsupportedArchiveFormatError(f"対応していない形式です: {suffix}")


def archive_open_error_message(error: Exception, language: str) -> str:
    if language == "en":
        return (
            "Failed to open archive.\n"
            f"{error}\n\n"
            "Recovery tips:\n"
            "- Run install_support.bat to install py7zr/rarfile\n"
            "- Or install 7-Zip/UnRAR/bsdtar and ensure it is in PATH"
        )
    return (
        "アーカイブを開けませんでした。\n"
        f"{error}\n\n"
        "対処方法:\n"
        "- install_support.bat で py7zr / rarfile を導入する\n"
        "- または 7-Zip / UnRAR / bsdtar を導入し、PATH を通す"
    )
