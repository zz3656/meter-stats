#!/usr/bin/env python3
"""
生成电表 macOS app 图标。

设计:
- 背景:Linear 风格深色 #08090a 圆角矩形(带轻微内阴影营造立体感)
- 主体:紫罗兰色 #7170ff → #5e6ad2 渐变的闪电符号
- 点缀:4 颗小圆点(对应 4 块电表),用各自代表色

输出:
- Assets/AppIcon.iconset/*.png (10 个规格)
- Assets/AppIcon.icns (iconutil 生成)
- 拷贝到 ~/Applications/电表.app/Contents/Resources/AppIcon.icns
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import math
import subprocess

ICON_DIR = Path(__file__).resolve().parent.parent / "Assets"
ICONSET = ICON_DIR / "AppIcon.iconset"
ICNS_OUT = ICON_DIR / "AppIcon.icns"

# Linear 主题色
BG_TOP = (16, 17, 22)        # 略亮一点
BG_BOTTOM = (8, 9, 10)       # #08090a
ACCENT_LIGHT = (113, 112, 255)  # #7170ff
ACCENT_DARK = (94, 106, 210)    # #5e6ad2

# 4 块表代表色(对应网页 Linear 主题配色)
METER_COLORS = [
    (96, 165, 250),   # 大厅 - 蓝
    (248, 113, 113),  # 消防 - 红
    (74, 222, 128),   # 包厢 - 绿
    (251, 191, 36),   # 空调 - 橙
]


def make_canvas(size: int) -> Image.Image:
    """1024x1024 透明底 — 实际 macOS app 图标外圈会被系统圆角裁剪,
    但我们仍然画圆角矩形,内边距 ~10% 以保证 macOS 渲染安全区"""
    return Image.new("RGBA", (size, size), (0, 0, 0, 0))


def draw_rounded_bg(canvas: Image.Image, color_top, color_bottom, radius_ratio=0.223):
    """画圆角矩形 + 垂直渐变背景。

    macOS 图标安全区规范:视觉主体占中心 ~80%(每边留 ~10% 透明边),
    系统会自动裁掉外圈 + 套系统圆角。背景不能铺满整个画布,否则
    看起来比别的图标大一圈。
    """
    size = canvas.size[0]
    margin = size * 0.10          # 每边留 10% 安全边
    x0, y0 = margin, margin
    x1, y1 = size - 1 - margin, size - 1 - margin
    w = x1 - x0
    radius = int(w * radius_ratio)

    # 垂直渐变(只画在背景区域内,避免颜色渗到圆角外)
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(int(y0), int(y1) + 1):
        t = (y - y0) / w
        r = int(color_top[0] * (1 - t) + color_bottom[0] * t)
        g = int(color_top[1] * (1 - t) + color_bottom[1] * t)
        b = int(color_top[2] * (1 - t) + color_bottom[2] * t)
        gd.line([(x0, y), (x1, y)], fill=(r, g, b))

    # 圆角 mask(背景区域)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(x0, y0), (x1, y1)], radius=radius, fill=255
    )
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg.paste(grad, (0, 0), mask)

    canvas.alpha_composite(bg)


def draw_bolt(canvas: Image.Image, color_light, color_dark):
    """画闪电符号 — SF Symbol bolt.fill 风格,6 点 Z 字 polygon。
    设计原则:
    - 顶尖/底尖在中轴上(关于 cx 居中)
    - 整体瘦长(高宽比 > 1.5)
    - 两道台阶垂直间距大,形成明显的 Z 字锯齿
    - 位置偏上(cy=0.40),给下方柱状图留空间
    """
    size = canvas.size[0]
    cx = size / 2
    s = size
    cy = s * 0.40

    h = s * 0.26    # 顶尖/底尖到中心(瘦长)
    w = s * 0.24    # 凸出宽度

    pts = [
        (cx,            cy - h * 0.95),         # 顶尖(中轴)
        (cx + w * 0.60, cy - h * 0.40),         # 右上凸(上半腰位置)
        (cx - w * 0.20, cy - h * 0.40),         # 中右内凹
        (cx - w * 0.10, cy + h * 0.95),         # 底尖(略偏左,Z 字动感)
        (cx - w * 0.60, cy + h * 0.05),         # 左下凸(下半腰位置,拉开间距)
        (cx + w * 0.20, cy + h * 0.05),         # 中左内凹
    ]

    # 渐变填充
    grad = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    for y in range(s):
        t = y / s
        r = int(color_light[0] * (1 - t) + color_dark[0] * t)
        g = int(color_light[1] * (1 - t) + color_dark[1] * t)
        b = int(color_light[2] * (1 - t) + color_dark[2] * t)
        ImageDraw.Draw(grad).line([(0, y), (s, y)], fill=(r, g, b, 255))

    bolt_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(bolt_layer).polygon(pts, fill=(255, 255, 255, 255))

    mask = bolt_layer.split()[3]
    grad.putalpha(mask)
    canvas.alpha_composite(grad)


def draw_bars(canvas: Image.Image, colors):
    """底部 4 根彩色柱状图(对应 4 块电表),高度从左到右递增。
    代表「用电统计」功能 — 和当月统计/月度报告的 4 表色一致。
    """
    size = canvas.size[0]
    bar_bottom = size * 0.87
    bar_width = size * 0.13
    heights = [size * 0.10, size * 0.17, size * 0.24, size * 0.31]  # 递增
    centers = [size * 0.28, size * 0.44, size * 0.60, size * 0.76]

    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for cx, h, color in zip(centers, heights, colors):
        top = bar_bottom - h
        d.rounded_rectangle(
            [(cx - bar_width / 2, top), (cx + bar_width / 2, bar_bottom)],
            radius=size * 0.025,
            fill=(*color, 255),
        )
    # 轻微模糊让边缘柔和
    layer = layer.filter(ImageFilter.GaussianBlur(radius=size * 0.003))
    canvas.alpha_composite(layer)


def build_icon(size: int) -> Image.Image:
    canvas = make_canvas(size)
    draw_rounded_bg(canvas, BG_TOP, BG_BOTTOM)
    draw_bolt(canvas, ACCENT_LIGHT, ACCENT_DARK)
    draw_bars(canvas, METER_COLORS)
    return canvas


def main():
    ICONSET.mkdir(parents=True, exist_ok=True)

    sizes = [
        (16, "16x16"),
        (32, "16x16@2x"),
        (32, "32x32"),
        (64, "32x32@2x"),
        (128, "128x128"),
        (256, "128x128@2x"),
        (256, "256x256"),
        (512, "256x256@2x"),
        (512, "512x512"),
        (1024, "512x512@2x"),
    ]

    for px, name in sizes:
        img = build_icon(px)
        out = ICONSET / f"icon_{name}.png"
        img.save(out, "PNG")
        print(f"  wrote {out.name} ({px}x{px})")

    # iconutil 把 .iconset 合成 .icns
    print(f"\n==> iconutil -> {ICNS_OUT}")
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS_OUT)],
        check=True,
    )
    print(f"    done, size: {ICNS_OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()