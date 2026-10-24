from __future__ import annotations

import json
from pathlib import Path

from tg_flowmap.core.models import BotMap


class HtmlVisualizer:
    def __init__(self, bot_map: BotMap):
        self.bot_map = bot_map
        self.templates_dir = Path(__file__).resolve().parent / "templates"

    def render(self, output_path: Path) -> None:
        """Renders an interactive, standalone single-file HTML visualization."""
        html_template_file = self.templates_dir / "viewer.html"
        css_file = self.templates_dir / "viewer.css"
        js_file = self.templates_dir / "viewer.js"

        html_template = html_template_file.read_text(encoding="utf-8")
        css_content = css_file.read_text(encoding="utf-8")
        js_content = js_file.read_text(encoding="utf-8")

        # Escape </ to prevent premature </script> closing and DOM XSS in browser HTML parser
        data_json = json.dumps(self.bot_map.to_dict(), ensure_ascii=False).replace("</", "<\\/")

        # Inject styles and scripts into the template first, then inject serialized data JSON
        html_output = html_template.replace("/* __STYLES__ */", css_content)
        html_output = html_output.replace("/* __SCRIPTS__ */", js_content)
        html_output = html_output.replace("__DATA_JSON__", data_json)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_output, encoding="utf-8")
