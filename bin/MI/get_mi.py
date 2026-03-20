#!/usr/bin/env python3
# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import os
import platform
import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

import requests

from src.console import console

MEDIAINFO_VERSION = "24.11"  # renovate: datasource=github-releases depName=MediaArea/MediaInfo
MEDIAINFO_CLI_BASE_URL = "https://mediaarea.net/download/binary/mediainfo"
MEDIAINFO_LIB_BASE_URL = "https://mediaarea.net/download/binary/libmediainfo0"


def _fetch_latest_mediainfo_version(fallback: str) -> str:
    """Query mediaarea.net and return the latest available MediaInfo version."""
    import re as _re

    try:
        resp = requests.get("https://mediaarea.net/download/binary/mediainfo/", timeout=15)
        resp.raise_for_status()
        versions = _re.findall(r'href="(\d+\.\d+)/"', resp.text)
        if versions:
            return sorted(versions, key=lambda v: [int(x) for x in v.split(".")])[-1]
    except Exception:
        pass
    return fallback


def get_filename(system: str, arch: str, library_type: str = "cli", version: str = MEDIAINFO_VERSION) -> str:
    if system == "windows":
        if library_type == "cli":
            return f"MediaInfo_CLI_{version}_Windows_x64.zip"
        return ""
    if system == "linux":
        if library_type == "cli":
            return f"MediaInfo_CLI_{version}_Lambda_{arch}.zip"
        elif library_type == "lib":
            return f"MediaInfo_DLL_{version}_Lambda_{arch}.zip"
        else:
            raise ValueError(f"Unknown library_type: {library_type}")
    return ""


def get_url(system: str, arch: str, library_type: str = "cli", version: str = MEDIAINFO_VERSION) -> str:
    filename = get_filename(system, arch, library_type, version)
    if library_type == "cli":
        return f"{MEDIAINFO_CLI_BASE_URL}/{version}/{filename}"
    elif library_type == "lib":
        return f"{MEDIAINFO_LIB_BASE_URL}/{version}/{filename}"
    else:
        raise ValueError(f"Unknown library_type: {library_type}")


def download_file(url: str, output_path: Path) -> None:
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def extract_windows(cli_archive: Path, output_dir: Path) -> None:
    """Extract MediaInfo.exe from the Windows zip archive."""
    with zipfile.ZipFile(cli_archive, "r") as zip_ref:
        for member in zip_ref.namelist():
            if member.endswith("MediaInfo.exe") or member == "MediaInfo.exe":
                zip_ref.extract(member, output_dir.parent)
                extracted_path = output_dir.parent / member
                target = output_dir / "MediaInfo.exe"
                shutil.move(str(extracted_path), str(target))
                break


def extract_linux(cli_archive: Path, lib_archive: Path, output_dir: Path) -> None:
    # Extract MediaInfo CLI from zip file
    with zipfile.ZipFile(cli_archive, "r") as zip_ref:
        file_list = zip_ref.namelist()
        mediainfo_file = output_dir / "mediainfo"

        # Look for the mediainfo binary in the archive
        for member in file_list:
            if member.endswith("/mediainfo") or member == "mediainfo":
                zip_ref.extract(member, output_dir.parent)
                extracted_path = output_dir.parent / member
                shutil.move(str(extracted_path), str(mediainfo_file))
                break

    # Extract MediaInfo library
    with zipfile.ZipFile(lib_archive, "r") as zip_ref:
        file_list = zip_ref.namelist()
        lib_file = output_dir / "libmediainfo.so.0"

        # Look for the library file in the archive
        if "lib/libmediainfo.so.0.0.0" in file_list:
            zip_ref.extract("lib/libmediainfo.so.0.0.0", output_dir.parent)
            extracted_path = output_dir.parent / "lib/libmediainfo.so.0.0.0"
            shutil.move(str(extracted_path), str(lib_file))

    # Clean up empty lib directory if it exists
    lib_dir = output_dir.parent / "lib"
    if lib_dir.exists() and not any(lib_dir.iterdir()):
        lib_dir.rmdir()


