import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance
import numpy as np

# --- DISABLE SAFETY LIMITS FOR HIGH-RES DRAWINGS ---
Image.MAX_IMAGE_PIXELS = None 
from scipy.ndimage import label, binary_dilation
import io
import datetime

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Walters | Project Delivery Suite",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- THEME & STYLING ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
    
    :root {
        --walters-blue: #1A365D;
        --walters-accent: #3182CE;
        --glass-bg: rgba(255, 255, 255, 0.95);
    }

    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }

    .main {
        background-color: #f8fafc;
    }

    /* Checklist Styling */
    .step-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        border-left: 5px solid #CBD5E0;
        margin-bottom: 1rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        transition: all 0.3s ease;
    }
    .step-active {
        border-left: 5px solid var(--walters-accent);
        background: #ebf8ff;
    }
    .step-complete {
        border-left: 5px solid #48BB78;
        background: #f0fff4;
    }

    /* Header */
    .header {
        background: var(--walters-blue);
        padding: 2rem;
        color: white;
        border-radius: 0 0 24px 24px;
        margin-bottom: 2rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* Buttons */
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 3rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
</style>
""", unsafe_allow_html=True)

# --- LOGIC FUNCTIONS ---

def get_drawing_data(page, zoom, offset_x=0, offset_y=0, scale=1.0):
    """Processes PDF page into line masks and color data."""
    mat = fitz.Matrix(zoom * scale, zoom * scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    
    data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    r, g, b = data[:,:,0], data[:,:,1], data[:,:,2]

    dark_mask = (r < 150) & (g < 150) & (b < 150)
    white_mask = (r > 240) & (g > 240) & (b > 240)
    color_mask = ~dark_mask & ~white_mask

    # Area filter for backgrounds
    if dark_mask.any():
        labeled_array, _ = label(dark_mask)
        component_sizes = np.bincount(labeled_array.ravel())
        too_large_mask = component_sizes > (dark_mask.size * 0.02)
        fill_mask = too_large_mask[labeled_array]
        line_mask = dark_mask & ~fill_mask
    else:
        line_mask = dark_mask

    color_img_data = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    color_img_data[color_mask] = np.concatenate([data[color_mask], np.full((data[color_mask].shape[0], 1), 255, dtype=np.uint8)], axis=1)

    return line_mask, color_img_data

def process_overlay(base_bytes, overlay_bytes, zoom, ox, oy, scale):
    base_doc = fitz.open(stream=base_bytes, filetype="pdf")
    overlay_doc = fitz.open(stream=overlay_bytes, filetype="pdf")
    
    base_page = base_doc[0]
    overlay_page = overlay_doc[0]

    base_mask, base_color = get_drawing_data(base_page, zoom)
    # Apply manual alignment to overlay
    overlay_mask, overlay_color = get_drawing_data(overlay_page, zoom, ox, oy, scale)

    # Simple padding/cropping to match sizes if they differ after scaling
    h1, w1 = base_mask.shape
    h2, w2 = overlay_mask.shape
    
    max_h, max_w = max(h1, h2), max(w1, w2)
    
    def pad_image(img, target_h, target_w):
        curr_h, curr_w = img.shape[:2]
        if len(img.shape) == 3: # RGBA
            padded = np.zeros((target_h, target_w, 4), dtype=np.uint8)
            padded[:curr_h, :curr_w] = img
        else: # Mask
            padded = np.zeros((target_h, target_w), dtype=bool)
            padded[:curr_h, :curr_w] = img
        return padded

    base_mask_final = pad_image(base_mask, max_h, max_w)
    overlay_mask_final = pad_image(overlay_mask, max_h, max_w)
    base_color_final = pad_image(base_color, max_h, max_w)
    overlay_color_final = pad_image(overlay_color, max_h, max_w)

def process_overlay(base_page, overlay_page, zoom, ox, oy, scale):
    """Processes a single page pair overlay."""
    base_mask, base_color = get_drawing_data(base_page, zoom)
    overlay_mask, overlay_color = get_drawing_data(overlay_page, zoom, ox, oy, scale)

    h1, w1 = base_mask.shape
    h2, w2 = overlay_mask.shape
    max_h, max_w = max(h1, h2), max(w1, w2)
    
    def pad_image(img, target_h, target_w):
        curr_h, curr_w = img.shape[:2]
        if len(img.shape) == 3: # RGBA
            padded = np.zeros((target_h, target_w, 4), dtype=np.uint8)
            padded[:curr_h, :curr_w] = img
        else: # Mask
            padded = np.zeros((target_h, target_w), dtype=bool)
            padded[:curr_h, :curr_w] = img
        return padded

    base_mask_final = pad_image(base_mask, max_h, max_w)
    overlay_mask_final = pad_image(overlay_mask, max_h, max_w)
    base_color_final = pad_image(base_color, max_h, max_w)
    overlay_color_final = pad_image(overlay_color, max_h, max_w)

    result = np.full((max_h, max_w, 4), 255, dtype=np.uint8)
    overlay_dilated = binary_dilation(overlay_mask_final, iterations=1)
    
    overlap = base_mask_final & overlay_dilated
    base_only = base_mask_final & ~overlap
    overlay_only = overlay_mask_final & ~overlap

    result[overlap] = [0, 0, 0, 255]      
    result[base_only] = [255, 0, 0, 255]   
    result[overlay_only] = [0, 180, 0, 255] 

    has_color_base = base_color_final[:,:,3] > 0
    has_color_overlay = overlay_color_final[:,:,3] > 0
    result[has_color_base] = base_color_final[has_color_base]
    result[has_color_overlay] = overlay_color_final[has_color_overlay]

    final_img = Image.fromarray(result)
    
    # --- HIGHEST QUALITY ENHANCEMENTS ---
    # 1. Sharpening pass for crisp engineering lines
    enhancer = ImageEnhance.Sharpness(final_img)
    final_img = enhancer.enhance(2.5)  # Boost sharpness
    
    # 2. Contrast adjustment to make Red/Green pop
    contrast = ImageEnhance.Contrast(final_img)
    final_img = contrast.enhance(1.1)
    
    return final_img

import re

def extract_drawing_info(page):
    """Attempts to extract the actual drawing number (A-101 etc.) by prioritizing 
    standard engineering prefixes and physical location."""
    # Look at the bottom-right area
    rect = page.rect
    clip = fitz.Rect(rect.width * 0.7, rect.height * 0.7, rect.width, rect.height)
    
    # Get text with coordinates
    words = page.get_text("words", clip=clip)
    if not words:
        return f"P{page.number + 1}"

    # Sort words by physical distance from the bottom-right corner
    # (x1, y1) is the bottom-right of each word
    words_sorted = sorted(words, key=lambda w: (rect.width - w[2])**2 + (rect.height - w[3])**2)

    # Drawing number patterns: Priorities
    # 1. Starts with a common engineering prefix, allows intermediate digits and decimals (e.g., A2.465, SK-101)
    prefix_pattern = r'^(A|S|M|E|P|L|C|W|SK|AD|SD)[0-9]*[-.\s]?[0-9.]+[A-Z]?$'
    # 2. General alphanumeric with at least one dash
    general_pattern = r'^[A-Z0-9]{1,4}-[A-Z0-9]{1,4}$'

    # Pass 1: Look for the physically closest word that matches a prefix pattern
    for word in words_sorted[:15]: # Check the 15 words closest to the bottom right
        text = word[4].strip().upper()
        if re.match(prefix_pattern, text):
            return text
            
    # Pass 2: Look for anything matching a general pattern but NOT starting with 202
    for word in words_sorted[:15]:
        text = word[4].strip().upper()
        if re.match(general_pattern, text) and not text.startswith('202'):
            return text

    # Pass 3: Just take the word physically closest to the absolute corner
    return words_sorted[0][4].strip()

# --- APP LAYOUT ---

def main():
    # Header
    st.markdown("""
        <div class="header">
            <div>
                <h1 style='margin:0; font-weight:800;'>WALTERS INC.</h1>
                <p style='margin:0; opacity:0.8;'>Project Delivery & Overlay Procedure | v1.0</p>
            </div>
            <div style='text-align:right;'>
                <p style='margin:0;'>Standard Operating Procedure</p>
                <p style='margin:0; font-weight:600;'>CO-OP QUICK REFERENCE</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Sidebar: Triage (Step 1)
    st.sidebar.header("📋 Step 1: Triage")
    proj_no = st.sidebar.text_input("Project No.", placeholder="e.g. 2024-001")
    date = st.sidebar.date_input("Date", datetime.date.today())
    transmittal = st.sidebar.text_input("Transmittal ID", placeholder="e.g. TR-5521")
    category = st.sidebar.selectbox("Request Category", ["PRICE", "COORD ONLY"])

    # Sidebar: Progress Tracker
    st.sidebar.markdown("---")
    st.sidebar.subheader("Workflow Progress")
    
    steps = ["Receive & Triage", "Folder Setup", "Old Revisions", "Overlay", "Package & Notify"]
    current_step = 0
    
    if proj_no and transmittal: current_step = 1
    
    # State Management for Steps
    if "step2_done" not in st.session_state: st.session_state.step2_done = False
    if "step3_done" not in st.session_state: st.session_state.step3_done = False
    if "overlay_ready" not in st.session_state: st.session_state.overlay_ready = False

    # Main Body
    col_steps, col_action = st.columns([1, 2])

    with col_steps:
        for i, step in enumerate(steps):
            status_class = "step-card"
            icon = "⚪"
            if i < current_step or (i==1 and st.session_state.step2_done) or (i==2 and st.session_state.step3_done) or (i==3 and st.session_state.overlay_ready):
                status_class += " step-complete"
                icon = "✅"
            elif i == current_step:
                status_class += " step-active"
                icon = "🔵"
            
            st.markdown(f"""
                <div class="{status_class}">
                    <div style='display:flex; align-items:center;'>
                        <span style='font-size:1.5rem; margin-right:1rem;'>{icon}</span>
                        <div>
                            <div style='font-size:0.8rem; opacity:0.7; font-weight:600;'>STEP {i+1}</div>
                            <div style='font-weight:600;'>{step}</div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

    with col_action:
        # STEP 2: FOLDER SETUP
        st.subheader("📁 Step 2: Folder Setup")
        st.info(f"Required for Category: **{category}**")
        
        folder_tree = f"📂 Project_{proj_no}\n └── 📂 Walters Review"
        if category == "PRICE":
            folder_tree += "\n     ├── 📂 Old Revisions\n     └── 📂 Change Pricing and Backup"
        else:
            folder_tree += "\n     └── 📂 Archive (COORD ONLY)"
            
        st.code(folder_tree)
        if st.button("Confirm Folder Structure Created"):
            st.session_state.step2_done = True
            st.toast("Folders Confirmed!", icon="📁")

        st.markdown("---")

        # STEP 3 & 4: OVERLAY
        st.subheader("🎨 Step 3 & 4: Drawing Comparison")
        
        up_col1, up_col2 = st.columns(2)
        with up_col1:
            base_file = st.file_uploader("Upload Master PDF", type=["pdf"])
        with up_col2:
            revision_files = st.file_uploader("Upload Revision Folder (Multiple Files)", type=["pdf"], accept_multiple_files=True)

        if base_file and revision_files:
            with st.expander("💎 Ultra-High Quality & Alignment Settings"):
                zoom = st.slider("Quality (DPI Scale - 4.0+ is Pro Level)", 1.0, 8.0, 4.0, 0.5)
                st.warning("⚠️ High zoom levels (6.0+) will create very large files and use significant memory.")
                ox = st.slider("X Offset", -100, 100, 0)
                oy = st.slider("Y Offset", -100, 100, 0)
                scale = st.slider("Relative Scale", 0.8, 1.2, 1.0, 0.01)
                st.info("💡 Files will be matched to pages by Drawing Number found in the title block.")

            if st.button("🚀 Run Batch Overlay Analysis"):
                base_doc = fitz.open(stream=base_file.read(), filetype="pdf")
                
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, base_page in enumerate(base_doc):
                    drawing_id = extract_drawing_info(base_page)
                    status_text.text(f"Processing Page {i+1}: {drawing_id}...")
                    
                    # Fuzzy matching: Check if drawing_id is in filename, 
                    # OR if drawing_id with common delimiters removed matches
                    id_clean = re.sub(r'[^A-Z0-9]', '', drawing_id.upper())
                    
                    match = None
                    for rev in revision_files:
                        rev_name_clean = re.sub(r'[^A-Z0-9]', '', rev.name.upper())
                        if drawing_id.lower() in rev.name.lower() or id_clean in rev_name_clean:
                            match = rev
                            break
                    
                    if match:
                        rev_doc = fitz.open(stream=match.getvalue(), filetype="pdf")
                        overlay_img = process_overlay(base_page, rev_doc[0], zoom, ox, oy, scale)
                        results.append(overlay_img)
                        rev_doc.close()
                    else:
                        st.warning(f"❌ Page {i+1}: No match for Drawing '{drawing_id}'")
                        # Add a manual selector for missing matches in the next update if needed
                    
                    progress_bar.progress((i + 1) / len(base_doc))
                
                if results:
                    st.session_state.overlay_ready = True
                    st.session_state.batch_results = results
                    st.success(f"Successfully processed {len(results)} overlays!")
                    st.image(results[0], caption="Preview of First Overlay", use_column_width=True)
                
                base_doc.close()

        # STEP 5: PACKAGE
        if st.session_state.overlay_ready and "batch_results" in st.session_state:
            st.markdown("---")
            st.subheader("📦 Step 5: Package and Notify")
            
            # Prepare Multi-page PDF (High Resolution Export)
            pdf_buffer = io.BytesIO()
            img_list = [img.convert("RGB") for img in st.session_state.batch_results]
            if img_list:
                # Save with high resolution metadata
                img_list[0].save(
                    pdf_buffer, 
                    format='PDF', 
                    save_all=True, 
                    append_images=img_list[1:],
                    resolution=zoom*72,
                    optimize=False # Disable optimization to keep max quality
                )
            
            st.download_button(
                label=f"📥 Download Full {transmittal} Package ({len(st.session_state.batch_results)} pages)",
                data=pdf_buffer.getvalue(),
                file_name=f"{transmittal}_COMPLETE_OVERLAY.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            
            st.success(f"**Action Required:** Upload to Kahua and notify PM for {proj_no}")
            st.text_area("Notification Draft", f"Hi PM, the overlay for transmittal {transmittal} (Project {proj_no}) is ready. Link: [Paste Kahua Link Here]")

if __name__ == "__main__":
    main()
