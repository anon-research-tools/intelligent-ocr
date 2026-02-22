#!/usr/bin/env python3
"""
Generate application icons for OCR Tool
Creates icon.png (1024x1024), icon.icns (macOS), and icon.ico (Windows)

Design: Document + magnifying glass/OCR text on nature green background
"""
import os
import sys
from pathlib import Path

# Ensure PIL is available
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow not installed. Run: pip install Pillow")
    sys.exit(1)

# Project paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RESOURCES_DIR = PROJECT_DIR / "desktop" / "resources"

# Design colors (matching styles.py)
COLORS = {
    'accent_primary': '#3D8A5A',  # Nature green
    'accent_hover': '#2D6A44',
    'bg_surface': '#FFFFFF',
    'text_primary': '#1A1918',
}


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def create_icon(size=1024):
    """Create the application icon"""
    # Create canvas with transparent background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Calculate dimensions
    margin = int(size * 0.08)
    corner_radius = int(size * 0.18)

    # Draw rounded rectangle background (green)
    green = hex_to_rgb(COLORS['accent_primary'])
    draw_rounded_rect(
        draw,
        (margin, margin, size - margin, size - margin),
        corner_radius,
        fill=green + (255,)
    )

    # Draw document icon (white)
    doc_margin = int(size * 0.22)
    doc_width = int(size * 0.45)
    doc_height = int(size * 0.55)
    doc_x = int(size * 0.18)
    doc_y = int(size * 0.22)

    # Document with folded corner
    white = hex_to_rgb(COLORS['bg_surface'])
    fold_size = int(size * 0.1)

    # Main document body (with corner fold effect)
    doc_points = [
        (doc_x, doc_y),
        (doc_x + doc_width - fold_size, doc_y),
        (doc_x + doc_width, doc_y + fold_size),
        (doc_x + doc_width, doc_y + doc_height),
        (doc_x, doc_y + doc_height),
    ]
    draw.polygon(doc_points, fill=white + (255,))

    # Folded corner triangle
    fold_color = hex_to_rgb(COLORS['accent_hover'])
    fold_points = [
        (doc_x + doc_width - fold_size, doc_y),
        (doc_x + doc_width, doc_y + fold_size),
        (doc_x + doc_width - fold_size, doc_y + fold_size),
    ]
    draw.polygon(fold_points, fill=fold_color + (200,))

    # Draw text lines on document
    line_color = hex_to_rgb(COLORS['accent_primary'])
    line_y_start = doc_y + int(size * 0.12)
    line_height = int(size * 0.06)
    line_x_start = doc_x + int(size * 0.04)
    line_widths = [0.32, 0.28, 0.35, 0.20]  # Varying line widths

    for i, width_factor in enumerate(line_widths):
        y = line_y_start + i * line_height
        if y + int(size * 0.02) < doc_y + doc_height - int(size * 0.04):
            draw.rounded_rectangle(
                (line_x_start, y, line_x_start + int(size * width_factor), y + int(size * 0.025)),
                radius=int(size * 0.01),
                fill=line_color + (180,)
            )

    # Draw magnifying glass (OCR symbol)
    mag_center_x = int(size * 0.68)
    mag_center_y = int(size * 0.62)
    mag_radius = int(size * 0.18)
    mag_stroke = int(size * 0.04)

    # Glass circle (white with green border)
    draw.ellipse(
        (mag_center_x - mag_radius, mag_center_y - mag_radius,
         mag_center_x + mag_radius, mag_center_y + mag_radius),
        fill=white + (240,),
        outline=white + (255,),
        width=mag_stroke
    )

    # Handle
    handle_length = int(size * 0.15)
    handle_angle_x = int(handle_length * 0.7)
    handle_angle_y = int(handle_length * 0.7)

    draw.line(
        (mag_center_x + int(mag_radius * 0.7), mag_center_y + int(mag_radius * 0.7),
         mag_center_x + int(mag_radius * 0.7) + handle_angle_x,
         mag_center_y + int(mag_radius * 0.7) + handle_angle_y),
        fill=white + (255,),
        width=mag_stroke
    )

    # "OCR" text inside magnifying glass
    try:
        # Try to use a system font
        font_size = int(size * 0.06)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    text = "OCR"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    draw.text(
        (mag_center_x - text_width // 2, mag_center_y - text_height // 2 - int(size * 0.01)),
        text,
        fill=line_color + (255,),
        font=font
    )

    return img


def draw_rounded_rect(draw, coords, radius, fill):
    """Draw a rounded rectangle"""
    x1, y1, x2, y2 = coords
    draw.rounded_rectangle(coords, radius=radius, fill=fill)


def create_iconset(icon_img, output_dir):
    """Create macOS .iconset directory with all required sizes"""
    iconset_dir = output_dir / "icon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    # Required sizes for macOS iconset
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    for size, filename in sizes:
        resized = icon_img.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / filename, "PNG")
        print(f"  Created {filename}")

    return iconset_dir


def create_ico(icon_img, output_path):
    """Create Windows .ico file with multiple sizes"""
    # ICO sizes (Windows standard)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icons = []

    for size in sizes:
        resized = icon_img.resize((size, size), Image.Resampling.LANCZOS)
        icons.append(resized)

    # Save as ICO with multiple sizes
    icon_img.save(output_path, format='ICO', sizes=[(s, s) for s in sizes])
    print(f"  Created {output_path.name}")


def main():
    """Generate all icon files"""
    print("Generating application icons...")

    # Ensure resources directory exists
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

    # Create the main icon
    print("\n1. Creating base icon (1024x1024)...")
    icon = create_icon(1024)

    # Save PNG
    png_path = RESOURCES_DIR / "icon.png"
    icon.save(png_path, "PNG")
    print(f"  Saved: {png_path}")

    # Create macOS iconset
    print("\n2. Creating macOS iconset...")
    iconset_dir = create_iconset(icon, RESOURCES_DIR)

    # Convert to .icns using iconutil (macOS only)
    icns_path = RESOURCES_DIR / "icon.icns"
    if sys.platform == "darwin":
        print("\n3. Converting to .icns...")
        result = os.system(f"iconutil -c icns '{iconset_dir}' -o '{icns_path}'")
        if result == 0:
            print(f"  Created: {icns_path}")
            # Clean up iconset directory
            import shutil
            shutil.rmtree(iconset_dir)
        else:
            print("  Warning: iconutil failed. Please manually convert iconset to icns.")
    else:
        print("\n3. Skipping .icns creation (not on macOS)")
        print(f"   Run on macOS: iconutil -c icns '{iconset_dir}' -o '{icns_path}'")

    # Create Windows ICO
    print("\n4. Creating Windows .ico...")
    ico_path = RESOURCES_DIR / "icon.ico"
    create_ico(icon, ico_path)

    print("\n✓ Icon generation complete!")
    print(f"\nOutput files in: {RESOURCES_DIR}")
    for f in RESOURCES_DIR.iterdir():
        if f.suffix in ['.png', '.icns', '.ico']:
            print(f"  - {f.name}")


if __name__ == "__main__":
    main()