def download_dvd_mediainfo(base_dir: str, debug: bool = False) -> Optional[str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if debug:
        console.print(f"[blue]System: {system}, arch: {machine}[/blue]")

    version = _fetch_latest_mediainfo_version(MEDIAINFO_VERSION)

    # ── Windows ──
    if system == "windows":
        output_dir = Path(base_dir) / "bin" / "MI" / "windows"
        output_dir.mkdir(parents=True, exist_ok=True)
        cli_file = output_dir / "MediaInfo.exe"
        version_file = output_dir / f"version_{version}"
        if cli_file.exists() and version_file.exists():
            if debug:
                console.print(f"[blue]Windows MediaInfo {version} already exists[/blue]")
            return str(cli_file)
        cli_filename = get_filename(system, "x64", "cli", version)
        cli_url = get_url(system, "x64", "cli", version)
        console.print(f"[yellow]Downloading MediaInfo {version} for Windows...[/yellow]")
        if debug:
            console.print(f"[blue]URL: {cli_url}[/blue]")
        with TemporaryDirectory() as tmp_dir:
            cli_archive = Path(tmp_dir) / cli_filename
            download_file(cli_url, cli_archive)
            extract_windows(cli_archive, output_dir)
            with open(version_file, "w") as f:
                f.write(f"MediaInfo {version}")
        if not cli_file.exists():
            raise Exception(f"Failed to extract MediaInfo.exe to {cli_file}")
        return str(cli_file)

    # ── Linux ──
    if system != "linux" or machine not in ["x86_64", "arm64", "amd64"]:
        return

    if machine == "amd64":
        machine = "x86_64"

    output_dir = Path(base_dir) / "bin" / "MI" / "linux"
    output_dir.mkdir(parents=True, exist_ok=True)

    if debug:
        console.print(f"[blue]Output: {output_dir}[/blue]")

    cli_file = output_dir / "mediainfo"
    lib_file = output_dir / "libmediainfo.so.0"
    version_file = output_dir / f"version_{version}"

    if cli_file.exists() and lib_file.exists() and version_file.exists():
        if debug:
            console.print(f"[blue]MediaInfo CLI and Library {version} exist[/blue]")
        return str(cli_file)
    console.print(f"[yellow]Downloading specific MediaInfo CLI and Library for DVD processing: {version}...[/yellow]")
    cli_url = get_url(system, machine, "cli", version)
    cli_filename = get_filename(system, machine, "cli", version)
    lib_url = get_url(system, machine, "lib", version)
    lib_filename = get_filename(system, machine, "lib", version)

    if debug:
        console.print(f"[blue]MediaInfo CLI URL: {cli_url}[/blue]")
        console.print(f"[blue]MediaInfo CLI filename: {cli_filename}[/blue]")
        console.print(f"[blue]MediaInfo Library URL: {lib_url}[/blue]")
        console.print(f"[blue]MediaInfo Library filename: {lib_filename}[/blue]")

    with TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(str(tmp_dir))
        cli_archive = tmp_dir_path / cli_filename
        lib_archive = tmp_dir_path / lib_filename

        download_file(cli_url, cli_archive)
        if debug:
            console.print(f"[green]Downloaded {cli_filename}[/green]")

        download_file(lib_url, lib_archive)
        if debug:
            console.print(f"[green]Downloaded {lib_filename}[/green]")

        extract_linux(cli_archive, lib_archive, output_dir)

        if debug:
            console.print("[green]Extracted library[/green]")

        with open(version_file, "w") as f:
            f.write(f"MediaInfo {version}")

        if cli_file.exists():
            os.chmod(cli_file, 0o700)

    if not cli_file.exists():
        raise Exception(f"Failed to extract CLI binary to {cli_file}")
    if not lib_file.exists():
        raise Exception(f"Failed to extract library to {lib_file}")

    return str(cli_file)
