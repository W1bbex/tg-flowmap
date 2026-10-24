from __future__ import annotations

# DAST components (Dynamic Application Security / Structure Testing via Telethon)
# Lazy loaded to preserve zero-runtime dependencies when only using SAST.

def is_dast_available() -> bool:
    try:
        import telethon  # noqa: F401
        return True
    except ImportError:
        return False
