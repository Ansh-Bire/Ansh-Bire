"""Convert a photo into an ASCII-style portrait SVG.

Usage:
    python make_portrait.py <input-image> <output-svg> [--cols N]

The image is downsampled to a character grid; each cell's brightness is
mapped onto a character ramp (quiet -> loud) and drawn as monospace text.
The font is embedded as base64 inside the SVG (via @font-face) so it
renders identically everywhere, since GitHub serves README-referenced
SVGs as standalone image resources (their own CSS is not stripped).
"""
import base64
import io
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image

RAMP = " .:-=+*#%@"
FONT_PATH = Path(__file__).parent / "fonts" / "JetBrainsMono-Regular.ttf"


def subset_font_bytes(font_path: Path, characters: str) -> bytes:
    """Strip the font down to just the glyphs this SVG actually draws."""
    font = TTFont(str(font_path))
    options = subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=characters)
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()

# JetBrains Mono's advance width is 0.600em; pair that with a 1.20em line
# height so the character grid maps to roughly square pixel blocks.
CHAR_ADVANCE_EM = 0.600
LINE_HEIGHT_EM = 1.20
FONT_SIZE_PX = 10


def image_to_grid(path: Path, cols: int) -> list[str]:
    img = Image.open(path).convert("L")
    w, h = img.size
    cell_w = w / cols
    # Compensate for character cells being taller than wide.
    cell_h = cell_w * (LINE_HEIGHT_EM / CHAR_ADVANCE_EM)
    rows = max(1, round(h / cell_h))
    small = img.resize((cols, rows), Image.LANCZOS)
    pixels = small.load()

    ramp_len = len(RAMP)
    lines = []
    for y in range(rows):
        line = []
        for x in range(cols):
            brightness = pixels[x, y]  # 0 (dark) .. 255 (light)
            # Dark pixels (the subject/shadow) get denser characters.
            idx = int((255 - brightness) / 256 * ramp_len)
            idx = min(idx, ramp_len - 1)
            line.append(RAMP[idx])
        lines.append("".join(line))
    return lines


def build_svg(lines: list[str], font_path: Path) -> str:
    cols = max(len(line) for line in lines)
    rows = len(lines)
    used_chars = "".join(sorted(set("".join(lines))))
    font_bytes = subset_font_bytes(font_path, used_chars)
    font_b64 = base64.b64encode(font_bytes).decode("ascii")

    width = round(cols * CHAR_ADVANCE_EM * FONT_SIZE_PX)
    height = round(rows * LINE_HEIGHT_EM * FONT_SIZE_PX)

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    text_rows = []
    for i, line in enumerate(lines):
        y = round((i + 0.85) * LINE_HEIGHT_EM * FONT_SIZE_PX)
        text_rows.append(f'<text x="0" y="{y}" xml:space="preserve">{esc(line)}</text>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<defs>
<style>
@font-face {{
  font-family: "PortraitMono";
  src: url(data:font/woff2;base64,{font_b64}) format("woff2");
}}
text {{
  font-family: "PortraitMono", monospace;
  font-size: {FONT_SIZE_PX}px;
  fill: currentColor;
  white-space: pre;
}}
</style>
</defs>
<rect width="100%" height="100%" fill="none"/>
<g>
{chr(10).join(text_rows)}
</g>
</svg>
"""
    return svg


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: make_portrait.py <input-image> <output-svg> [--cols N]", file=sys.stderr)
        raise SystemExit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    cols = 90
    if "--cols" in sys.argv:
        cols = int(sys.argv[sys.argv.index("--cols") + 1])

    lines = image_to_grid(src, cols)
    svg = build_svg(lines, FONT_PATH)
    dst.write_text(svg, encoding="utf-8")
    print(f"wrote {dst} ({cols} cols x {len(lines)} rows)")


if __name__ == "__main__":
    main()
