
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance
import numpy as np
from scipy.ndimage import label
import sys
import os

def get_drawing_data(page, zoom):
    """
    Analyzes a page and returns:
    1. A binary mask of the black linework (using Area-based filtering).
    2. An RGBA image containing only the non-black/non-white colors.
    """
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    
    # Convert to numpy array
    data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    r, g, b = data[:,:,0], data[:,:,1], data[:,:,2]

    # 1. Identify Dark pixels
    dark_mask = (r < 150) & (g < 150) & (b < 150)
    
    # 2. Identify White pixels
    white_mask = (r > 240) & (g > 240) & (b > 240)

    # 3. Identify Colored pixels
    color_mask = ~dark_mask & ~white_mask

    # 4. PROFESSIONAL AREA FILTER: Remove only massive background blocks
    # We label all dark islands. If an island is huge, it's a 'fill'.
    if dark_mask.any():
        labeled_array, num_features = label(dark_mask)
        # Count pixels in each island
        component_sizes = np.bincount(labeled_array.ravel())
        # If an island covers more than 2% of the total page area, it's a fill
        too_large_mask = component_sizes > (dark_mask.size * 0.02)
        # Any component that is too large is marked for removal
        fill_mask = too_large_mask[labeled_array]
        line_mask = dark_mask & ~fill_mask
    else:
        line_mask = dark_mask

    # 5. Create an RGBA image of the preserved colors
    color_img_data = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    color_img_data[color_mask] = np.concatenate([data[color_mask], np.full((data[color_mask].shape[0], 1), 255, dtype=np.uint8)], axis=1)

    return line_mask, color_img_data

def process_pdf_comparison(base_pdf_path, overlay_pdf_path, output_path):
    print(f"Loading PDFs...")
    base_doc = fitz.open(base_pdf_path)
    overlay_doc = fitz.open(overlay_pdf_path)

    base_page = base_doc[0]
    overlay_page = overlay_doc[0]

    # Ultra-High Sharpness
    zoom = 5.0 

    print("Analyzing Base Drawing (Ultra-High Resolution)...")
    base_line_mask, base_color_data = get_drawing_data(base_page, zoom)

    print("Analyzing Overlay Drawing (Ultra-High Resolution)...")
    overlay_line_mask, overlay_color_data = get_drawing_data(overlay_page, zoom)

    print("Merging Layers (Precision Alignment)...")
    
    height, width = base_line_mask.shape
    result_data = np.full((height, width, 4), 255, dtype=np.uint8)
    
    # 1-pixel tolerance for alignment
    from scipy.ndimage import binary_dilation
    overlay_dilated = binary_dilation(overlay_line_mask, iterations=1)
    
    overlap = base_line_mask & overlay_dilated
    base_only = base_line_mask & ~overlap
    overlay_only = overlay_line_mask & ~overlap

    # Apply Colors
    result_data[overlap] = [0, 0, 0, 255]      
    result_data[base_only] = [255, 0, 0, 255]   
    result_data[overlay_only] = [0, 180, 0, 255] 

    # Preserve Colors
    has_color_base = base_color_data[:,:,3] > 0
    has_color_overlay = overlay_color_data[:,:,3] > 0
    result_data[has_color_base] = base_color_data[has_color_base]
    result_data[has_color_overlay] = overlay_color_data[has_color_overlay]

    print(f"Enhancing Sharpness & Saving: {output_path}")
    final_img = Image.fromarray(result_data)
    
    # Boost sharpness
    enhancer = ImageEnhance.Sharpness(final_img)
    final_img = enhancer.enhance(2.0)
    
    final_pdf = final_img.convert("RGB")
    final_pdf.save(output_path, "PDF", resolution=zoom*72)
    
    base_doc.close()
    overlay_doc.close()
    print("Success! Comparison generated with Area-Filtering and Ultra-Sharpness.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python pdf_hq_export.py base.pdf overlay.pdf [result.pdf]")
    else:
        base, overlay = sys.argv[1], sys.argv[2]
        result = sys.argv[3] if len(sys.argv) > 3 else "pdf_pro_comparison.pdf"
        process_pdf_comparison(base, overlay, result)
