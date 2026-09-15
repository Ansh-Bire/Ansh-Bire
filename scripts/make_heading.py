"""Draw a section-heading SVG in the profile's own typeface.

READMEs strip inline CSS, so headings can't be styled text in Markdown --
they're rendered as tiny SVGs instead, with the font subset and embedded
exactly like the portrait.

Usage:
    python make_heading.py "about" hd-about.svg
"""
import base64
import io
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FONT_PATH = Path(__file__).parent / "fonts" / "JetBrainsMono-Bold.ttf"
FONT_SIZE_PX = 22
PAD_X = 4
PAD_Y = 6
CHAR_ADVANCE_EM = 0.600


def subset_font_bytes(font_path: Path, characters: str) -> bytes:
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


def build_svg(label: str) -> str:
    text = f"// {label}"
    font_bytes = subset_font_bytes(FONT_PATH, text)
    font_b64 = base64.b64encode(font_bytes).decode("ascii")

    width = round(len(text) * CHAR_ADVANCE_EM * FONT_SIZE_PX) + PAD_X * 2
    height = FONT_SIZE_PX + PAD_Y * 2
    baseline = height - PAD_Y - round(FONT_SIZE_PX * 0.22)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<defs>
<style>
@font-face {{
  font-family: "HeadingMono";
  src: url(data:font/woff2;base64,{font_b64}) format("woff2");
}}
text {{
  font-family: "HeadingMono", monospace;
  font-size: {FONT_SIZE_PX}px;
  font-weight: 700;
  letter-spacing: 0.04em;
  fill: currentColor;
}}
</style>
</defs>
<text x="{PAD_X}" y="{baseline}">{text}</text>
</svg>
"""


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: make_heading.py <label> <output-svg>", file=sys.stderr)
        raise SystemExit(1)
    label, dst = sys.argv[1], Path(sys.argv[2])
    dst.write_text(build_svg(label), encoding="utf-8")
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
