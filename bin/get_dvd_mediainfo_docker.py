#!/usr/bin/env python3
# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
"""
Docker-specific script to download DVD-capable MediaInfo binaries for Linux.
This script downloads specialized MediaInfo CLI and library binaries that
support DVD IFO/VOB file parsing with language information.
"""

import os
import platform
import shutil
import stat
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

try:
    from src.console import console
except ImportError:
    # Fallback for Docker builds where rich is not yet installed
    class SimpleConsole:
        def print(self, message: str, markup: bool = False) -> None:  # noqa: ARG002
            print(message)

    console = SimpleConsole()

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
    """Get the appropriate filename for MediaInfo download based on system and architecture."""
    if system == "linux":
        if library_type == "cli":
            return f"MediaInfo_CLI_{version}_Lambda_{arch}.zip"
        elif library_type == "lib":
            return f"MediaInfo_DLL_{version}_Lambda_{arch}.zip"
        else:
            raise ValueError(f"Unknown library_type: {library_type}")
    else:
        raise ValueError(f"Unsupported system: {system}")


def get_url(system: str, arch: str, library_type: str = "cli", version: str = MEDIAINFO_VERSION) -> str:
    """Construct download URL for MediaInfo components."""
    filename = get_filename(system, arch, library_type, version)
    if library_type == "cli":
        return f"{MEDIAINFO_CLI_BASE_URL}/{version}/{filename}"
    elif library_type == "lib":
        return f"{MEDIAINFO_LIB_BASE_URL}/{version}/{filename}"
    else:
        raise ValueError(f"Unknown library_type: {library_type}")


def download_file(url: str, output_path: Path) -> None:
    """Download a file from URL to specified path."""
    console.print(f"Downloading: {url}", markup=False)
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    console.print(f"Downloaded: {output_path.name}", markup=False)


def extract_linux_binaries(cli_archive: Path, lib_archive: Path, output_dir: Path) -> None:
    """Extract MediaInfo CLI and library from downloaded archives."""
    console.print("Extracting MediaInfo binaries...", markup=False)

    # Extract MediaInfo CLI from zip file
    with zipfile.ZipFile(cli_archive, "r") as zip_ref:
        file_list = zip_ref.namelist()
        mediainfo_file = output_dir / "mediainfo"

        console.print(f"CLI archive contents: {file_list}", markup=False)

        # Look for the mediainfo binary in the archive
        for member in file_list:
            # Check for symlinks in ZIP files
            info = zip_ref.getinfo(member)
            perm = info.external_attr >> 16
            if stat.S_ISLNK(perm):
                console.print(f"Warning: Skipping symlink: {member}", markup=False)
                continue

            # Check for absolute paths
            if os.path.isabs(member):
                console.print(f"Warning: Skipping absolute path: {member}", markup=False)
                continue

            # Check for directory traversal patterns
            if ".." in member or member.startswith("/"):
                console.print(f"Warning: Skipping dangerous path: {member}", markup=False)
                continue

            if member.endswith("/mediainfo") or member == "mediainfo":
                zip_ref.extract(member, output_dir.parent)
                extracted_path = output_dir.parent / member
                shutil.move(str(extracted_path), str(mediainfo_file))
                console.print(f"Extracted CLI binary: {mediainfo_file}", markup=False)
                break
        else:
            raise Exception("MediaInfo CLI binary not found in archive")

    # Extract MediaInfo library
    with zipfile.ZipFile(lib_archive, "r") as zip_ref:
        file_list = zip_ref.namelist()
        lib_file = output_dir / "libmediainfo.so.0"

        console.print(f"Library archive contents: {file_list}", markup=False)

        # Look for the library file in the archive
        lib_candidates = ["lib/libmediainfo.so.0.0.0", "libmediainfo.so.0.0.0", "libmediainfo.so.0", "MediaInfo/libmediainfo.so.0.0.0", "MediaInfo/lib/libmediainfo.so.0.0.0"]

        for candidate in lib_candidates:
            if candidate in file_list:
                # Check for symlinks in ZIP files
                info = zip_ref.getinfo(candidate)
                perm = info.external_attr >> 16
                if stat.S_ISLNK(perm):
                    console.print(f"Warning: Skipping symlink: {candidate}", markup=False)
                    continue

                # Check for absolute paths
                if os.path.isabs(candidate):
                    console.print(f"Warning: Skipping absolute path: {candidate}", markup=False)
                    continue

                # Check for directory traversal patterns
                if ".." in candidate or candidate.startswith("/"):
                    console.print(f"Warning: Skipping dangerous path: {candidate}", markup=False)
                    continue

                zip_ref.extract(candidate, output_dir.parent)
                extracted_path = output_dir.parent / candidate
                # Move to final location
                shutil.move(str(extracted_path), str(lib_file))
                # Set appropriate permissions for library file (readable by all)
                os.chmod(lib_file, 0o644)
                console.print(f"Extracted library: {lib_file}", markup=False)
                break
        else:
            raise Exception("MediaInfo library not found in archive")

    # Clean up empty lib directory if it exists
    lib_dir = output_dir.parent / "lib"
    if lib_dir.exists() and not any(lib_dir.iterdir()):
        lib_dir.rmdir()


