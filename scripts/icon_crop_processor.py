#!/usr/bin/env python3
"""
icon_crop_processor.py

将 1024x1024 图标原稿处理为 macOS 规范的圆角透明图标。

用法：
    python3 icon_crop_processor.py <输入文件路径> <输出文件路径>

示例：
    python3 icon_crop_processor.py input.png output.png

依赖：仅 Pillow（pip install Pillow）
"""

import sys
import os
from PIL import Image, ImageDraw


def process_icon(src_path: str, out_path: str):
    """处理图标原稿，输出透明背景的圆角矩形 PNG。"""

    # 检查输入文件
    if not os.path.exists(src_path):
        print(f"ERROR: 文件不存在: {src_path}")
        sys.exit(1)

    try:
        img = Image.open(src_path).convert("RGBA")
    except Exception as e:
        print(f"ERROR: 无法打开图片: {e}")
        sys.exit(1)

    if img.size != (1024, 1024):
        print(f"WARNING: 图片尺寸 {img.size}，不是 1024x1024")

    print(f"=== Step 1: 读取原图 ===")
    print(f"  尺寸: {img.size}")

    # Step 2: 识别圆角矩形边界
    w, h = img.size
    margin = (w - 824) // 2  # 100

    print(f"\n=== Step 2: 识别圆角矩形边界 ===")
    print(f"  假定边界: ({margin}, {margin}) 到 ({w - margin}, {h - margin})")
    print(f"  圆角矩形尺寸: 824x824")

    # Step 3: 裁切中心 824x824
    print(f"\n=== Step 3: 裁切中心 824x824 ===")
    cropped = img.crop((margin, margin, w - margin, h - margin))
    print(f"  裁切区域: ({margin},{margin}) 到 ({w-margin},{h-margin})")
    print(f"  裁切后尺寸: {cropped.size}")

    # Step 4: 抗锯齿圆角遮罩（supersampling x4）
    print(f"\n=== Step 4: 应用抗锯齿圆角遮罩 ===")

    small_w, small_h = 824, 824
    scale = 4
    big_w, big_h = small_w * scale, small_h * scale

    # 创建放大版遮罩（全黑 = 透明）
    big_mask = Image.new("L", (big_w, big_h), 0)
    draw_mask = ImageDraw.Draw(big_mask)

    # 绘制圆角矩形（radius = 185.4 * scale）
    big_radius = 185.4 * scale
    draw_mask.rounded_rectangle(
        (0, 0, big_w - 1, big_h - 1),
        radius=int(big_radius),
        fill=255
    )

    # 缩小回原始尺寸，使用 LANCZOS 抗锯齿
    small_mask = big_mask.resize((small_w, small_h), Image.LANCZOS)

    print(f"  放大倍数: {scale}x")
    print(f"  遮罩尺寸: {big_w}x{big_h} -> {small_w}x{small_h}")

    # 将裁切后的图像与遮罩合并
    result = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
    result.paste(cropped, (0, 0))

    # 逐像素应用遮罩（alpha 与遮罩值相乘）
    result_pixels = result.load()
    mask_pixels = small_mask.load()

    for y in range(small_h):
        for x in range(small_w):
            r, g, b, a = result_pixels[x, y]
            m = mask_pixels[x, y]
            new_a = int(a * m / 255)
            result_pixels[x, y] = (r, g, b, new_a)

    print(f"  圆角半径: 185.4px (抗锯齿)")

    # Step 5: 创建最终 1024x1024 透明画布，居中粘贴
    print(f"\n=== Step 5: 创建最终 1024x1024 画布 ===")
    final = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    offset_x = (1024 - small_w) // 2  # 0
    offset_y = (1024 - small_h) // 2  # 0
    final.paste(result, (offset_x, offset_y))

    print(f"  居中偏移: ({offset_x}, {offset_y})")
    print(f"  最终尺寸: {final.size}")

    # Step 6: 保存
    final.save(out_path, "PNG")

    print(f"\n=== Step 6: 保存结果 ===")
    print(f"  输出文件: {out_path}")
    print(f"  文件大小: {os.path.getsize(out_path)} bytes")

    # 验证
    verify = Image.open(out_path).convert("RGBA")
    v_pixels = verify.load()

    # 检查四个角是否透明
    corners = [(0, 0), (1023, 0), (0, 1023), (1023, 1023)]
    print(f"\n=== 验证 ===")
    all_corners_transparent = True
    for c in corners:
        r, g, b, a = v_pixels[c[0], c[1]]
        status = "透明" if a < 250 else f"不透明 (alpha={a})"
        print(f"  角 {c}: alpha={a} ({r},{g},{b}) — {status}")
        if a >= 250:
            all_corners_transparent = False

    # 检查圆角区域
    corner_radius_px = int(185.4)
    cut_corners = 0
    total_corner = 0
    for y in range(corner_radius_px):
        for x in range(corner_radius_px):
            dist = ((x - corner_radius_px) ** 2 + (y - corner_radius_px) ** 2)
            if dist <= corner_radius_px ** 2:
                total_corner += 1
                r, g, b, a = v_pixels[x, y]
                if a < 250:
                    cut_corners += 1

    print(f"\n圆角区域验证:")
    print(f"  圆角半径: {corner_radius_px}px")
    print(f"  圆角区域像素: {total_corner}")
    print(f"  被切掉（alpha < 250）: {cut_corners} ({cut_corners / total_corner * 100:.1f}%)")

    if all_corners_transparent:
        print(f"\n✓ 处理成功：四个角已透明，圆角完整")
    else:
        print(f"\n✗ 警告：部分角未完全透明")

    print(f"\n=== 处理完成 ===")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python3 icon_crop_processor.py <输入文件路径> <输出文件路径>")
        sys.exit(1)

    src_path = sys.argv[1]
    out_path = sys.argv[2]
    process_icon(src_path, out_path)
