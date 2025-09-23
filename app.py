import io
import os
import logging
import requests
import qrcode
from flask import Flask, request, send_file, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import getSampleStyleSheet
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import RectangleObject

app = Flask(__name__)

# --- Config & Debug Mode ---
DEBUG_MODE = os.getenv("DEBUG_LOGS", "false").lower() == "true"
logging.basicConfig(level=logging.DEBUG if DEBUG_MODE else logging.INFO)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# --- Optional tiny nudge offsets for the template merge (points) ---
TEMPLATE_DX = float(os.getenv("TEMPLATE_DX", "0"))
TEMPLATE_DY = float(os.getenv("TEMPLATE_DY", "0"))

# --- Template path (flattened) ---
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template-flat.pdf")

# --- Page size ---
PAGE_W, PAGE_H = letter  # 612 x 792

# --- Anchor: extracted bbox for "Scan the QR Code:" on the NON-flattened PDF ---
SCAN_X0 = 60.471
SCAN_X1 = 238.875
SCAN_Y0 = 326.522
SCAN_Y1 = 345.077

# --- Blue line bounds (right column) to align property code left edge (unchanged) ---
BLUE_X_LEFT = 375.616
BLUE_X_RIGHT = 555.895

# --- Layout controls you asked for (UNCHANGED) ---
Y_NAME = 92  # property name
CODE_X_LEFT = BLUE_X_LEFT
CODE_FRAME_WIDTH = BLUE_X_RIGHT - BLUE_X_LEFT
Y_CODE = 210  # property code (about 2 lines up)
CODE_FRAME_HEIGHT = 48

# QR code: center under the "Scan the QR Code:" label, below it (UNCHANGED)
QR_SIZE = 200
QR_TOP_GAP = 12
QR_CENTER_X = (SCAN_X0 + SCAN_X1) / 2.0
QR_X = QR_CENTER_X - (QR_SIZE / 2.0)
QR_Y = (SCAN_Y0 - QR_TOP_GAP) - QR_SIZE
QR_X = max(0, min(QR_X, PAGE_W - QR_SIZE))
QR_Y = max(0, min(QR_Y, PAGE_H - QR_SIZE))

# --- Helpers ---
def fetch_property_row(property_id: str) -> dict:
    """Fetch property row from Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/properties"
    params = {
        "id": f"eq.{property_id}",
        "select": "id,code,property_name,qr_url"
    }
    logging.info(f"Fetching property {property_id} from Supabase")
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    logging.debug(f"Supabase response: {data}")
    if not data:
        raise ValueError("Property not found")
    return data[0]

def generate_qr_code(data: str) -> ImageReader:
    """Generate QR code as ImageReader"""
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)

def _normalize_page_boxes(page):
    """Force media/crop boxes to exact Letter and clear rotation."""
    # Clear rotation if present
    try:
        if "/Rotate" in page:
            del page["/Rotate"]
            logging.info("Cleared page rotation")
    except Exception as e:
        logging.warning(f"Could not clear Rotate: {e}")

    # Force boxes to 0,0,612,792
    rect = RectangleObject([0, 0, PAGE_W, PAGE_H])
    try:
        page.mediabox = rect
    except Exception:
        page.mediaBox = rect  # compatibility
    try:
        page.cropbox = rect
    except Exception:
        page.cropBox = rect  # compatibility

    logging.info(f"Normalized mediabox: {page.mediabox}")
    logging.info(f"Normalized cropbox:  {page.cropbox}")

def build_pdf(property_row: dict) -> bytes:
    """Generate PDF with template, QR code, and property info"""
    logging.info("Building PDF with template overlay...")

    # Read template and normalize page boxes/rotation
    reader = PdfReader(TEMPLATE_PATH)
    template_page = reader.pages[0]
    logging.info(f"TEMPLATE BEFORE normalize -> mediabox: {template_page.mediabox}, cropbox: {template_page.cropbox}")
    _normalize_page_boxes(template_page)
    logging.info(f"TEMPLATE AFTER normalize  -> mediabox: {template_page.mediabox}, cropbox: {template_page.cropbox}")

    # Create overlay canvas (our drawn content)
    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=letter)

    # --- Property Code (wrapped, left-aligned with blue line, unchanged placement) ---
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Helvetica"
    style.fontSize = 12
    para = Paragraph(property_row["code"], style)
    frame = Frame(CODE_X_LEFT, Y_CODE, CODE_FRAME_WIDTH, CODE_FRAME_HEIGHT, showBoundary=0)
    frame.addFromList([para], c)

    # --- Property Name (unchanged) ---
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(PAGE_W / 2.0, Y_NAME, property_row["property_name"])

    # --- QR Code (unchanged) ---
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, QR_X, QR_Y, width=QR_SIZE, height=QR_SIZE, mask="auto")

    # Debug coordinates
    logging.info(f"QR placement -> x={QR_X:.2f}, y={QR_Y:.2f}, size={QR_SIZE}")
    logging.info(f"Code frame  -> x={CODE_X_LEFT:.2f}, y={Y_CODE:.2f}, w={CODE_FRAME_WIDTH:.2f}, h={CODE_FRAME_HEIGHT}")
    logging.info(f"Name        -> x={PAGE_W/2.0:.2f}, y={Y_NAME:.2f}")

    # Finalize overlay
    c.save()
    overlay_buf.seek(0)

    overlay_pdf = PdfReader(overlay_buf)
    base_page = overlay_pdf.pages[0]  # make the overlay the base
    _normalize_page_boxes(base_page)  # ensure overlay page boxes match letter

    # Merge the TEMPLATE onto the overlay base (reverse of earlier approach)
    # Optional translation nudge via env vars TEMPLATE_DX / TEMPLATE_DY
    try:
        # If available in your PyPDF2, use merge_translated_page for fine control:
        if hasattr(base_page, "merge_translated_page"):
            base_page.merge_translated_page(template_page, TEMPLATE_DX, TEMPLATE_DY, expand=False)
            logging.info(f"Merged template with dx={TEMPLATE_DX}, dy={TEMPLATE_DY}")
        else:
            # Fallback to plain merge (no translation API)
            base_page.merge_page(template_page)
            logging.info("Merged template with merge_page (no dx/dy supported)")
    except Exception as e:
        logging.exception(f"Template merge failed; falling back to merge_page: {e}")
        base_page.merge_page(template_page)

    # Write final
    writer = PdfWriter()
    writer.add_page(base_page)
    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    pdf_bytes = out_buf.getvalue()

    # Sanity: first bytes
    logging.info(f"PDF first 120 bytes: {pdf_bytes[:120]}")
    return pdf_bytes

# --- Routes ---
@app.route("/")
def health():
    return jsonify({"ok": True})

@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    try:
        body = request.get_json(force=True)
        property_id = body.get("property_id")
        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        logging.info(f"Received request for property_id={property_id}")
        row = fetch_property_row(property_id)
        logging.info(f"Fetched property row: {row}")

        pdf_bytes = build_pdf(row)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="qr_property.pdf"
        )
    except Exception as e:
        logging.exception("PDF generation failed")
        return jsonify({"error": str(e)}), 500

# --- Main Entrypoint ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))