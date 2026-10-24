from __future__ import annotations

import base64
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, Optional, Set


def get_default_cache_dir() -> Path:
    """Returns local project cache directory for downloaded emojis,
    falling back to user home cache if project directory is read-only or in site-packages.
    """
    local_dir = Path(__file__).resolve().parent.parent / ".cache" / "emojis"
    is_site_packages = any(p in str(local_dir).lower() for p in ("site-packages", "dist-packages"))
    if not is_site_packages:
        try:
            local_dir.mkdir(parents=True, exist_ok=True)
            return local_dir
        except (PermissionError, OSError):
            pass

    home_cache = Path.home() / ".cache" / "tg_flowmap" / "emojis"
    home_cache.mkdir(parents=True, exist_ok=True)
    return home_cache


def load_cached_emoji(emoji_id: str, cache_dir: Path) -> Optional[str]:
    """Loads a cached emoji file as a base64 Data URL if it exists."""
    for ext in (".webp", ".png", ".jpg", ".svg"):
        cached_file = cache_dir / f"{emoji_id}{ext}"
        if cached_file.exists():
            try:
                raw_bytes = cached_file.read_bytes()
                mime = "image/svg+xml" if ext == ".svg" else f"image/{ext.lstrip('.')}"
                b64 = base64.b64encode(raw_bytes).decode("ascii")
                return f"data:{mime};base64,{b64}"
            except Exception:
                pass
    return None


def fetch_custom_emojis(
    token: str,
    emoji_ids: Iterable[str],
    cache_dir: Optional[Path] = None,
    timeout: float = 8.0,
) -> Dict[str, str]:
    """Fetches Telegram Premium custom emojis by IDs using Telegram Bot API.
    
    Caches downloaded WebP files locally so subsequent runs do not perform
    repeated network requests. Returns mapping of {emoji_id: data_url}.
    """
    clean_token = token.strip()
    if not clean_token or not emoji_ids:
        return {}

    cache_path = cache_dir or get_default_cache_dir()
    cache_path.mkdir(parents=True, exist_ok=True)

    result_map: Dict[str, str] = {}
    missing_ids: Set[str] = set()

    for eid in emoji_ids:
        eid_str = str(eid).strip()
        if not eid_str:
            continue
        data_url = load_cached_emoji(eid_str, cache_path)
        if data_url:
            result_map[eid_str] = data_url
        else:
            missing_ids.add(eid_str)

    if not missing_ids:
        return result_map

    ctx = ssl.create_default_context()

    missing_list = list(missing_ids)
    batches = [missing_list[i : i + 100] for i in range(0, len(missing_list), 100)]

    for batch in batches:
        api_url = f"https://api.telegram.org/bot{clean_token}/getCustomEmojiStickers"
        req_body = json.dumps({"custom_emoji_ids": batch}).encode("utf-8")

        try:
            req = urllib.request.Request(
                api_url,
                data=req_body,
                headers={"Content-Type": "application/json", "User-Agent": "tg-flowmap/0.1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

            if not resp_data.get("ok"):
                desc = resp_data.get("description", "Unknown error")
                print(f"[WARN] Telegram API error: {desc}", file=sys.stderr)
                continue

            stickers = resp_data.get("result", [])
            for sticker in stickers:
                custom_id = str(sticker.get("custom_emoji_id") or "")
                if not custom_id:
                    continue

                # Pick thumbnail if available for compact size, otherwise main file
                file_id = None
                if sticker.get("thumbnail") and sticker["thumbnail"].get("file_id"):
                    file_id = sticker["thumbnail"]["file_id"]
                elif sticker.get("file_id"):
                    file_id = sticker["file_id"]

                if not file_id:
                    continue

                # Call getFile to resolve file_path
                try:
                    get_file_url = f"https://api.telegram.org/bot{clean_token}/getFile?file_id={file_id}"
                    file_req = urllib.request.Request(
                        get_file_url,
                        headers={"User-Agent": "tg-flowmap/0.1.0"},
                    )
                    with urllib.request.urlopen(file_req, context=ctx, timeout=timeout) as f_resp:
                        f_data = json.loads(f_resp.read().decode("utf-8"))

                    if not f_data.get("ok"):
                        continue

                    file_path_str = f_data["result"]["file_path"]
                    dl_url = f"https://api.telegram.org/file/bot{clean_token}/{file_path_str}"

                    dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "tg-flowmap/0.1.0"})
                    with urllib.request.urlopen(dl_req, context=ctx, timeout=timeout) as dl_resp:
                        raw_bytes = dl_resp.read()

                    # Determine extension
                    ext = Path(file_path_str).suffix.lower() or ".webp"
                    target_file = cache_path / f"{custom_id}{ext}"
                    target_file.write_bytes(raw_bytes)

                    mime = "image/svg+xml" if ext == ".svg" else f"image/{ext.lstrip('.')}"
                    b64 = base64.b64encode(raw_bytes).decode("ascii")
                    data_url = f"data:{mime};base64,{b64}"
                    result_map[custom_id] = data_url

                except Exception:
                    continue

        except Exception as e:
            err_msg = str(e).replace(clean_token, "[REDACTED_TOKEN]")
            print(f"[WARN] Не удалось загрузить стикеры Telegram: {err_msg}", file=sys.stderr)

    return result_map
