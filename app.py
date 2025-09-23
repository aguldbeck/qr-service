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

# --- Template path (flattened) ---
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template-flat.pdf")

# --- Page size ---
PAGE_W, PAGE_H = letter  # 612 x 792

# --- Anchor: extracted bbox for "Scan the QR Code:" on the NON-flattened PDF ---
# These values let us center the QR under the label precisely.
SCAN_X0 = 60.471
SCAN_X1 = 238.875
SCAN_Y0 = 326.522
SCAN_Y1 = 345.077

# --- Blue line bounds (right column) to align property code left edge ---
# Taken from the "Go to ... and enter code:" block bbox:
BLUE_X_LEFT = 375.616
BLUE_X_RIGHT = 555.895

# --- Layout controls you asked for ---
# Property NAME: leave as-is (no change from last placement).
Y_NAME = 92  # keep what worked visually for you

# Property CODE: move left to align with blue line left edge; raise ~2 lines.
CODE_X_LEFT = BLUE_X_LEFT  # align left edge with blue line
CODE_FRAME_WIDTH = BLUE_X_RIGHT - BLUE_X_LEFT  # wrap width
Y_CODE = 210  # raised from earlier placements (about 2 lines)

# QR code: center under the "Scan the QR Code:" label, and drop below it so it doesn't overlap.
QR_SIZE = 200  # keep current scale
QR_TOP_GAP = 12  # pixels below the label before QR starts
QR_CENTER_X = (SCAN_X0 + SCAN_X1) / 2.0
QR_X = QR_CENTER_X - (QR_SIZE / 2.0)
QR_Y = (SCAN_Y0 - QR_TOP_GAP) - QR_SIZE  # place below label, no overlap

# Safety clamp so the QR doesn't go off-page
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

def build_pdf(property_row: dict) -> bytes:
    """Generate PDF with template, QR code, and property info"""
    logging.info("Building PDF with template overlay...")
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()

    # Create overlay canvas
    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=letter)

    # --- Property Code (wrapped) ---
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Helvetica"
    style.fontSize = 12
    para = Paragraph(property_row["code"], style)
    frame = Frame(CODE_X_LEFT, Y_CODE, CODE_FRAME_WIDTH, 48, showBoundary=0)
    frame.addFromList([para], c)

    # --- Property Name (unchanged) ---
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(PAGE_W / 2.0, Y_NAME, property_row["property_name"])

    # --- QR Code (centered under label, lowered to avoid overlap) ---
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, QR_X, QR_Y, width=QR_SIZE, height=QR_SIZE, mask="auto")

    # Debug coordinates (server logs)
    logging.info(f"QR placement -> x={QR_X:.2f}, y={QR_Y:.2f}, size={QR_SIZE}")
    logging.info(f"Code frame -> x={CODE_X_LEFT:.2f}, y={Y_CODE:.2f}, w={CODE_FRAME_WIDTH:.2f}, h=48")
    logging.info(f"Name -> x={PAGE_W/2.0:.2f}, y={Y_NAME:.2f}")

    # Finalize overlay
    c.save()
    overlay_buf.seek(0)

    # Merge overlay onto template
    overlay_pdf = PdfReader(overlay_buf)
    template_page = reader.pages[0]
    template_page.merge_page(overlay_pdf.pages[0])
    writer.add_page(template_page)

    # Output bytes
    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    pdf_bytes = out_buf.getvalue()

    # Force print first bytes in logs to confirm a valid PDF
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