# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
"""
La Cale (la-cale.space) — French private tracker (custom REST API)

Upload endpoint:  POST https://la-cale.space/api/external/upload
Authentication:   X-Api-Key header (or ?apikey= query param)
Content-Type:     multipart/form-data

Required fields:  title, categoryId, file (.torrent)
Optional fields:  description, tmdbId, tmdbType, coverUrl, tags[] (IDs), nfoFile

API reference:    https://la-cale.space (Swagger docs)

Important: the torrent must contain the source flag "lacale".
"""

import asyncio
import json
import os
from typing import Any, Optional, TYPE_CHECKING

import aiofiles
import aiohttp
import httpx

from src.console import console
from src.trackers.COMMON import COMMON
from src.trackers.FRENCH import FrenchTrackerMixin

Meta = dict[str, Any]
Config = dict[str, Any]


class LACALE(FrenchTrackerMixin):
    """La Cale (la-cale.space) — French private tracker with custom REST API."""

    BASE_URL: str = "https://la-cale.space"

    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.tracker: str = "LACALE"
        self.source_flag: str = "lacale"
        self.base_url: str = self.BASE_URL
        self.upload_url: str = f"{self.BASE_URL}/api/external/upload"
        self.search_url: str = f"{self.BASE_URL}/api/external"
        self.meta_url: str = f"{self.BASE_URL}/api/external/meta"
        self.torrent_url: str = f"{self.BASE_URL}/torrents/"
        tracker_cfg = config["TRACKERS"].get(self.tracker, {})
        self.api_key: str = str(tracker_cfg.get("api_key", "")).strip()
        self.banned_groups: list[str] = [""]
        self._meta_cache: Optional[dict[str, Any]] = None  # cached /api/external/meta

    # ──────────────────────────────────────────────────────────
    #  HTTP helpers
    # ──────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
        }

    # ──────────────────────────────────────────────────────────
    #  Metadata (categories & tags) — cached
    # ──────────────────────────────────────────────────────────

    async def _fetch_meta(self) -> dict[str, Any]:
        """Fetch and cache /api/external/meta (categories, tagGroups, ungroupedTags)."""
        if self._meta_cache is not None:
            return self._meta_cache
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(self.meta_url, headers=self._headers())
            if resp.status_code == 200:
                self._meta_cache = resp.json()
                return self._meta_cache
            console.print(f"[yellow]LACALE: /api/external/meta returned HTTP {resp.status_code}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]LACALE: failed to fetch meta: {e}[/yellow]")
        return {}

    async def _get_category_id(self, meta: Meta) -> str:
        """Resolve the La Cale categoryId string for the given upload.

        Walks categories[].children[] from /api/external/meta and picks
        the best match.  Falls back to slug-based heuristics if the live
        API is unavailable.
        """
        site_meta = await self._fetch_meta()
        categories: list[dict[str, Any]] = site_meta.get("categories", [])

        if meta.get("debug") and categories:
            console.print("[cyan]LACALE categories from API:[/cyan]")
            for cat in categories:
                console.print(f"  {cat.get('id')} | {cat.get('slug')} | {cat.get('name')}")
                for child in (cat.get("children") or []):
                    console.print(f"    └─ {child.get('id')} | {child.get('slug')} | {child.get('name')}")

        is_anime = bool(meta.get("anime")) or bool(meta.get("mal_id"))
        genres = str(meta.get("genres", "")).lower()
        is_animation = is_anime or "animation" in genres
        is_reality = "reality" in genres or "talk show" in genres or "game show" in genres
        is_tv = meta.get("category") == "TV"
        is_doc = "documentary" in genres or "documentaire" in genres

        # Map: (slug_keyword, is_tv) → preferred slug candidates
        if is_tv:
            if is_animation:
                slug_prefs = ["series-animees", "animes", "animation-serie", "series"]
            elif is_reality:
                slug_prefs = ["emission", "emissions-tv", "tele-realite", "series"]
            else:
                slug_prefs = ["series", "series-tv", "tv"]
        else:
            if is_animation:
                slug_prefs = ["films-animation", "animation", "films"]
            elif is_doc:
                slug_prefs = ["documentaires", "documentaire", "films"]
            else:
                slug_prefs = ["films", "films-hd", "video"]

        # Flatten all children
        all_children: list[dict[str, Any]] = []
        for cat in categories:
            all_children.extend(cat.get("children") or [])
            # Include top-level categories too
            all_children.append(cat)

        for pref in slug_prefs:
            for child in all_children:
                if child.get("slug", "").lower() == pref:
                    return str(child["id"])

        # Fallback: pick first child of first "video" parent
        for cat in categories:
            if "vid" in cat.get("slug", "").lower() or "vid" in cat.get("name", "").lower():
                children = cat.get("children", [])
                if children:
                    return str(children[0]["id"])
                return str(cat.get("id", ""))

        # Last resort: first category
        if all_children:
            return str(all_children[0].get("id", ""))
        return ""

    async def _get_tag_ids(self, meta: Meta, language_tag: str) -> list[str]:
        """Resolve tag IDs from /api/external/meta for quality, source, codec, language."""
        site_meta = await self._fetch_meta()
        tag_groups: list[dict[str, Any]] = site_meta.get("tagGroups", [])
        ungrouped: list[dict[str, Any]] = site_meta.get("ungroupedTags", [])

        # Flatten all tags
        all_tags: list[dict[str, Any]] = list(ungrouped)
        for grp in tag_groups:
            if grp and isinstance(grp, dict):
                all_tags.extend(grp.get("tags") or [])

        slug_to_id: dict[str, str] = {t["slug"]: str(t["id"]) for t in all_tags if t.get("slug") and t.get("id")}
        name_to_id: dict[str, str] = {t["name"].lower(): str(t["id"]) for t in all_tags if t.get("name") and t.get("id")}

        def find_tag(*candidates: str) -> Optional[str]:
            for c in candidates:
                c_lower = c.lower()
                if c_lower in slug_to_id:
                    return slug_to_id[c_lower]
                if c_lower in name_to_id:
                    return name_to_id[c_lower]
            return None

        tag_ids: list[str] = []

        # Resolution
        resolution = meta.get("resolution", "")
        if resolution:
            tid = find_tag(resolution, resolution.lower())
            if tid:
                tag_ids.append(tid)

        # Source
        source = meta.get("source", "")
        type_ = meta.get("type", "")
        source_candidates: list[str] = []
        if type_ == "WEBDL":
            source_candidates = ["web-dl", "webdl", "web"]
        elif type_ == "WEBRIP":
            source_candidates = ["webrip", "web-rip", "web"]
        elif type_ == "REMUX":
            source_candidates = ["remux", "bluray-remux"]
        elif type_ == "ENCODE":
            source_candidates = [source.lower(), "encode"] if source else ["encode"]
        elif type_ == "HDTV":
            source_candidates = ["hdtv"]
        if source_candidates:
            tid = find_tag(*source_candidates)
            if tid:
                tag_ids.append(tid)

        # HDR/DV
        hdr = meta.get("hdr", "")
        if hdr:
            for token in hdr.split():
                tid = find_tag(token.lower(), token)
                if tid:
                    tag_ids.append(tid)

        # Video codec
        video_encode = meta.get("video_encode", "") or meta.get("video_codec", "")
        if video_encode:
            codec_candidates = [video_encode.lower(), video_encode]
            # Common slug aliases
            if "av1" in video_encode.lower():
                codec_candidates += ["av1"]
            elif "265" in video_encode or "hevc" in video_encode.lower():
                codec_candidates += ["x265", "h265", "hevc"]
            elif "264" in video_encode or "avc" in video_encode.lower():
                codec_candidates += ["x264", "h264", "avc"]
            tid = find_tag(*codec_candidates)
            if tid:
                tag_ids.append(tid)

        # Language
        if language_tag:
            lang_candidates: list[str] = [language_tag.lower()]
            if "multi" in language_tag.lower():
                lang_candidates += ["multi", "multi-langues"]
            elif "vostfr" in language_tag.lower():
                lang_candidates += ["vostfr"]
            elif "french" in language_tag.lower():
                lang_candidates += ["french", "vff", "vof"]
            elif "vof" in language_tag.lower():
                lang_candidates += ["vof", "vff", "french"]
            tid = find_tag(*lang_candidates)
            if tid:
                tag_ids.append(tid)

        return list(dict.fromkeys(tag_ids))  # deduplicate, preserve order

    # ──────────────────────────────────────────────────────────
    #  Release name  (French conventions via FrenchTrackerMixin)
    # ──────────────────────────────────────────────────────────

    async def get_name(self, meta: Meta) -> dict[str, str]:
        """Build the La Cale release name following French scene conventions."""
        import re

        def _clean(name: str) -> str:
            for char, repl in FrenchTrackerMixin._TITLE_CHAR_MAP.items():
                name = name.replace(char, repl)
            name = re.sub(r"[^a-zA-Z0-9 .+\-]", "", name)
            return name

        def _dotify(name: str) -> str:
            name = _clean(name)
            name = name.replace(" ", ".")
            name = re.sub(r"\.(-\.)+", ".", name)
            name = re.sub(r"\.{2,}", ".", name)
            return name.strip(".")

        type_ = meta.get("type", "").upper()
        title = meta.get("title", "")
        year = meta.get("year", "")
        if meta.get("manual_year") and int(meta["manual_year"]) > 0:
            year = meta["manual_year"]
        resolution = meta.get("resolution", "")
        if resolution == "OTHER":
            resolution = ""
        language = await self._build_audio_string(meta)
        service = meta.get("service", "")
        season = meta.get("season", "")
        episode = meta.get("episode", "")
        part = meta.get("part", "")
        repack = meta.get("repack", "")
        hdr = meta.get("hdr", "")
        video_encode = meta.get("video_encode", "")
        video_codec = meta.get("video_codec", "")
        audio = meta.get("audio", "").replace("Dual-Audio", "").replace("Dubbed", "").strip()
        edition = self._format_edition(meta.get("edition", ""))
        tag = meta.get("tag", "")
        uhd = meta.get("uhd", "")
        hybrid = str(meta.get("webdv", "")) if meta.get("webdv", "") else ""

        if meta.get("is_disc") == "BDMV":
            codec = video_codec
        else:
            codec = video_encode

        if meta.get("category") == "TV":
            if meta.get("search_year") == "":
                year = ""
            se = f"{season}{episode}"

            if type_ == "WEBDL":
                name = f"{title} {year} {se} {part} {edition} {hybrid} {repack} {language} {resolution} {uhd} {service} WEB {audio} {hdr} {codec}"
            elif type_ == "WEBRIP":
                name = f"{title} {year} {se} {part} {edition} {hybrid} {repack} {language} {resolution} {uhd} {service} WEBRip {audio} {hdr} {codec}"
            elif type_ == "REMUX":
                name = f"{title} {year} {se} {part} {edition} {hybrid} {repack} {language} {resolution} {uhd} BluRay REMUX {hdr} {video_codec} {audio}"
            elif type_ == "ENCODE":
                name = f"{title} {year} {se} {part} {edition} {hybrid} {repack} {language} {resolution} {uhd} {meta.get('source','')} {audio} {hdr} {codec}"
            elif type_ == "HDTV":
                name = f"{title} {year} {se} {part} {edition} {repack} {language} {resolution} HDTV {audio} {codec}"
            else:
                name = f"{title} {year} {se} {language} {resolution} {service} WEB {audio} {codec}"
        else:
            if type_ == "WEBDL":
                name = f"{title} {year} {edition} {hybrid} {repack} {language} {resolution} {uhd} {service} WEB {audio} {hdr} {codec}"
            elif type_ == "WEBRIP":
                name = f"{title} {year} {edition} {hybrid} {repack} {language} {resolution} {uhd} {service} WEBRip {audio} {hdr} {codec}"
            elif type_ == "REMUX":
                name = f"{title} {year} {edition} {hybrid} {repack} {language} {resolution} {uhd} BluRay REMUX {hdr} {video_codec} {audio}"
            elif type_ == "ENCODE":
                name = f"{title} {year} {edition} {hybrid} {repack} {language} {resolution} {uhd} {meta.get('source','')} {audio} {hdr} {codec}"
            elif type_ == "HDTV":
                name = f"{title} {year} {edition} {repack} {language} {resolution} HDTV {audio} {codec}"
            else:
                name = f"{title} {year} {language} {resolution} {service} WEB {audio} {codec}"

        name = " ".join(name.split())
        name = name + tag
        return {"name": _dotify(name)}

    # ──────────────────────────────────────────────────────────
    #  Dupe search
    # ──────────────────────────────────────────────────────────

    async def search_existing(self, meta: Meta, _: Any = None) -> list[dict[str, Any]]:
        """Search for existing torrents on La Cale.

        Uses TMDB ID when available (most accurate), falls back to title search.
        """
        if not self.api_key:
            console.print("[yellow]LACALE: No API key configured, skipping dupe check.[/yellow]")
            return []

        dupes: list[dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                params: dict[str, str] = {}

                tmdb_id = meta.get("tmdb_id") or meta.get("tmdb")
                if tmdb_id:
                    params["tmdbId"] = str(tmdb_id)
                else:
                    title = meta.get("title", "")
                    year = meta.get("year", "")
                    params["q"] = f"{title} {year}".strip()

                resp = await client.get(self.search_url, headers=self._headers(), params=params)

                if resp.status_code != 200:
                    if meta.get("debug"):
                        console.print(f"[yellow]LACALE: search returned HTTP {resp.status_code}[/yellow]")
                    return []

                items: list[dict[str, Any]] = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("title", "")
                    dupes.append({
                        "name": name,
                        "size": item.get("size"),
                        "link": item.get("link") or (f"{self.torrent_url}{item['guid']}" if item.get("guid") else None),
                        "id": item.get("guid"),
                    })

        except Exception as e:
            if meta.get("debug"):
                console.print(f"[yellow]LACALE: search error: {e}[/yellow]")

        if meta.get("debug"):
            console.print(f"[cyan]LACALE: dupe search found {len(dupes)} result(s)[/cyan]")

        return await self._check_french_lang_dupes(dupes, meta)

    # ──────────────────────────────────────────────────────────
    #  Upload
    # ──────────────────────────────────────────────────────────

    async def upload(self, meta: Meta, _disctype: str) -> bool:
        """Upload torrent to La Cale.

        POST https://la-cale.space/api/external/upload
          X-Api-Key: <api_key>
          Content-Type: multipart/form-data

        Required: title, categoryId, file (.torrent)
        Optional: description, tmdbId, tmdbType, coverUrl, tags[], nfoFile
        """
        if not self.api_key:
            console.print("[red]LACALE: No API key configured.[/red]")
            meta["tracker_status"][self.tracker]["status_message"] = "No API key configured"
            return False

        common = COMMON(config=self.config)
        await common.create_torrent_for_upload(meta, self.tracker, self.source_flag)

        # ── Release name ──
        name_result = await self.get_name(meta)
        title = name_result.get("name", "") if isinstance(name_result, dict) else str(name_result)

        # ── Language tag ──
        language_tag = await self._build_audio_string(meta)

        # ── Torrent file ──
        torrent_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}].torrent"
        async with aiofiles.open(torrent_path, "rb") as f:
            torrent_bytes = await f.read()

        # ── Category ID ──
        category_id = await self._get_category_id(meta)
        if not category_id:
            console.print("[red]LACALE: Could not resolve category ID.[/red]")
            meta["tracker_status"][self.tracker]["status_message"] = "Category ID resolution failed"
            return False

        # ── Tag IDs ──
        tag_ids = await self._get_tag_ids(meta, language_tag)

        # ── Cover URL (TMDB poster) ──
        cover_url = ""
        poster = meta.get("poster")
        if poster and str(poster).startswith("http"):
            cover_url = str(poster)

        # ── TMDB info ──
        tmdb_id = str(meta.get("tmdb_id") or meta.get("tmdb") or "")
        tmdb_type = "TV" if meta.get("category") == "TV" else "MOVIE"

        # ── Description ──
        description = await self._build_description(meta, language_tag)

        # ── NFO file (generate C411-style) ──
        nfo_bytes = b""
        nfo_path = meta.get("nfo", "")
        if nfo_path and os.path.exists(str(nfo_path)):
            async with aiofiles.open(str(nfo_path), "rb") as f:
                nfo_bytes = await f.read()
        else:
            from src.trackers.C411 import C411 as _C411
            _c411 = _C411(config=self.config)
            nfo_content = await _c411._generate_c411_nfo(meta)
            if nfo_content:
                nfo_bytes = nfo_content.encode("utf-8")

        # ── Anonymous ──
        anon = meta.get("anon", False) or self.config["TRACKERS"].get(self.tracker, {}).get("anon", False)

        if meta.get("debug"):
            console.print("[cyan]LACALE Debug — Request data:[/cyan]")
            console.print(f"  Title:       {title}")
            console.print(f"  CategoryId:  {category_id}")
            console.print(f"  Tags:        {tag_ids}")
            console.print(f"  TmdbId:      {tmdb_id} ({tmdb_type})")
            console.print(f"  CoverUrl:    {cover_url}")
            console.print(f"  Language:    {language_tag}")
            desc_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}]DESCRIPTION.txt"
            async with aiofiles.open(desc_path, "w", encoding="utf-8") as f:
                await f.write(description)
            console.print(f"  Description saved to {desc_path}")
            meta["tracker_status"][self.tracker]["status_message"] = "Debug mode, not uploaded."
            return True

        # ── Build multipart form ──
        files: dict[str, Any] = {
            "file": (f"{title}.torrent", torrent_bytes, "application/x-bittorrent"),
        }
        if nfo_bytes:
            files["nfoFile"] = ("release.nfo", nfo_bytes, "text/plain")

        data: dict[str, Any] = {
            "title": title,
            "categoryId": category_id,
        }
        if description:
            data["description"] = description
        if tmdb_id:
            data["tmdbId"] = tmdb_id
            data["tmdbType"] = tmdb_type
        if cover_url:
            data["coverUrl"] = cover_url

        max_retries = 2
        retry_delay = 5
        timeout = aiohttp.ClientTimeout(total=60)

        for attempt in range(max_retries):
            try:
                form = aiohttp.FormData()
                form.add_field("title", title)
                form.add_field("categoryId", category_id)
                if description:
                    form.add_field("description", description)
                if tmdb_id:
                    form.add_field("tmdbId", tmdb_id)
                    form.add_field("tmdbType", tmdb_type)
                if cover_url:
                    form.add_field("coverUrl", cover_url)
                for tid in tag_ids:
                    form.add_field("tags", tid)
                form.add_field("file", torrent_bytes, filename=f"{title}.torrent", content_type="application/x-bittorrent")
                if nfo_bytes:
                    form.add_field("nfoFile", nfo_bytes, filename="release.nfo", content_type="text/plain")

                async with aiohttp.ClientSession(headers=self._headers(), timeout=timeout, trust_env=True) as session:
                    async with session.post(self.upload_url, data=form) as response:
                        status = response.status
                        try:
                            resp_data = await response.json(content_type=None)
                        except Exception:
                            resp_data = {"raw": await response.text()}

                if status in (200, 201):
                    slug = resp_data.get("slug", "")
                    torrent_id = resp_data.get("id", slug)
                    link = resp_data.get("link", f"{self.torrent_url}{slug}" if slug else "")

                    meta["tracker_status"][self.tracker]["torrent_id"] = torrent_id
                    meta["tracker_status"][self.tracker]["status_message"] = resp_data
                    if slug:
                        meta["tracker_status"][self.tracker]["release_name"] = title
                        meta["tracker_status"][self.tracker]["torrent_url"] = link

                    console.print(f"[green]LACALE upload successful: {link}[/green]")

                    # Download tracker-generated torrent if available
                    download_url = resp_data.get("downloadLink") or resp_data.get("download_url")
                    if download_url:
                        if download_url.startswith("/"):
                            download_url = f"{self.BASE_URL}{download_url}"
                        try:
                            async with aiohttp.ClientSession(headers=self._headers(), trust_env=True) as dl_session:
                                async with dl_session.get(download_url) as dl_resp:
                                    if dl_resp.status == 200:
                                        torrent_data = await dl_resp.read()
                                        async with aiofiles.open(torrent_path, "wb") as f:
                                            await f.write(torrent_data)
                        except Exception as e:
                            console.print(f"[yellow]LACALE: Could not download tracker torrent: {e}[/yellow]")

                    return True

                elif status == 409:
                    meta["tracker_status"][self.tracker]["status_message"] = {"error": "Duplicate torrent (409)", "detail": resp_data}
                    console.print("[yellow]LACALE: Torrent already exists (duplicate infohash).[/yellow]")
                    return False

                elif status in (400, 401, 403, 422):
                    meta["tracker_status"][self.tracker]["status_message"] = {"error": f"HTTP {status}", "detail": resp_data}
                    console.print(f"[red]LACALE upload failed: HTTP {status}[/red]")
                    console.print(f"[dim]{resp_data}[/dim]")
                    return False

                elif status == 429:
                    console.print(f"[yellow]LACALE: Rate limited (429), waiting {retry_delay * 2}s…[/yellow]")
                    await asyncio.sleep(retry_delay * 2)
                    continue

                else:
                    if attempt < max_retries - 1:
                        console.print(f"[yellow]LACALE: HTTP {status}, retrying in {retry_delay}s… ({attempt + 1}/{max_retries})[/yellow]")
                        await asyncio.sleep(retry_delay)
                        continue
                    meta["tracker_status"][self.tracker]["status_message"] = {"error": f"HTTP {status}", "detail": resp_data}
                    console.print(f"[red]LACALE upload failed after {max_retries} attempts: HTTP {status}[/red]")
                    return False

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    console.print(f"[yellow]LACALE: timeout, retrying in {retry_delay}s… ({attempt + 1}/{max_retries})[/yellow]")
                    await asyncio.sleep(retry_delay)
                    continue
                meta["tracker_status"][self.tracker]["status_message"] = "data error: Request timed out"
                return False

            except Exception as e:
                if attempt < max_retries - 1:
                    console.print(f"[yellow]LACALE: error, retrying in {retry_delay}s… ({attempt + 1}/{max_retries})[/yellow]")
                    await asyncio.sleep(retry_delay)
                    continue
                meta["tracker_status"][self.tracker]["status_message"] = f"data error: Upload failed: {e}"
                console.print(f"[red]LACALE upload error: {e}[/red]")
                return False

        return False

    # ──────────────────────────────────────────────────────────
    #  Description (BBCode) — delegate to C411 builder
    # ──────────────────────────────────────────────────────────

    async def _build_description(self, meta: Meta, language_tag: str = "") -> str:
        """Delegate to C411's description builder (same rich BBCode layout)."""
        from src.trackers.C411 import C411  # late import to avoid circular dependency
        c411 = C411(config=self.config)
        return await c411._build_description(meta)

    async def edit_desc(self, _meta: Meta) -> None:
        """No-op — LACALE descriptions are built in upload()."""
        return
