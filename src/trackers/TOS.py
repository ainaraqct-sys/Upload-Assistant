# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
# import discord
from typing import Any, Optional

import cli_ui
import httpx

from src.console import console
from src.trackers.COMMON import COMMON
from src.trackers.FRENCH import FrenchTrackerMixin
from src.trackers.UNIT3D import UNIT3D, QueryValue


class TOS(FrenchTrackerMixin, UNIT3D):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config, tracker_name="TOS")
        self.config = config
        self.common = COMMON(config)
        self.tracker = "TOS"
        self.source_flag = "TheOldSchool"
        self.STRIP_FRENCH_DUB_SUFFIX = True
        self.INCLUDE_AUDIO_IN_NAME = False
        self.base_url = "https://theoldschool.cc"
        self.id_url = f"{self.base_url}/api/torrents/"
        self.upload_url = f"{self.base_url}/api/torrents/upload"
        self.search_url = f"{self.base_url}/api/torrents/filter"
        self.torrent_url = f"{self.base_url}/torrents/"
        self.banned_groups = [
            "FL3ER",
            "SUNS3T",
            "WoLFHD",
            "EXTREME",
            "Slay3R",
            "3T3AM",
            "BARBiE",
        ]
        pass

    async def get_category_id(
        self,
        meta: dict[str, Any],
        category: Optional[str] = None,
        reverse: bool = False,
        mapping_only: bool = False,
    ) -> dict[str, str]:
        _ = (category, reverse, mapping_only)
        language_tag = await self._build_audio_string(meta)
        if language_tag == "VOSTFR":
            category_id = "9" if meta["category"] == "TV" and meta.get("tv_pack") else {"MOVIE": "6", "TV": "7"}.get(meta["category"], "0")
        else:
            category_id = "8" if meta["category"] == "TV" and meta.get("tv_pack") else {"MOVIE": "1", "TV": "2"}.get(meta["category"], "0")
        return {"category_id": category_id}

    async def get_type_id(
        self,
        meta: dict[str, Any],
        type: Optional[str] = None,
        reverse: bool = False,
        mapping_only: bool = False,
    ) -> dict[str, str]:
        _ = (type, reverse, mapping_only)
        if meta["is_disc"] == "DVD":
            type_id = "7"
        elif meta.get("3D") == "3D":
            type_id = "8"
        else:
            type_id = {
                "DISC": "1",
                "REMUX": "2",
                "ENCODE": "3",
                "WEBDL": "4",
                "WEBRIP": "5",
                "HDTV": "6",
            }.get(meta["type"], "0")
        return {"type_id": type_id}

    async def search_existing(self, meta: dict[str, Any], _: Any = None) -> list[dict[str, Any]]:
        """Search for existing torrents on TOS.

        TOS uses separate categories for VOSTFR releases.  The default
        UNIT3D search filters by category, so a VOSTFR upload would miss
        MULTI releases in the normal category.  This override searches
        across both category sets so ``_check_french_lang_dupes`` can
        detect superior French-audio releases.
        """
        dupes: list[dict[str, Any]] = []

        meta.setdefault("tracker_status", {})
        meta["tracker_status"].setdefault(self.tracker, {})

        if not self.api_key:
            if not meta["debug"]:
                console.print(f"[bold red]{self.tracker}: Missing API key in config file. Skipping upload...[/bold red]")
            meta["skipping"] = f"{self.tracker}"
            return dupes

        should_continue = await self.get_additional_checks(meta)
        if not should_continue:
            meta["skipping"] = f"{self.tracker}"
            return dupes

        headers = {
            "authorization": f"Bearer {self.api_key}",
            "accept": "application/json",
        }

        # Determine all relevant category IDs
        # Normal: MOVIE=1, TV=2, TV pack=8
        # VOSTFR: MOVIE=6, TV=7, TV pack=9
        cat = meta.get("category", "MOVIE")
        is_pack = meta.get("tv_pack", False)
        if cat == "TV" and is_pack:
            category_ids = ["8", "9"]
        elif cat == "TV":
            category_ids = ["2", "7"]
        else:
            category_ids = ["1", "6"]

        params: list[tuple[str, QueryValue]] = [
            ("tmdbId", str(meta["tmdb"])),
            ("name", ""),
            ("perPage", "100"),
        ]
        params.extend(("categories[]", cid) for cid in category_ids)

        # Add resolution filter(s)
        resolutions = await self.get_resolution_id(meta)
        resolution_id = str(resolutions["resolution_id"])
        if resolution_id in ["3", "4"]:
            params.append(("resolutions[]", "3"))
            params.append(("resolutions[]", "4"))
        else:
            params.append(("resolutions[]", resolution_id))

        # Add type filter (types are format-based, not language-based)
        type_id = str((await self.get_type_id(meta))["type_id"])
        params.append(("types[]", type_id))

        if meta["category"] == "TV":
            params = [(k, (str(v) + f" {meta.get('season', '')}" if k == "name" else v)) for k, v in params]

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url=self.search_url, headers=headers, params=params)
                response.raise_for_status()
                if response.status_code == 200:
                    data = response.json()
                    for each in data["data"]:
                        torrent_id = each.get("id", None)
                        attributes = each.get("attributes", {})
                        name = attributes.get("name", "")
                        size = attributes.get("size", 0)
                        result: dict[str, Any] = {
                            "name": name,
                            "size": size,
                            "files": ([f["name"] for f in attributes.get("files", []) if isinstance(f, dict) and "name" in f] if not meta["is_disc"] else []),
                            "file_count": len(attributes.get("files", [])) if isinstance(attributes.get("files"), list) else 0,
                            "trumpable": attributes.get("trumpable", False),
                            "link": attributes.get("details_link", None),
                            "download": attributes.get("download_link", None),
                            "id": torrent_id,
                            "type": attributes.get("type", None),
                            "res": attributes.get("resolution", None),
                            "internal": attributes.get("internal", False),
                        }
                        if meta["is_disc"]:
                            result["bd_info"] = attributes.get("bd_info", "")
                            result["description"] = attributes.get("description", "")
                        dupes.append(result)
                else:
                    console.print(f"[bold red]Failed to search torrents on {self.tracker}. HTTP Status: {response.status_code}")
        except httpx.HTTPStatusError as e:
            meta["tracker_status"][self.tracker]["status_message"] = f"data error: HTTP {e.response.status_code}"
        except Exception as e:
            console.print(f"[bold red]{self.tracker}: Error searching for existing torrents — {e}[/bold red]")

        return await self._check_french_lang_dupes(dupes, meta)


    async def get_additional_checks(self, meta: dict[str, Any]) -> bool:
        # Check language requirements: must be French audio OR original audio with French subtitles
        french_languages = ["french", "fre", "fra", "fr", "français", "francais"]
        if not await self.common.check_language_requirements(
            meta,
            self.tracker,
            languages_to_check=french_languages,
            check_audio=True,
            check_subtitle=True,
            require_both=False,
            original_language=True,
        ):
            console.print(f"[bold red]Language requirements not met for {self.tracker}.[/bold red]")
            self._set_skip_reason(meta, "Langue française absente (audio/ST)")
            return False

        # Check if it's a Scene release without NFO - TOS requires NFO for Scene releases
        is_scene = meta.get("scene", False)
        has_nfo = meta.get("nfo", False) or meta.get("auto_nfo", False)

        if is_scene and not has_nfo:
            console.print(f"[red]{self.tracker}: Scene release detected but no NFO file found. TOS requires NFO files for Scene releases.[/red]")
            self._set_skip_reason(meta, "Release Scene sans NFO")
            return False

        # ── Limites bitrate TOS (source: règles officielles) ──
        # WEB-DL Untouched : pas de seuil minimum
        # BluRay Encode (ENCODE) et WEB Encode (WEBRIP) : limites ci-dessous
        release_type = meta.get("type", "")
        is_anime = bool(meta.get("anime", False))

        bitrate_table: dict[str, dict[str, dict[str, int]]] = {
            "ENCODE": {  # BluRay encodes
                "x264": {"720p": 4000, "1080p": 8000,  "2160p": 16000},
                "x265": {"720p": 3000, "1080p": 6000,  "2160p": 12000},
                "AV1":  {"720p": 2400, "1080p": 4000,  "2160p": 8000},
            },
            "WEBRIP": {  # WEB encodes
                "x264": {"720p": 3000, "1080p": 5000,  "2160p": 10000},
                "x265": {"720p": 2000, "1080p": 3500,  "2160p": 8000},
                "AV1":  {"720p": 2000, "1080p": 3000,  "2160p": 5000},
            },
        }
        anime_table: dict[str, dict[str, dict[str, int]]] = {
            "ENCODE": {
                "x264": {"720p": 2300, "1080p": 5000,  "2160p": 0},
                "x265": {"720p": 1800, "1080p": 3500,  "2160p": 8000},
                "AV1":  {"720p": 2400, "1080p": 4000,  "2160p": 8000},
            },
            "WEBRIP": {
                "x264": {"720p": 1800, "1080p": 3000,  "2160p": 6000},
                "x265": {"720p": 1200, "1080p": 2000,  "2160p": 4000},
                "AV1":  {"720p": 1200, "1080p": 1500,  "2160p": 3000},
            },
        }

        codec_map: dict[str, str] = {
            "H264": "x264", "x264": "x264", "AVC": "x264",
            "H265": "x265", "x265": "x265", "HEVC": "x265",
            "AV1": "AV1",
        }

        table = anime_table if is_anime else bitrate_table
        if release_type in table and not meta.get("is_disc"):
            resolution = meta.get("resolution", "")
            codec_key = codec_map.get(meta.get("video_codec", ""))
            if codec_key and resolution in table[release_type].get(codec_key, {}):
                min_kbps = table[release_type][codec_key][resolution]
                if min_kbps > 0:
                    tracks = meta.get("mediainfo", {}).get("media", {}).get("track", [])
                    video_track = next((t for t in tracks if t.get("@type") == "Video"), None)
                    raw_br = video_track.get("BitRate") if video_track else None
                    try:
                        bit_rate_kbps = int(raw_br) / 1000 if raw_br else None
                    except (ValueError, TypeError):
                        bit_rate_kbps = None

                    if bit_rate_kbps is not None and bit_rate_kbps < min_kbps:
                        label = f"{codec_key} (anime)" if is_anime else codec_key
                        console.print(f"[bold red]{self.tracker}: Bitrate trop bas: {bit_rate_kbps:.0f} kbps pour {label}.[/bold red]")
                        console.print(f"[bold yellow]Minimum TOS: {min_kbps} kbps pour {resolution}.[/bold yellow]")
                        self._set_skip_reason(meta, f"Bitrate trop bas: {bit_rate_kbps:.0f} kbps (min {min_kbps} kbps pour {codec_key}/{resolution})")
                        if meta.get("unattended", False):
                            return False
                        return cli_ui.ask_yes_no("Uploader quand même ?", default=False)

        return True

    async def get_additional_files(self, meta: dict[str, Any]) -> dict[str, tuple[str, bytes, str]]:
        """Override to inject a C411-style NFO into every TOS upload."""
        import os
        import aiofiles
        from src.trackers.C411 import C411

        files = await super().get_additional_files(meta)
        if "nfo" not in files:
            c411 = C411(config=self.config)
            nfo_content = await c411._generate_c411_nfo(meta)
            if nfo_content:
                nfo_path = os.path.join(meta["base_dir"], "tmp", meta["uuid"], f"{meta.get('uuid', 'release')}.nfo")
                os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
                async with aiofiles.open(nfo_path, "w", encoding="utf-8") as f:
                    await f.write(nfo_content)
                files["nfo"] = ("nfo_file.nfo", nfo_content.encode("utf-8"), "text/plain")
        return files

    async def get_description(self, meta: dict[str, Any]) -> dict[str, str]:
        return {"description": await self._build_description(meta)}

    async def _build_description(self, meta: dict[str, Any]) -> str:
        """Build the TOS BBCode description."""
        import re
        from datetime import date

        category = meta.get("category", "MOVIE")
        title = meta.get("title", "")
        year = meta.get("year", "")
        season = meta.get("season", "") or ""
        episode = meta.get("episode", "") or ""
        is_tv_pack = bool(meta.get("tv_pack", False))
        language = await self._build_audio_string(meta)
        resolution = meta.get("resolution", "") or ""
        type_val = meta.get("type", "").upper()
        service = meta.get("service", "") or ""
        tag = (meta.get("tag", "") or "").lstrip("-")

        type_display_map = {
            "WEBDL": "Web-Dl",
            "WEBRIP": "WEBRip",
            "REMUX": "Remux",
            "ENCODE": "Encode",
            "HDTV": "HDTV",
            "DISC": "Blu-ray",
        }
        type_display = type_display_map.get(type_val, type_val)
        category_display = "SERIE" if category == "TV" else "FILM"

        # ── Display title ──
        if category == "TV":
            season_m = re.search(r"S(\d+)", season)
            episode_m = re.search(r"E(\d+)", episode)
            if is_tv_pack and season_m:
                display_title = f"{title} - Saison {int(season_m.group(1))}"
            elif season_m and episode_m:
                display_title = f"{title} - Saison {int(season_m.group(1))} - Épisode {int(episode_m.group(1))}"
            else:
                display_title = title
        else:
            display_title = f"{title} ({year})" if year else title

        # ── File count ──
        filelist = meta.get("filelist", [])
        file_count = len(filelist) if filelist else 1

        # ── Source string ──
        source_str = f"{service} ({tag})" if service and tag else (service or tag)

        # ── Search URL ──
        cat_id_result = await self.get_category_id(meta)
        cat_id_str = cat_id_result.get("category_id", "1")
        tracker_cfg = self.config["TRACKERS"].get(self.tracker, {})
        tos_username = tracker_cfg.get("username", "")
        uploader_param = f"&uploader={tos_username}" if tos_username else ""
        # Use &#91; / &#93; to escape [ ] in BBCode
        search_url = (
            f"https://theoldschool.cc/torrents?perPage=100{uploader_param}"
            f"&name={title}&categories&#91;0&#93;={cat_id_str}"
        )

        # ── Build ──
        L = []

        # Header
        L.append("[center]")
        L.append("[code]")
        L.append("                                                                                ")
        L.append("                ▀█▀ █ █ █▀▀   █▀▀ █ █ █▀█ █▀▄ ▀█▀ █▀▀ █▀█ ▀█▀ █▀▀               ")
        L.append("                 █  █▀█ █▀▀   ▀▀█  █  █ █ █ █  █  █   █▀█  █  █▀▀               ")
        L.append("                 ▀  ▀ ▀ ▀▀▀   ▀▀▀  ▀  ▀ ▀ ▀▀  ▀▀▀ ▀▀▀ ▀ ▀  ▀  ▀▀▀               ")
        L.append("                                                                                ")
        L.append("                                  * Presents *                                  ")
        L.append("[/code]")
        L.append("")
        L.append(f"[size=30][b]{display_title}[/b][/size]")

        header_parts = [p for p in [category_display, type_display, service, resolution, language] if p]
        L.append(f"[b]{' – '.join(header_parts)}[/b]")

        if category == "TV":
            se = f"{season}{episode}"
            if se:
                L.append(se)
            label = "épisode" if file_count == 1 else "épisodes"
            L.append(f"{file_count} {label}")

        L.append("[/center]")
        L.append("")
        L.append("")

        # Compatibility warning
        L.append("[center][quote]")
        L.append("[size=20][b]Merci de vérifier la compatibilité de votre matériel avant de télécharger nos releases ![/b][/size]")
        L.append("En cas de problème de lecture, privilégiez le lecteur [url=https://mpv.io/installation/]mpv[/url].")
        L.append("[/quote][/center]")
        L.append("")
        L.append("")
        L.append("")

        # Upload info
        L.append("[center][size=20][b]📦 Informations Upload[/b][/size][/center]")
        L.append("")
        L.append("[code]")
        L.append(f"Qualité : {type_display}")
        if source_str:
            L.append(f"Source : {source_str}")
        L.append(f"Nombre de fichiers : {file_count}")
        L.append(f"Date d'upload : {date.today().strftime('%Y-%m-%d')}")
        L.append("[/code]")
        L.append("")
        L.append("")

        # Notes
        L.append("[center][size=20][b]💡 Notes[/b][/size][/center]")
        L.append("[center][quote]")
        L.append('[i]"We don\'t race. We don\'t need to."[/i]')
        L.append("")
        L.append("Merci de rester en seed le plus longtemps possible pour maintenir en vie nos torrents.")
        L.append("[/quote][/center]")
        L.append("")
        L.append("")

        # Other releases
        L.append("[center][size=20][b]🔗 Autres releases du groupe[/b][/size]")
        L.append(f"[url={search_url}]Retrouvez ici nos autres releases[/url] du même programme :")
        L.append(search_url)
        L.append("[/center]")

        return "\n".join(L)

    # get_name, _build_audio_string — inherited from FrenchTrackerMixin