def download_dvd_mediainfo_docker():
    """Download DVD-specific MediaInfo binaries for Docker container."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    console.print(f"System: {system}, Architecture: {machine}", markup=False)

    if system != "linux":
        raise Exception(f"This script is only for Linux containers, got: {system}")

    # Normalize architecture names
    if machine in ["amd64", "x86_64"]:
        arch = "x86_64"
    elif machine in ["arm64", "aarch64"]:
        arch = "arm64"
    else:
        raise Exception(f"Unsupported architecture: {machine}")

    # Set up output directory in the container
    base_dir = Path("/Upload-Assistant")
    output_dir = base_dir / "bin" / "MI" / "linux"
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"Installing DVD MediaInfo to: {output_dir}", markup=False)

    version = _fetch_latest_mediainfo_version(MEDIAINFO_VERSION)

    cli_file = output_dir / "mediainfo"
    lib_file = output_dir / "libmediainfo.so.0"
    version_file = output_dir / f"version_{version}"

    # Check if already installed
    if cli_file.exists() and lib_file.exists() and version_file.exists():
        console.print(f"DVD MediaInfo {version} already installed", markup=False)
        return str(cli_file)

    console.print(f"Downloading DVD-specific MediaInfo CLI and Library: {version}", markup=False)

    # Get download URLs
    cli_url = get_url(system, arch, "cli", version)
    lib_url = get_url(system, arch, "lib", version)

    cli_filename = get_filename(system, arch, "cli", version)
    lib_filename = get_filename(system, arch, "lib", version)

    console.print(f"CLI URL: {cli_url}", markup=False)
    console.print(f"Library URL: {lib_url}", markup=False)

    # Download and extract in temporary directory
    with TemporaryDirectory() as tmp_dir:
        cli_archive = Path(tmp_dir) / cli_filename
        lib_archive = Path(tmp_dir) / lib_filename

        # Download both archives
        download_file(cli_url, cli_archive)
        download_file(lib_url, lib_archive)

        # Extract binaries
        extract_linux_binaries(cli_archive, lib_archive, output_dir)

        # Create version marker
        with open(version_file, "w") as f:
            f.write(f"MediaInfo {version} - DVD Support")

        # Make CLI binary executable and verify permissions
        if cli_file.exists():
            # Set secure executable permissions (owner only)
            os.chmod(cli_file, 0o700)
            # Verify permissions were set correctly
            file_stat = cli_file.stat()
            is_executable = bool(file_stat.st_mode & 0o100)  # Check if owner execute bit is set
            if is_executable:
                console.print(f"✓ Set secure executable permissions on: {cli_file} (mode: {oct(file_stat.st_mode)})", markup=False)
            else:
                raise Exception(f"Failed to set executable permissions on: {cli_file}")
        else:
            raise Exception(f"CLI binary not found for permission setting: {cli_file}")

    # Verify installation and permissions
    if not cli_file.exists():
        raise Exception(f"Failed to install CLI binary: {cli_file}")
    if not lib_file.exists():
        raise Exception(f"Failed to install library: {lib_file}")

    # Final executable verification
    cli_stat = cli_file.stat()
    if not (cli_stat.st_mode & 0o111):
        raise Exception(f"CLI binary is not executable: {cli_file}")
    else:
        console.print(f"✓ CLI binary is executable: {oct(cli_stat.st_mode)}", markup=False)

    console.print(f"Successfully installed DVD MediaInfo {version}", markup=False)
    console.print(f"CLI: {cli_file}", markup=False)
    console.print(f"Library: {lib_file}", markup=False)

    return str(cli_file)


if __name__ == "__main__":
    try:
        download_dvd_mediainfo_docker()
        console.print("DVD MediaInfo installation completed successfully!", markup=False)
    except Exception as e:
        console.print(f"ERROR: Failed to install DVD MediaInfo: {e}", markup=False)
        exit(1)
