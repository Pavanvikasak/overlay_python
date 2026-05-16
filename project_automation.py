import streamlit as st
import fitz
from PIL import Image, ImageEnhance
import numpy as np
import re
from scipy.ndimage import label, binary_dilation
import io, os, zipfile, imaplib, email, requests, json, datetime, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

load_dotenv()
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
DB_PATH    = os.getenv("REVISONS_PATH", "./revisons")
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Aekam AI | Overlay Engine", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")
Image.MAX_IMAGE_PIXELS = None

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap');
html,body,[class*="css"]{font-family:'Outfit',sans-serif;}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#0f172a 0%,#1e293b 100%);border-right:1px solid #334155;}
section[data-testid="stSidebar"] *{color:#e2e8f0 !important;}
.main{background:#f8fafc;}
.step-card{display:flex;align-items:flex-start;gap:12px;padding:12px 14px;margin:5px 0;border-radius:12px;border:1px solid transparent;transition:all .3s;}
.step-card.active{background:rgba(59,130,246,.15);border-color:#3b82f6;}
.step-card.done{background:rgba(34,197,94,.1);border-color:#22c55e;}
.step-card.pending{background:rgba(255,255,255,.04);border-color:#334155;opacity:.55;}
.step-card.running{background:rgba(250,204,21,.1);border-color:#facc15;}
.step-num{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;flex-shrink:0;}
.step-num.active{background:#3b82f6;color:#fff !important;}
.step-num.done{background:#22c55e;color:#fff !important;}
.step-num.pending{background:#334155;color:#94a3b8 !important;}
.step-num.running{background:#facc15;color:#0f172a !important;}
.step-label{font-size:13px;font-weight:600;margin:0;line-height:1.3;}
.step-desc{font-size:11px;opacity:.6;margin:2px 0 0;}
.status-log{background:#0f172a;border-radius:12px;padding:16px;font-family:'Courier New',monospace;font-size:13px;color:#94a3b8;min-height:80px;border:1px solid #1e293b;margin-top:8px;}
.log-line{margin:3px 0;}.log-ok{color:#22c55e;}.log-info{color:#60a5fa;}.log-warn{color:#f59e0b;}.log-err{color:#f87171;}
.step-header{font-size:2rem;font-weight:800;color:#0f172a;margin-bottom:6px;}
.step-sub{color:#64748b;font-size:1rem;margin-bottom:24px;}
.activity{display:inline-flex;align-items:center;gap:8px;background:rgba(59,130,246,.1);border:1px solid #3b82f6;border-radius:20px;padding:6px 16px;font-size:13px;font-weight:600;color:#3b82f6;margin-bottom:20px;}
.pulse{width:8px;height:8px;border-radius:50%;background:#3b82f6;animation:pulse 1.5s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.4;transform:scale(.8);}}
#MainMenu,footer,header{visibility:hidden;}
</style>
""", unsafe_allow_html=True)


# ── CORE ──────────────────────────────────────────────────────────────────────

def get_drawing_data(page, zoom=3.0):
    mat  = fitz.Matrix(zoom, zoom)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    r,g,b = data[:,:,0],data[:,:,1],data[:,:,2]
    dark  = (r<150)&(g<150)&(b<150)
    white = (r>240)&(g>240)&(b>240)
    color = ~dark&~white
    if dark.any():
        la,_ = label(dark)
        sz   = np.bincount(la.ravel())
        big  = sz>(dark.size*0.02)
        line = dark&~big[la]
    else:
        line = dark
    ci = np.zeros((data.shape[0],data.shape[1],4),dtype=np.uint8)
    ci[color] = np.concatenate([data[color],np.full((color.sum(),1),255,dtype=np.uint8)],axis=1)
    return line, ci

def process_overlay(bp, op, zoom=3.0):
    bm,bc = get_drawing_data(bp,zoom)
    om,oc = get_drawing_data(op,zoom)
    mh,mw = max(bm.shape[0],om.shape[0]),max(bm.shape[1],om.shape[1])
    def pad(a,h,w):
        ph,pw=a.shape[:2]; z=(np.zeros((h,w,4),dtype=np.uint8) if a.ndim==3 else np.zeros((h,w),dtype=bool)); z[:ph,:pw]=a; return z
    bm=pad(bm,mh,mw);om=pad(om,mh,mw);bc=pad(bc,mh,mw);oc=pad(oc,mh,mw)
    res=np.full((mh,mw,4),255,dtype=np.uint8)
    ovd=binary_dilation(om,iterations=1); ov=bm&ovd
    res[ov]=[0,0,0,255];res[bm&~ov]=[255,0,0,255];res[om&~ov]=[0,180,0,255]
    hb=bc[:,:,3]>0;ho=oc[:,:,3]>0;res[hb]=bc[hb];res[ho]=oc[ho]
    img=Image.fromarray(res)
    return ImageEnhance.Contrast(ImageEnhance.Sharpness(img).enhance(2.5)).enhance(1.1)

def extract_id(page):
    rect=page.rect; clip=fitz.Rect(rect.width*.7,rect.height*.7,rect.width,rect.height)
    words=page.get_text("words",clip=clip)
    if not words: return f"P{page.number+1}"
    ws=sorted(words,key=lambda w:(rect.width-w[2])**2+(rect.height-w[3])**2)
    for w in ws[:15]:
        t=w[4].strip().upper()
        if re.match(r'^(A|S|M|E|P|L|C|W|SK|AD|SD)[0-9]*[-.\\s]?[0-9.]+[A-Z]?$',t): return t
    for w in ws[:15]:
        t=w[4].strip().upper()
        if re.match(r'^[A-Z0-9]{1,4}-[A-Z0-9]{1,4}$',t) and not t.startswith('202'): return t
    return ws[0][4].strip()

def find_match(did):
    if not os.path.exists(DB_PATH): return None
    c=re.sub(r'[^A-Z0-9]','',did.upper())
    for f in os.listdir(DB_PATH):
        if f.lower().endswith('.pdf') and c in re.sub(r'[^A-Z0-9]','',f.upper()):
            return os.path.join(DB_PATH,f)
    return None

def resolve_path(p):
    """Resolve absolute, relative, or bare filename paths. Supports directories by picking the first PDF inside."""
    p = p.strip()
    
    def check_and_return(target):
        if not os.path.exists(target): return None
        if os.path.isfile(target) and target.lower().endswith('.pdf'): return target
        if os.path.isdir(target):
            pdfs = sorted([f for f in os.listdir(target) if f.lower().endswith('.pdf')])
            if pdfs: return os.path.join(target, pdfs[0])
        return None

    # 1. Try as-is (absolute or already relative to CWD)
    res = check_and_return(p)
    if res: return res

    # 2. Try relative to BASE_DIR (with various prefix stripping)
    # Strip leading ./ or / or \
    stripped = p
    if stripped.startswith('./'): stripped = stripped[2:]
    stripped = stripped.lstrip('/\\').replace('/', os.sep).replace('\\', os.sep)
    
    candidate = os.path.normpath(os.path.join(BASE_DIR, stripped))
    res = check_and_return(candidate)
    if res: return res

    # 3. Bare filename search recursively (max 3 levels)
    bare = os.path.basename(stripped)
    if bare and bare.lower().endswith('.pdf'):
        for root, _, files in os.walk(BASE_DIR):
            if root.count(os.sep) - BASE_DIR.count(os.sep) > 3:
                continue
            if bare in files:
                return os.path.join(root, bare)
    return None

def fetch_pdf_path_from_email():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        status, msgs = mail.search(None, '(UNSEEN SUBJECT "MASTER PDF")')
        if status != "OK" or not msgs[0]:
            return None, None, None, {}, "No new 'MASTER PDF' emails found."
        
        lid = msgs[0].split()[-1]
        _, mdata = mail.fetch(lid, "(RFC822)")
        found_path, att_bytes, att_name = None, None, None
        meta = {}
        sender = None

        for rp in mdata:
            if not isinstance(rp, tuple): continue
            msg = email.message_from_bytes(rp[1])
            body = ""
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    body += part.get_payload(decode=True).decode(errors="ignore")
                elif ct == "text/html":
                    body += re.sub(r'<[^>]+>',' ',part.get_payload(decode=True).decode(errors="ignore"))
            
            if not sender:
                sender = msg.get("From")
            
            # 1. Extract Metadata from table-like structure (as per user image)
            patterns = {
                "name":      r"Project name\s*[:\s]\s*([^\r\n<\"|]+)",
                "id":        r"Project\s*[:\s]\s*([^\r\n<\"|]+)",
                "c#":        r"c#\s*[:\s]\s*([^\r\n<\"|]+)",
                "loc":       r"Location of data\s*[:\s]\s*([^\r\n<\"|]+)",
                "manager":   r"Project manager\s*[:\s]\s*([^\r\n<\"|]+)",
                "received":  r"Recevied on\s*[:\s]\s*([^\r\n<\"|]+)"
            }
            for k, pat in patterns.items():
                m = re.search(pat, body, re.IGNORECASE)
                if m: meta[k] = m.group(1).strip()
            
            # 2. Identify the PDF path
            if "loc" in meta:
                found_path = meta["loc"]
            else:
                # Fallback to generic PDF regex
                pdf_patterns = [
                    r'[A-Za-z]:\\[^\r\n<>"]+?\.pdf',
                    r'\\\\?[a-zA-Z][^\r\n<>"]+?\.pdf',
                    r'\\[^\r\n<>"]+?\.pdf',
                    r'(?:/|\.\/)[^\r\n<>"]+?\.pdf',
                    r'[^\r\n<>"]+?\.pdf',
                ]
                for pat in pdf_patterns:
                    m = re.findall(pat, body, re.IGNORECASE)
                    if m:
                        found_path = m[0].strip()
                        break
            
            # 3. Attachment fallback
            for part in msg.walk():
                if part.get_content_maintype()=="multipart": continue
                if part.get("Content-Disposition") is None: continue
                fn = part.get_filename()
                if fn and fn.lower().endswith(".pdf"):
                    att_bytes = io.BytesIO(part.get_payload(decode=True))
                    att_name  = fn
                    break
        
        mail.logout()
        if sender: meta['sender'] = sender
        return found_path, att_bytes, att_name, meta, None
    except Exception as e:
        return None, None, None, {}, f"Gmail Error: {e}"


# ── SESSION STATE ─────────────────────────────────────────────────────────────

for k,v in {"step":1,"logs":[],"pdf_path":None,"pdf_bytes":None,"pdf_name":None, "meta":{},
             "results":[],"auto_pdf_bytes":None,"auto_zip_bytes":None,"autorun":False}.items():
    if k not in st.session_state:
        st.session_state[k]=v


# ── HELPERS ───────────────────────────────────────────────────────────────────

def log(msg, kind="info"):
    st.session_state.logs.append((kind, msg))

def show_logs():
    cls = {"ok":"log-ok","info":"log-info","warn":"log-warn","err":"log-err"}
    html = "".join(f'<div class="log-line {cls.get(k,"log-info")}">› {m}</div>'
                   for k,m in st.session_state.logs[-25:])
    if not html:
        html = '<div class="log-line">Waiting...</div>'
    st.markdown(f'<div class="status-log">{html}</div>', unsafe_allow_html=True)

def badge(text):
    st.markdown(f'<div style="display:flex;justify-content:center;margin-bottom:16px;">'
                f'<div class="activity"><div class="pulse"></div>{text}</div></div>',
                unsafe_allow_html=True)

def sidebar():
    steps = [
        (1,"Check Emails","Scan Gmail for Master PDF path"),
        (2,"Load PDF","Read file from path in email"),
        (3,"Match Drawings","Look up revisions database"),
        (4,"Generate Overlays","Render comparison images"),
        (5,"Download","Export PDF & ZIP"),
    ]
    st.sidebar.markdown(
        '<div style="padding:16px 0 8px">'
        '<span style="font-size:22px;font-weight:800;color:#60a5fa;">⚡ Aekam AI</span>'
        '<br><span style="font-size:11px;color:#475569;text-transform:uppercase;letter-spacing:2px;">Overlay Engine</span>'
        '</div>', unsafe_allow_html=True)
    st.sidebar.markdown("---")
    cur = st.session_state.step
    for num,lbl,desc in steps:
        if cur > num:   state,icon = "done","✓"
        elif cur == num: state,icon = "active",str(num)
        else:            state,icon = "pending",str(num)
        st.sidebar.markdown(
            f'<div class="step-card {state}">'
            f'<div class="step-num {state}">{icon}</div>'
            f'<div><p class="step-label">{lbl}</p><p class="step-desc">{desc}</p></div>'
            f'</div>', unsafe_allow_html=True)
    st.sidebar.markdown("---")
    if st.session_state.meta:
        m = st.session_state.meta
        st.sidebar.markdown(f"📂 **Project:** {m.get('name','Unknown')}")
        if 'id' in m: st.sidebar.markdown(f"🆔 **ID:** {m['id']}")
        if 'manager' in m: st.sidebar.markdown(f"👤 **PM:** {m['manager']}")
        st.sidebar.markdown("---")

    if os.path.exists(DB_PATH):
        cnt = len([f for f in os.listdir(DB_PATH) if f.endswith('.pdf')])
        st.sidebar.success(f"🗄️ DB: {cnt} revisions")
    else:
        st.sidebar.error("⚠️ Revisions DB missing")
    if GMAIL_USER:
        st.sidebar.info(f"📧 {GMAIL_USER}")

def save_to_disk_and_notify():
    meta = st.session_state.get('meta', {})
    proj_name = meta.get('name', 'Unknown_Project').strip()
    pdf_name  = st.session_state.get('pdf_name', 'Input_File')
    if not pdf_name.lower().endswith('.pdf'): pdf_name += '.pdf'
    
    # Clean names for filesystem
    safe_proj = re.sub(r'[^a-zA-Z0-9_\-\s]', '', proj_name).replace(' ', '_')
    safe_pdf_folder = re.sub(r'[^a-zA-Z0-9_\-\s]', '', pdf_name.replace('.pdf','').replace('.PDF','')).replace(' ', '_')
    
    # Build structure: outputs/{project_name}/{input_file_folder}/
    base_dir = os.path.join(BASE_DIR, "outputs", safe_proj, safe_pdf_folder)
    review_dir = os.path.join(base_dir, "review", "overlays and revisons")
    os.makedirs(review_dir, exist_ok=True)
    
    # 1. Save original input file copy in the base folder
    input_path = os.path.join(base_dir, pdf_name)
    if st.session_state.pdf_bytes:
        with open(input_path, "wb") as f:
            f.write(st.session_state.pdf_bytes)
    
    # 2. Save generated outputs in the review folder
    master_path = os.path.join(review_dir, "COMBINED_MASTER.pdf")
    zip_path = os.path.join(review_dir, "Overlay_Package.zip")
    
    if st.session_state.auto_pdf_bytes:
        with open(master_path, "wb") as f:
            f.write(st.session_state.auto_pdf_bytes)
    
    if st.session_state.auto_zip_bytes:
        with open(zip_path, "wb") as f:
            f.write(st.session_state.auto_zip_bytes)
        
    log(f"Saved to: outputs/{safe_proj}/{safe_pdf_folder}/...", "ok")
    
    # Webhook
    try:
        url = "https://pavanvikas.app.n8n.cloud/webhook/b9a26a30-3d2b-408b-b515-d7063e6916eb"
        payload = {
          "Project": meta.get('id', 'N/A'),
          "Project_Name": proj_name,
          "Project_message": f"Overlay processing complete for {len(st.session_state.results)} pages.",
          "C#": meta.get('c#', 'N/A'),
          "Pages": str(len(st.session_state.results)),
          "Recevied_on": meta.get('received', datetime.datetime.now().strftime("%Y-%m-%d")),
          "Returend_on": datetime.datetime.now().strftime("%Y-%m-%d"),
          "Review_by": meta.get('manager', 'System'),
          "General_notes": f"Automated processing. Saved to {review_dir}",
          "Progress_status": "Completed",
          "Kahua_updates": "Updated"
        }
        headers = { 'Content-Type': 'application/json' }
        response = requests.post(url, headers=headers, json=payload)
        log(f"Webhook sent: {response.status_code} {response.reason}", "ok")
    except Exception as e:
        log(f"Webhook failed: {e}", "err")

    # 3. Email Reply
    sender = meta.get('sender')
    if sender and GMAIL_USER and GMAIL_PASS:
        try:
            log(f"Sending reply to {sender}...", "info")
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = sender
            msg['Subject'] = f"RE: MASTER PDF - {proj_name}"
            
            body = f"""
Project name: {proj_name}
Project: {meta.get('id', 'N/A')}
c#: {meta.get('c#', 'N/A')}
Project manager: {meta.get('manager', 'N/A')}
Recevied on: {meta.get('received', 'N/A')}
Status: Completed
Pages Processed: {len(st.session_state.results)}

The overlay processing is complete. Please find the attached files.
Outputs saved to: {review_dir}
"""
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_USER, GMAIL_PASS)
                server.send_message(msg)
            log("Reply email sent successfully!", "ok")
        except Exception as e:
            log(f"Email reply failed: {e}", "err")


# ── STEPS ─────────────────────────────────────────────────────────────────────

def step1():
    st.markdown('<div class="step-header">📬 Check Emails</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">Click below — Gmail will be scanned for a new <b>Master PDF</b> email. Everything else runs automatically.</div>', unsafe_allow_html=True)
    show_logs()
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("📨  Check Emails for Master PDF", type="primary", use_container_width=True):
        if not GMAIL_USER or not GMAIL_PASS:
            st.error("Gmail credentials missing in .env!"); return
        with st.spinner("Connecting to Gmail…"):
            log(f"Connecting as {GMAIL_USER}…")
            found_path, att, att_name, meta, err = fetch_pdf_path_from_email()
        if err:
            log(err,"err"); st.error(err); return
        
        st.session_state.meta = meta
        if meta.get('name'):
            log(f"Project found: {meta['name']} (ID: {meta.get('id','N/A')})", "ok")

        if found_path:
            log(f"Location of data: {found_path}","ok")
            st.session_state.pdf_path = found_path
            st.session_state.pdf_name = os.path.basename(found_path)
        elif att:
            log(f"Using attachment: {att_name}","warn")
            st.session_state.pdf_bytes = att.getvalue()
            st.session_state.pdf_name  = att_name
        else:
            log("No path or attachment found","err"); st.error("Email had no PDF path or attachment."); return
        st.session_state.step    = 2
        st.session_state.autorun = True
        st.rerun()


def step2():
    """Auto-run: load PDF from path, no button."""
    st.markdown('<div class="step-header">📂 Loading PDF…</div>', unsafe_allow_html=True)
    path = st.session_state.pdf_path

    if path:
        badge(f"Reading: {os.path.basename(path)}")
        resolved = resolve_path(path)
        if not resolved:
            log(f"File not found: {path}","err")
            st.error(f"Cannot find file: `{path}`")
            st.session_state.autorun = False
            return
        log(f"Resolved path → {resolved}","info")
        with st.spinner("Reading file…"):
            with open(resolved,"rb") as f:
                data = f.read()
        size_mb = len(data)/(1024*1024)
        log(f"Loaded {os.path.basename(resolved)} ({size_mb:.1f} MB)","ok")
        st.session_state.pdf_bytes = data
        st.session_state.pdf_name  = os.path.basename(resolved)
    else:
        log("Using attachment bytes","info")

    show_logs()
    st.session_state.step = 3
    st.rerun()


def step3():
    """Auto-run: match drawings."""
    st.markdown('<div class="step-header">🔍 Matching Drawings…</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="step-sub">Scanning <b>{st.session_state.pdf_name}</b> against revisions database.</div>', unsafe_allow_html=True)
    badge("Scanning pages…")
    show_logs()

    pdf_bytes = st.session_state.pdf_bytes
    if not pdf_bytes:
        st.error("No PDF data!"); return

    log("Opening PDF…","info")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    log(f"PDF has {len(doc)} page(s)","info")

    matched = []
    prog = st.progress(0, text="Matching…")
    for i, page in enumerate(doc):
        did   = extract_id(page)
        match = find_match(did)
        log(f"Page {i+1}: {did} → {'✓ '+os.path.basename(match) if match else '✗ no match'}",
            "ok" if match else "warn")
        if match:
            matched.append((did, match))
        prog.progress((i+1)/len(doc), text=f"Page {i+1}/{len(doc)}")

    log(f"Matched {len(matched)}/{len(doc)} pages","ok" if matched else "err")
    st.session_state.matched = matched
    st.session_state._doc_bytes = pdf_bytes
    show_logs()

    if not matched:
        st.error("No matches found in database."); return
    st.session_state.step = 4
    st.rerun()


def step4():
    """Auto-run: render overlays with per-drawing progress and live previews."""
    matched = st.session_state.get("matched",[])
    st.markdown('<div class="step-header">🎨 Generating Overlays…</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="step-sub">Rendering <b>{len(matched)}</b> comparison(s) — live updates below.</div>', unsafe_allow_html=True)
    badge(f"Processing {len(matched)} drawing(s)…")
    show_logs()

    # Pre-allocate fixed top slots (stay at top during entire loop)
    cur_label  = st.empty()
    cur_bar    = st.empty()
    cur_status = st.empty()
    overall    = st.progress(0, text=f"Overall: 0 / {len(matched)}")
    st.markdown("---")
    done_slot  = st.empty()   # completed pills accumulate here

    doc        = fitz.open(stream=st.session_state._doc_bytes, filetype="pdf")
    results    = []
    done_pills = ""

    for i,(did,match_path) in enumerate(matched):
        cur_label.markdown(f"**Drawing {i+1} / {len(matched)}: `{did}`**")
        cur_bar.progress(15, text="Locating page…")
        base_page = None
        for page in doc:
            if extract_id(page)==did:
                base_page=page; break
        if base_page is None:
            base_page=doc[i]

        cur_bar.progress(35, text="Loading revision drawing…")
        log(f"Rendering {did}…","info")
        rev = fitz.open(match_path)

        cur_bar.progress(60, text="Compositing red/green overlay…")
        img = process_overlay(base_page, rev[0], zoom=3.0)
        rev.close()
        results.append(img)

        cur_bar.progress(100, text=f"✓ {did} complete")
        log(f"  ✓ {did} done","ok")
        cur_status.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:8px;'
            f'background:rgba(34,197,94,.12);border:1px solid #22c55e;'
            f'border-radius:20px;padding:5px 14px;font-size:13px;font-weight:600;color:#16a34a;">'
            f'✓ Overlay {i+1} of {len(matched)} ready — {did}</div>',
            unsafe_allow_html=True
        )

        overall.progress((i+1)/len(matched), text=f"Overall: {i+1} / {len(matched)} complete")
        st.markdown("---")

    # Package
    pack = st.progress(0, text="Packaging PDF…")
    log("Building PDF package…","info")
    pdf_buf = io.BytesIO()
    rgb = [r.convert("RGB") for r in results]
    rgb[0].save(pdf_buf,format='PDF',save_all=True,append_images=rgb[1:],resolution=144)
    st.session_state.auto_pdf_bytes = pdf_buf.getvalue()
    pack.progress(60, text="Packaging ZIP…")

    log("Building ZIP…","info")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf,'w') as zf:
        for idx,img in enumerate(results):
            buf=io.BytesIO(); img.convert("RGB").save(buf,format='PDF',resolution=144)
            zf.writestr(f"Page_{idx+1}_Overlay.pdf",buf.getvalue())
        zf.writestr("COMBINED_MASTER.pdf",st.session_state.auto_pdf_bytes)
    st.session_state.auto_zip_bytes = zip_buf.getvalue()
    st.session_state.results = results
    log("All done!","ok")
    
    # Automated Saving and Webhook
    save_to_disk_and_notify()
    
    st.session_state.step = 5
    st.rerun()


def step5():
    results = st.session_state.results
    st.markdown('<div class="step-header">✅ Complete!</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="step-sub">{len(results)} overlay(s) generated.</div>', unsafe_allow_html=True)
    badge("Pipeline Complete")
    show_logs()

    if results:
        st.markdown("### 🖼️ Preview — First Page")
        st.image(results[0], use_container_width=True)

    st.markdown("---")
    c1,c2 = st.columns(2)
    with c1:
        st.download_button("📥 Download Combined PDF", st.session_state.auto_pdf_bytes,
                           "Automated_Master.pdf","application/pdf",
                           use_container_width=True, type="primary")
    with c2:
        st.download_button("🗜️ Download ZIP Package", st.session_state.auto_zip_bytes,
                           "Automated_Package.zip","application/zip",
                           use_container_width=True)
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄  Start New Run", use_container_width=True):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    sidebar()
    st.markdown('<div style="max-width:800px;margin:40px auto;">', unsafe_allow_html=True)

    s = st.session_state.step
    if   s == 1: step1()
    elif s == 2: step2()
    elif s == 3: step3()
    elif s == 4: step4()
    elif s == 5: step5()

    st.markdown('</div>', unsafe_allow_html=True)

if __name__ == "__main__":
    main()
