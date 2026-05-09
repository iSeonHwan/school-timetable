"""
앱 아이콘 생성기 (Python + Pillow)
실행: python installer/generate_icon.py

산출물:
  - installer/icon.png   (1024x1024)
  - installer/icon.icns  (macOS)
  - installer/icon.ico   (Windows)

사전 설치: pip install Pillow
"""
import os
import sys
import struct

INSTALLER_DIR = os.path.dirname(os.path.abspath(__file__))
PNG_PATH = os.path.join(INSTALLER_DIR, "icon.png")
ICNS_PATH = os.path.join(INSTALLER_DIR, "icon.icns")
ICO_PATH = os.path.join(INSTALLER_DIR, "icon.ico")

# Colors
PRIMARY = (27, 79, 138)      # #1B4F8A dark blue
ACCENT = (93, 173, 226)      # #5DADE2 light blue
WHITE = (255, 255, 255)
GREEN = (39, 174, 96)        # #27AE60


def create_icon_png():
    from PIL import Image, ImageDraw, ImageFont

    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rect background
    margin = 40
    bg_rect = [margin, margin, size - margin, size - margin]
    draw.rounded_rectangle(bg_rect, radius=120, fill=PRIMARY)

    # Inner lighter panel
    inner_margin = 120
    inner_rect = [inner_margin, inner_margin + 80, size - inner_margin, size - inner_margin - 40]
    draw.rounded_rectangle(inner_rect, radius=80, fill=(240, 247, 251))

    # Grid lines to represent timetable
    line_color = (200, 215, 230)
    grid_top = inner_rect[1] + 40
    grid_left = inner_rect[0] + 40
    grid_right = inner_rect[2] - 40
    grid_bottom = inner_rect[3] - 40
    rows = 5
    cols = 5
    row_h = (grid_bottom - grid_top) / rows
    col_w = (grid_right - grid_left) / cols

    for i in range(rows + 1):
        y = grid_top + i * row_h
        draw.line([(grid_left, y), (grid_right, y)], fill=line_color, width=4)

    for j in range(cols + 1):
        x = grid_left + j * col_w
        draw.line([(x, grid_top), (x, grid_bottom)], fill=line_color, width=4)

    # Fill some cells with accent colors to look like timetable entries
    cell_colors = [
        (0, 0, ACCENT), (2, 1, (155, 89, 182)), (3, 2, GREEN),
        (1, 3, (243, 156, 18)), (4, 2, ACCENT), (0, 4, (231, 76, 60)),
        (3, 0, GREEN), (1, 1, ACCENT),
    ]
    for col, row, color in cell_colors:
        x = grid_left + col * col_w + 6
        y = grid_top + row * row_h + 6
        draw.rounded_rectangle(
            [x, y, x + col_w - 12, y + row_h - 12],
            radius=16, fill=color
        )

    # Clock icon in the title area
    clock_cx = size // 2
    clock_cy = inner_margin + 40
    clock_r = 40
    draw.ellipse(
        [clock_cx - clock_r, clock_cy - clock_r,
         clock_cx + clock_r, clock_cy + clock_r],
        outline=PRIMARY, width=6
    )
    # Clock hands
    draw.line([(clock_cx, clock_cy), (clock_cx, clock_cy - 22)], fill=PRIMARY, width=5)
    draw.line([(clock_cx, clock_cy), (clock_cx + 16, clock_cy)], fill=ACCENT, width=4)

    # Text "시간표"
    try:
        # Try system Korean fonts
        font_paths = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/Library/Fonts/NanumGothic.ttf",
            "C:\\Windows\\Fonts\\malgun.ttf",
        ]
        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, 90)
                break
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "시간표", font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((size - tw) / 2, inner_rect[1] + 120), "시간표", fill=PRIMARY, font=font)

    img.save(PNG_PATH, "PNG")
    print(f"[생성] {PNG_PATH}")
    return img


def create_icns():
    """PNG를 macOS .icns로 변환"""
    if not os.path.exists(PNG_PATH):
        print("[오류] icon.png가 없습니다. 먼저 generate_icon.py를 실행하세요.")
        return

    from PIL import Image

    img = Image.open(PNG_PATH)

    # Required sizes for .icns
    sizes = {
        "ic07": 128,
        "ic08": 256,
        "ic09": 512,
        "ic10": 1024,
        "ic11": 32,
        "ic12": 64,
        "ic13": 256,
        "ic14": 512,
        "icp4": 16,
        "icp5": 32,
        "icp6": 64,
    }

    icon_data = []
    for os_type, s in sizes.items():
        if os_type.startswith("ic"):
            # Resize
            resized = img.resize((s, s), Image.LANCZOS)
            # Save as PNG bytes
            from io import BytesIO
            buf = BytesIO()
            resized.save(buf, format="PNG")
            raw = buf.getvalue()
            icon_data.append((os_type.encode("ascii"), raw))

    # Write .icns
    with open(ICNS_PATH, "wb") as f:
        # Magic + size
        total_size = 8 + sum(8 + len(d) for _, d in icon_data)
        f.write(b"icns" + struct.pack(">I", total_size))

        for os_type, data in icon_data:
            entry_size = 8 + len(data)
            f.write(os_type + struct.pack(">I", entry_size) + data)

    print(f"[생성] {ICNS_PATH}")


def create_ico():
    """PNG를 Windows .ico로 변환"""
    if not os.path.exists(PNG_PATH):
        print("[오류] icon.png가 없습니다. 먼저 generate_icon.py를 실행하세요.")
        return

    from PIL import Image

    img = Image.open(PNG_PATH)
    sizes = [16, 32, 48, 64, 128, 256]

    ico_images = []
    for s in sizes:
        resized = img.resize((s, s), Image.LANCZOS)
        ico_images.append(resized)

    ico_images[0].save(
        ICO_PATH, format="ICO", sizes=[(s, s) for s in sizes],
        append_images=ico_images[1:]
    )
    print(f"[생성] {ICO_PATH}")


if __name__ == "__main__":
    print("앱 아이콘 생성 중...")
    print()

    try:
        create_icon_png()
        create_icns()
        create_ico()
        print()
        print("완료! 아이콘 파일이 installer/ 디렉터리에 생성되었습니다.")
    except ImportError:
        print("[오류] Pillow 라이브러리가 필요합니다.")
        print("       pip install Pillow")
        sys.exit(1)
