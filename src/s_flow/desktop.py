"""Desktop entry point for S-Flow."""

from __future__ import annotations

from sovereign import desktop_main

from .application import APPLICATION_MANIFEST


APPLICATION_ALIASES = {
    "flow": {
        "app_module": "s_flow.application",
        "application_id": APPLICATION_MANIFEST.application_id,
        "asset_package": APPLICATION_MANIFEST.asset_package,
        "ui_file": APPLICATION_MANIFEST.ui_file,
        "css_file": APPLICATION_MANIFEST.css_file,
    },
}


def main(argv: list[str] | None = None) -> int:
    return desktop_main(
        argv, "flow", APPLICATION_MANIFEST.display_name,
        APPLICATION_ALIASES,
    )


if __name__ == "__main__":
    raise SystemExit(main())

