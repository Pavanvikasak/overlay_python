# pyrefly: ignore [missing-import]
import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance
import numpy as np
from scipy.ndimage import label, binary_dilation
import io
import os
import tempfile

# Set page config for a premium feel
st.set_page_config(
    page_title="PDF Overlay Pro",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for high-end aesthetics
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    
    .stButton>button {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        color: white;
        border-radius: 12px;
        padding: 0.6rem 2rem;
        border: none;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.15);
        color: #fff;
    }
    
    .upload-box {
        border: 2px dashed #4b6cb7;
        border-radius: 20px;
        padding: 40px;
        background: rgba(255, 255, 255, 0.8);
        text-align: center;
        transition: all 0.3s ease;
    }
    
    .header-container {
        text-align: center;
        padding: 3rem 0;
        background: transparent;
    }
    
    .title-text {
        font-size: 3.5rem;
        font-weight: 800;
        background: -webkit-linear-gradient(#182848, #4b6cb7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .subtitle-text {
        color: #555;
        font-size: 1.2rem;
    }
    
    /* Glassmorphism card */
    .glass-card {
        background: rgba(255, 255, 255, 0.7);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.3);
        padding: 2rem;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.1);
    }
</style>
""", unsafe_allow_html=True)

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

    # 4. PROFESSIONAL AREA FILTER
    if dark_mask.any():
        labeled_array, num_features = label(dark_mask)
        component_sizes = np.bincount(labeled_array.ravel())
        too_large_mask = component_sizes > (dark_mask.size * 0.02)
        fill_mask = too_large_mask[labeled_array]
        line_mask = dark_mask & ~fill_mask
    else:
        line_mask = dark_mask

    # 5. Create an RGBA image of the preserved colors
    color_img_data = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    color_img_data[color_mask] = np.concatenate([data[color_mask], np.full((data[color_mask].shape[0], 1), 255, dtype=np.uint8)], axis=1)

    return line_mask, color_img_data

def process_pdf_comparison(base_pdf_bytes, overlay_pdf_bytes, zoom=3.0):
    base_doc = fitz.open(stream=base_pdf_bytes, filetype="pdf")
    overlay_doc = fitz.open(stream=overlay_pdf_bytes, filetype="pdf")

    # Assuming single page for now, but can be extended
    base_page = base_doc[0]
    overlay_page = overlay_doc[0]

    with st.spinner("Processing High-Resolution Layers..."):
        base_line_mask, base_color_data = get_drawing_data(base_page, zoom)
        overlay_line_mask, overlay_color_data = get_drawing_data(overlay_page, zoom)

    with st.spinner("Aligning and Merging..."):
        height, width = base_line_mask.shape
        result_data = np.full((height, width, 4), 255, dtype=np.uint8)
        
        overlay_dilated = binary_dilation(overlay_line_mask, iterations=1)
        
        overlap = base_line_mask & overlay_dilated
        base_only = base_line_mask & ~overlap
        overlay_only = overlay_line_mask & ~overlap

        # Apply Colors
        result_data[overlap] = [0, 0, 0, 255]      
        result_data[base_only] = [255, 0, 0, 255]   
        result_data[overlay_only] = [0, 180, 0, 255] 

        # Preserve Original Colors
        has_color_base = base_color_data[:,:,3] > 0
        has_color_overlay = overlay_color_data[:,:,3] > 0
        result_data[has_color_base] = base_color_data[has_color_base]
        result_data[has_color_overlay] = overlay_color_data[has_color_overlay]

        final_img = Image.fromarray(result_data)
        
        # Boost sharpness
        enhancer = ImageEnhance.Sharpness(final_img)
        final_img = enhancer.enhance(2.0)
        
    base_doc.close()
    overlay_doc.close()
    
    return final_img

def main():
    st.markdown('<div class="header-container"><h1 class="title-text">PDF Overlay Pro</h1><p class="subtitle-text">Professional Revision Comparison with AI-Powered Alignment</p></div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📁 Base Drawing (Original)")
        base_file = st.file_uploader("Upload Base PDF", type=["pdf"], key="base")
        st.markdown('</div>', unsafe_allow_html=True)
        
    with col2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📁 Overlay Drawing (Revised)")
        overlay_file = st.file_uploader("Upload Overlay PDF", type=["pdf"], key="overlay")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Settings in an expander for cleaner UI
    with st.expander("⚙️ Advanced Settings"):
        zoom_level = st.slider("Quality Zoom (Higher = Sharper but Slower)", 1.0, 5.0, 3.0, 0.5)
        st.info("💡 High zoom levels (4.0+) are recommended for large engineering drawings but require more memory.")

    if base_file and overlay_file:
        if st.button("🚀 Generate Comparison"):
            try:
                base_bytes = base_file.read()
                overlay_bytes = overlay_file.read()
                
                final_image = process_pdf_comparison(base_bytes, overlay_bytes, zoom=zoom_level)
                
                st.success("✨ Comparison Generated Successfully!")
                
                # Show result
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                st.subheader("🖼️ Preview")
                st.image(final_image, use_column_width=True)
                
                # Download button
                img_byte_arr = io.BytesIO()
                # Convert to RGB for PDF saving
                final_image.convert("RGB").save(img_byte_arr, format='PDF', resolution=zoom_level*72)
                img_byte_arr = img_byte_arr.getvalue()
                
                st.download_button(
                    label="📥 Download Professional Comparison PDF",
                    data=img_byte_arr,
                    file_name="comparison_result.pdf",
                    mime="application/pdf"
                )
                st.markdown('</div>', unsafe_allow_html=True)
                
            except Exception as e:
                st.error(f"Error processing PDFs: {str(e)}")
    else:
        st.info("Please upload both base and overlay PDF files to begin.")

    # Footer
    st.markdown("""
    <div style="text-align: center; margin-top: 5rem; color: #888;">
        <p>Built with ❤️ for Precision Engineering</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
