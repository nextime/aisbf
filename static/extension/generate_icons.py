#!/usr/bin/env python3
"""
Generate PNG icons from SVG for the AISBF OAuth2 Relay extension.
"""
from PIL import Image, ImageDraw
import os

def create_icon(size):
    """Create a simple gradient icon with checkmark."""
    # Create image with transparency
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw gradient circle (simplified - solid color)
    color = (102, 126, 234, 255)  # #667eea
    margin = 2
    draw.ellipse([margin, margin, size-margin, size-margin], fill=color)
    
    # Draw checkmark (simplified)
    if size >= 48:
        line_width = max(2, size // 16)
        # Checkmark path
        points = [
            (size * 0.3, size * 0.5),
            (size * 0.45, size * 0.65),
            (size * 0.7, size * 0.35)
        ]
        draw.line(points, fill='white', width=line_width, joint='curve')
    
    return img

# Create icons directory if it doesn't exist
icons_dir = 'static/extension/icons'
os.makedirs(icons_dir, exist_ok=True)

# Generate icons
for size in [16, 48, 128]:
    icon = create_icon(size)
    icon.save(f'{icons_dir}/icon{size}.png', 'PNG')
    print(f'Created icon{size}.png')

print('All icons created successfully!')
