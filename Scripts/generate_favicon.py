#!/usr/bin/env python3
"""
生成工程管理部系统的 favicon。

设计:
- 背景: 深蓝色圆角矩形 #1a1b2e → #0f1020 渐变
- 闪电: 紫罗兰色渐变 #7170ff → #5e6ad2
- 底部: 4 根彩色柱状图(蓝/红/绿/橙,对应 4 块电表)
- 输出: favicon.svg (矢量) + favicon-32.png + favicon-16.png

输出位置:
- Sources/Linclub/Resources/favicon.svg
- Sources/Linclub/Resources/favicon-32.png
- Sources/Linclub/Resources/favicon-16.png
- docker/favicon.svg (同步副本)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import math
import os

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
WEB_DIR = ROOT / "Sources" / "Linclub" / "Resources"
DOCKER_DIR = ROOT / "docker"

# 主题色
BG_TOP = (26, 27, 46)       # #1a1b2e
BG_BOTTOM = (15, 16, 32)    # #0f1020
ACCENT_LIGHT = (113, 112, 255)  # #7170ff
ACCENT_DARK = (94, 106, 210)    # #5e6ad2

METER_COLORS = [
    (96, 165, 250),   # 大厅 - 蓝
    (248, 113, 113),  # 消防 - 红
    (74, 222, 128),   # 包厢 - 绿
    (251, 191, 36),   # 空调 - 黄/橙
]

OUTPUT_FILES = {
    "svg": WEB_DIR / "favicon.svg",
    "png32": WEB_DIR / "favicon-32.png",
    "png16": WEB_DIR / "favicon-16.png",
}


def draw_bolt_points(size, cx, cy):
    """返回闪电多边形的顶点坐标。"""
    s = size
    h = s * 0.26
    w = s * 0.24

    pts = [
        (cx, cy - h * 0.95),
        (cx + w * 0.60, cy - h * 0.40),
        (cx - w * 0.20, cy - h * 0.40),
        (cx - w * 0.10, cy + h * 0.95),
        (cx - w * 0.60, cy + h * 0.05),
        (cx + w * 0.20, cy + h * 0.05),
    ]
    return pts


def create_icon(size):
    """创建图标图像 (RGBA, 指定 size)。"""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    margin = size * 0.10
    x0, y0 = margin, margin
    x1, y1 = size - 1 - margin, size - 1 - margin
    w = x1 - x0
    radius = int(w * 0.223)

    # 背景渐变
    for y in range(int(y0), int(y1) + 1):
        t = (y - y0) / w if w > 0 else 0
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        d.line([(x0, y), (x1, y)], fill=(r, g, b))

    # 圆角矩形
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([(x0, y0), (x1, y1)], radius=radius, fill=255)
    masked = canvas.copy()
    masked.putalpha(mask)
    canvas = masked

    # 闪电渐变 + 多边形
    cx = size / 2
    cy = size * 0.40
    pts = draw_bolt_points(size, cx, cy)

    bolt_grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bolt_grad)
    for y in range(size):
        t = y / size
        r = int(ACCENT_LIGHT[0] * (1 - t) + ACCENT_DARK[0] * t)
        g = int(ACCENT_LIGHT[1] * (1 - t) + ACCENT_DARK[1] * t)
        b = int(ACCENT_LIGHT[2] * (1 - t) + ACCENT_DARK[2] * t)
        bd.line([(0, y), (size, y)], fill=(r, g, b, 255))

    bolt_mask = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bmd = ImageDraw.Draw(bolt_mask)
    bmd.polygon(pts, fill=(255, 255, 255, 255))
    bolt_mask.putalpha(bolt_mask.split()[3])

    # 复合渐变 + 闪电
    bolt_colored = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bolt_colored.paste(bolt_grad, (0, 0), bolt_mask.split()[3])
    canvas.alpha_composite(bolt_colored)

    # 柱状图
    bar_bottom = size * 0.87
    bar_width = size * 0.13
    heights = [size * 0.10, size * 0.17, size * 0.24, size * 0.31]
    centers = [size * 0.28, size * 0.44, size * 0.60, size * 0.76]

    for bar_cx, h, color in zip(centers, heights, METER_COLORS):
        top = bar_bottom - h
        d.rounded_rectangle(
            [(bar_cx - bar_width / 2, top), (bar_cx + bar_width / 2, bar_bottom)],
            radius=size * 0.025,
            fill=(*color, 255),
        )

    return canvas


def create_svg():
    """生成 SVG 格式的 favicon (矢量, 可缩放)。"""
    # 背景圆角矩形
    bg_x, bg_y = 0.10, 0.10
    bg_w, bg_h = 0.80, 0.80
    bg_rx = 0.223

    # 闪电多边形 (viewBox 0 0 100 100)
    cx = 50
    cy = 40
    bolt_pts = [
        f"{cx},{cy - 26*0.95}",
        f"{cx + 24*0.60},{cy - 26*0.40}",
        f"{cx - 24*0.20},{cy - 26*0.40}",
        f"{cx - 24*0.10},{cy + 26*0.95}",
        f"{cx - 24*0.60},{cy + 26*0.05}",
        f"{cx + 24*0.20},{cy + 26*0.05}",
    ]

    # 柱状图 (相对 viewBox)
    bars = [
        {"cx": 28, "h": 10, "w": 13, "color": "#60a5fa"},
        {"cx": 44, "h": 17, "w": 13, "color": "#f87171"},
        {"cx": 60, "h": 24, "w": 13, "color": "#4ade80"},
        {"cx": 76, "h": 31, "w": 13, "color": "#fbbf24"},
    ]

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="512" height="512">
  <defs>
    <!-- 背景渐变 -->
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1a1b2e"/>
      <stop offset="100%" stop-color="#0f1020"/>
    </linearGradient>
    <!-- 闪电渐变 -->
    <linearGradient id="bolt" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#7170ff"/>
      <stop offset="100%" stop-color="#5e6ad2"/>
    </linearGradient>
    <!-- 圆角矩形 clip -->
    <clipPath id="rc">
      <rect x="{bg_x*100}" y="{bg_y*100}" width="{bg_w*100}" height="{bg_h*100}" rx="{bg_rx*100}" ry="{bg_rx*100}"/>
    </clipPath>
  </defs>
  <!-- 背景 -->
  <g clip-path="url(#rc)">
    <rect x="0" y="0" width="100" height="100" fill="url(#bg)"/>
  </g>
  <!-- 闪电 -->
  <polygon points="{' '.join(bolt_pts)}" fill="url(#bolt)" clip-path="url(#rc)"/>
  <!-- 柱状图 -->
  <g clip-path="url(#rc)">'''

    for bar in bars:
        bar_rect_y = 87 - bar["h"]
        svg += f'''
    <rect x="{bar['cx'] - bar['w']/2}" y="{bar_rect_y}" width="{bar['w']}" height="{bar['h']}" rx="2.5" fill="{bar['color']}"/>'''

    svg += f'''
  </g>
</svg>'''
    return svg


def main():
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 生成 SVG favicon
    svg_content = create_svg()
    svg_path = OUTPUT_FILES["svg"]
    svg_path.write_text(svg_content, encoding="utf-8")
    print(f"  ✓ wrote {svg_path.name}")

    # 2. 生成 PNG 32x32
    img_32 = create_icon(32)
    png32_path = OUTPUT_FILES["png32"]
    img_32.save(png32_path, "PNG")
    print(f"  ✓ wrote {png32_path.name}")

    # 3. 生成 PNG 16x16
    img_16 = create_icon(16)
    png16_path = OUTPUT_FILES["png16"]
    img_16.save(png16_path, "PNG")
    print(f"  ✓ wrote {png16_path.name}")

    # 4. 同步副本到 docker/ 目录
    for d in [DOCKER_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        for src_name, dst_name in [("favicon.svg", "favicon.svg"), ("favicon-32.png", "favicon-32.png"), ("favicon-16.png", "favicon-16.png")]:
            src = WEB_DIR / src_name
            dst = d / dst_name
            if src.exists():
                dst.write_bytes(src.read_bytes())
                print(f"  ✓ synced {dst_name} to docker/")

    print(f"\n==> Done! Favicon files:")
    for name, path in OUTPUT_FILES.items():
        size = path.stat().st_size if path.exists() else 0
        print(f"    {path.name}: {size} bytes")


if __name__ == "__main__":
    main()
