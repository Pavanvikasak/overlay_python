
import re
import sys

# Attempt to load PDF engines (optional)
try:
    import cairosvg
    HAS_CAIRO = True
except:
    HAS_CAIRO = False

def process_svg_string(svg_text, target_color):
    """
    String-based replacement for high performance on 55MB+ SVGs.
    Targets only Black variations and converts all White to transparent.
    """
    print(f"Applying string replacements (Target: {target_color})...")
    
    # 1. White to Transparent (Convert all white fills/strokes to 'none')
    # This handles attributes like fill="white" or stroke="#ffffff"
    white_pattern = r'(white|#fff|#ffffff|#FFFFFF|rgb\(255,255,255\)|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))'
    svg_text = re.sub(rf'(fill|stroke|color)=["\']{white_pattern}["\']', r'\1="none"', svg_text, flags=re.IGNORECASE)
    
    # Also handle styles like style="fill:white"
    svg_text = re.sub(rf'(fill|stroke|color):\s*{white_pattern}', r'\1:none', svg_text, flags=re.IGNORECASE)
    
    # 2. Black to Target Color
    black_pattern = r'(#000|#000000|black|rgb\(0,0,0\)|rgb\(\s*0\s*,\s*0\s*,\s*0\s*\))'

    # Attributes: fill="black"
    svg_text = re.sub(rf'(fill|stroke|color)=["\']{black_pattern}["\']', rf'\1="{target_color}"', svg_text, flags=re.IGNORECASE)
    
    # Style: fill:black
    svg_text = re.sub(rf'(fill|stroke|color):\s*{black_pattern}', rf'\1:{target_color}', svg_text, flags=re.IGNORECASE)
    
    return svg_text

def hq_export(base_path, overlay_path, output_pdf):
    print(f"Reading {base_path}...")
    with open(base_path, 'r', encoding='utf-8', errors='ignore') as f:
        base_text = f.read()
    
    print(f"Reading {overlay_path}...")
    with open(overlay_path, 'r', encoding='utf-8', errors='ignore') as f:
        overlay_text = f.read()

    # Process each layer
    print("Processing Base (Red)...")
    base_processed = process_svg_string(base_text, 'red')
    
    print("Processing Overlay (Green)...")
    overlay_processed = process_svg_string(overlay_text, 'green')
    
    # Free memory
    base_text = overlay_text = None

    print("Merging layers (Transparent Background)...")
    
    # Extract content
    base_content_match = re.search(r'<svg[^>]*>([\s\S]*?)<\/svg>', base_processed, re.IGNORECASE)
    overlay_content_match = re.search(r'<svg[^>]*>([\s\S]*?)<\/svg>', overlay_processed, re.IGNORECASE)
    
    if not base_content_match or not overlay_content_match:
        print("Error: Could not parse SVG content.")
        return
    
    base_content = base_content_match.group(1)
    overlay_content = overlay_content_match.group(1)
    
    # Get the header
    header_match = re.search(r'(<svg[^>]*>)', base_processed, re.IGNORECASE)
    header = header_match.group(1) if header_match else '<svg xmlns="http://www.w3.org/2000/svg">'

    # Final assembly: No background rect, just layers
    final_svg_text = (
        header + 
        f'\n<g opacity="1.0" id="overlay_green">\n{overlay_content}\n</g>' + 
        f'\n<g opacity="1.0" id="base_red">\n{base_content}\n</g>' + 
        '\n</svg>'
    )
    
    temp_svg = "comparison_output.svg"
    with open(temp_svg, 'w', encoding='utf-8') as f:
        f.write(final_svg_text)
    print(f"Success! Transparent result saved to {temp_svg}")

    if HAS_CAIRO:
        print(f"Converting to PDF...")
        try:
            cairosvg.svg2pdf(bytestring=final_svg_text.encode('utf-8'), write_to=output_pdf)
            print(f"PDF created: {output_pdf}")
        except Exception as e:
            print(f"PDF failed: {e}")
    else:
        print("\nNote: For PDF, open 'comparison_output.svg' in Chrome and print to PDF.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python hq_export.py base.svg overlay.svg [output.pdf]")
    else:
        out = sys.argv[3] if len(sys.argv) > 3 else "overlay_comparison.pdf"
        hq_export(sys.argv[1], sys.argv[2], out)
