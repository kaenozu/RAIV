from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "assets" / "readme"
SOURCE_IMAGE_PATH = ROOT_DIR / "tests" / "data" / "regression" / "sample_alpha.ppm"
KEYCONFIG_SCREENSHOT_PATH = OUTPUT_DIR / "key-config.png"
KEYCAPTURE_SCREENSHOT_PATH = OUTPUT_DIR / "key-config-dialog.png"
COMPARE_GIF_PATH = OUTPUT_DIR / "compare-mode.gif"
FONT_DIR = Path("C:/Windows/Fonts")
FONT_CANDIDATES = {
    False: [FONT_DIR / "segoeui.ttf", FONT_DIR / "arial.ttf"],
    True: [FONT_DIR / "segoeuib.ttf", FONT_DIR / "arialbd.ttf"],
}
KEYCONFIG_ROWS = [
    ("Open image", "O", "Left click"),
    ("Open folder", "F", "Right click"),
    ("Next page", "Right", "Wheel down"),
    ("Previous page", "Left", "Wheel up"),
    ("Jump to last page", "End", "Forward button"),
    ("Jump to first page", "Home", "Back button"),
    ("Toggle fullscreen", "F11", "Middle click"),
    ("Toggle compare mode", "C", "Unassigned"),
    ("Actual size", "1", "Right double click"),
    ("Fit to window", "0", "Left double click"),
    ("Rotate right", "R", "Unassigned"),
    ("Rotate left", "L", "Unassigned"),
    ("Flip horizontal", "H", "Unassigned"),
    ("Flip vertical", "V", "Unassigned"),
]


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES[bold]:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def draw_centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.ImageFont, fill: str) -> None:
    width, height = measure_text(draw, text, font)
    x = box[0] + max(0, (box[2] - box[0] - width) // 2)
    y = box[1] + max(0, (box[3] - box[1] - height) // 2)
    draw.text((x, y), text, font=font, fill=fill)


def draw_button(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.ImageFont, *, fill: str = "#f6f7f9", outline: str = "#b8bcc4", text_fill: str = "#20242b") -> None:
    draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=1)
    draw_centered_text(draw, box, text, font, text_fill)


def draw_checkbox(draw: ImageDraw.ImageDraw, xy: tuple[int, int], checked: bool, label: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    box = (x, y, x + 16, y + 16)
    draw.rectangle(box, outline="#8d95a3", width=1, fill="#ffffff")
    if checked:
        draw.line((x + 3, y + 8, x + 7, y + 12, x + 13, y + 3), fill="#2f6fed", width=2)
    draw.text((x + 24, y - 2), label, font=font, fill="#1d2128")


def build_compare_images() -> tuple[Image.Image, Image.Image]:
    source = Image.open(SOURCE_IMAGE_PATH).convert("RGBA")
    processed = source.copy()
    tint = Image.new("RGBA", processed.size, (0, 60, 120, 56))
    processed = Image.alpha_composite(processed, tint)
    draw = ImageDraw.Draw(processed)
    if processed.width >= 4 and processed.height >= 4:
        draw.rectangle((1, 1, processed.width - 2, processed.height - 2), outline="#ffcc66", width=1)
    return source, processed


def render_key_config_overview() -> None:
    image = Image.new("RGBA", (1260, 920), "#f3f5f7")
    draw = ImageDraw.Draw(image)
    font_regular = load_font(20)
    font_small = load_font(16)
    font_bold = load_font(24, bold=True)
    font_tab = load_font(18, bold=True)

    draw.rounded_rectangle((0, 0, 1259, 919), radius=18, fill="#f3f5f7", outline="#d4d8df")
    draw.text((28, 22), "Settings", font=font_bold, fill="#11151b")
    draw_button(draw, (1032, 18, 1212, 58), "Pinned", font_small)

    tabs = [
        ("Engine", (24, 84, 170, 124), False),
        ("General", (176, 84, 320, 124), False),
        ("Key Config", (326, 78, 528, 124), True),
    ]
    for label, box, selected in tabs:
        fill = "#ffffff" if selected else "#eaedf1"
        outline = "#c9ced7" if selected else "#d6dbe3"
        draw.rounded_rectangle(box, radius=10, fill=fill, outline=outline)
        draw_centered_text(draw, box, label, font_tab, "#1b2027")

    panel = (24, 136, 1218, 892)
    draw.rectangle(panel, fill="#ffffff", outline="#c9ced7")
    draw.text((44, 154), "Click a binding to change it. Press Esc to clear it. Space and Backspace stay fixed.", font=font_regular, fill="#2f3640")

    header_y = 210
    draw.text((48, header_y), "Action", font=font_bold, fill="#151922")
    draw.text((484, header_y), "Keyboard", font=font_bold, fill="#151922")
    draw.text((842, header_y), "Mouse", font=font_bold, fill="#151922")

    start_y = 254
    row_height = 42
    for index, (action, keyboard, mouse) in enumerate(KEYCONFIG_ROWS):
        y = start_y + index * row_height
        if index % 2 == 0:
            draw.rectangle((38, y - 6, 1200, y + 28), fill="#fafbfd")
        draw.text((48, y), action, font=font_regular, fill="#20242b")
        keyboard_fill = "#f6f7f9"
        keyboard_outline = "#b8bcc4"
        mouse_fill = "#f6f7f9"
        mouse_outline = "#b8bcc4"
        if action == "Toggle compare mode":
            mouse = "Duplicate: Middle click"
            mouse_fill = "#7a2020"
            mouse_outline = "#ffcc66"
        draw_button(draw, (438, y - 4, 756, y + 28), keyboard, font_small, fill=keyboard_fill, outline=keyboard_outline, text_fill="#20242b")
        draw_button(draw, (790, y - 4, 1170, y + 28), mouse, font_small, fill=mouse_fill, outline=mouse_outline, text_fill="#ffffff" if action == "Toggle compare mode" else "#20242b")

    draw_button(draw, (48, 830, 1170, 874), "Reset key config to defaults", font_regular)
    image.save(KEYCONFIG_SCREENSHOT_PATH)


def render_key_capture_dialog() -> None:
    image = Image.new("RGBA", (560, 190), "#eef1f4")
    draw = ImageDraw.Draw(image)
    font_regular = load_font(20)
    font_small = load_font(16)
    font_bold = load_font(18, bold=True)

    draw.rounded_rectangle((0, 0, 559, 189), radius=16, fill="#eef1f4", outline="#cfd5dd")
    draw.text((18, 16), "Next page - Keyboard", font=font_bold, fill="#171b21")
    draw_button(draw, (18, 46, 540, 82), "Click here, then press a key", font_small)
    draw_checkbox(draw, (20, 98), True, "Ctrl", font_small)
    draw_checkbox(draw, (118, 98), False, "Shift", font_small)
    draw_checkbox(draw, (230, 98), False, "Alt", font_small)
    draw.text((20, 132), "Current: Ctrl+Right", font=font_regular, fill="#1f252d")
    draw_button(draw, (182, 142, 306, 176), "OK", font_small, fill="#dce9ff", outline="#5d8ae8")
    draw_button(draw, (326, 142, 460, 176), "Cancel", font_small)
    image.save(KEYCAPTURE_SCREENSHOT_PATH)


def render_compare_gif() -> None:
    source, processed = build_compare_images()
    scale = max(1, 960 // max(1, source.width))
    render_size = (source.width * scale, source.height * scale)
    source = source.resize(render_size, Image.Resampling.NEAREST)
    processed = processed.resize(render_size, Image.Resampling.NEAREST)
    width, height = render_size
    original_small, processed_small = build_compare_images()
    original_small = original_small.convert("RGBA")
    processed_small = processed_small.convert("RGBA")
    diff_points: list[tuple[int, int]] = []
    for y in range(original_small.height):
        for x in range(original_small.width):
            left = original_small.getpixel((x, y))
            right = processed_small.getpixel((x, y))
            diff = abs(left[0] - right[0]) + abs(left[1] - right[1]) + abs(left[2] - right[2])
            if diff >= 24 * 3:
                diff_points.append((x, y))

    header_height = 60
    font_regular = load_font(18)
    font_small = load_font(15)
    frames: list[Image.Image] = []
    for split in (120, 300, 500, 700, 880, 700, 500, 300):
        split_x = max(1, min(width - 1, round(width * split / 1000)))
        frame = Image.new("RGBA", (width, height + header_height), "#12151b")
        composed = Image.new("RGBA", (width, height), "#000000")
        composed.paste(source.crop((0, 0, split_x, height)), (0, 0))
        composed.paste(processed.crop((split_x, 0, width, height)), (split_x, 0))
        for x, y in diff_points:
            sx = x * scale
            sy = y * scale
            for dx in range(scale):
                for dy in range(scale):
                    px = sx + dx
                    py = sy + dy
                    if 0 <= px < width and 0 <= py < height:
                        composed.putpixel((px, py), (255, 96, 0, 220))
        frame.paste(composed, (0, header_height))
        draw = ImageDraw.Draw(frame)
        draw.text((12, 10), "RAIV Compare Mode", font=font_regular, fill="#ffffff")
        draw.text((12, 34), "Original", font=font_small, fill="#d3def7")
        draw.text((width - 120, 34), "Processed", font=font_small, fill="#ffd6a3")
        draw.line((split_x, header_height, split_x, height + header_height), fill="#ffffff", width=3)
        frames.append(frame)

    frames[0].save(
        COMPARE_GIF_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=180,
        loop=0,
        optimize=False,
    )


def main() -> int:
    ensure_output_dir()
    render_key_config_overview()
    render_key_capture_dialog()
    render_compare_gif()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
