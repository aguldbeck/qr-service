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

# --- Template path ---
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template-flat.pdf")

# --- Page size ---
PAGE_W, PAGE_H = letter  # 612 x 792

# --- Anchors ---
SCAN_X0, SCAN_X1 = 60.471, 238.875
SCAN_Y0, SCAN_Y1 = 326.522, 345.077
BLUE_X_LEFT, BLUE_X_RIGHT = 375.616, 555.895

# --- Layout ---
Y_NAME = 92
Y_CODE = 210
CODE_FRAME_WIDTH = BLUE_X_RIGHT - BLUE_X_LEFT
CODE_FRAME_HEIGHT = 48

QR_SIZE = 200
QR_TOP_GAP = 12
QR_CENTER_X = (SCAN_X0 + SCAN_X1) / 2.0
QR_X = QR_CENTER_X - (QR_SIZE / 2.0)
QR_Y = (SCAN_Y0 - QR_TOP_GAP) - QR_SIZE
QR_X = max(0, min(QR_X, PAGE_W - QR_SIZE))
QR_Y = max(0, min(QR_Y, PAGE_H - QR_SIZE))


# --- Helpers ---
def fetch_property_row(property_id: str) -> dict:
    url = f"{SUPABASE_URL}/rest/v1/properties"
    params = {
        "id": f"eq.{property_id}",
        "select": "id,code,property_name,qr_url"
    }
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError("Property not found")
    return data[0]

def generate_qr_code(data: str) -> ImageReader:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)

def build_pdf(property_row: dict) -> bytes:
    logging.info("Building PDF...")
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()

    # --- Normalize mediabox/cropbox ---
    template_page = reader.pages[0]
    template_page.mediabox.lower_left = (0, 0)
    template_page.cropbox.lower_left = (0, 0)
    logging.info(f"Template mediabox: {template_page.mediabox}")
    logging.info(f"Template cropbox: {template_page.cropbox}")

    # --- Overlay ---
    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=letter)

    # Property Code
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Helvetica"
    style.fontSize = 12
    para = Paragraph(property_row["code"], style)
    frame = Frame(CODE_FRAME_WIDTH + BLUE_X_LEFT - CODE_FRAME_WIDTH, Y_CODE, CODE_FRAME_WIDTH, CODE_FRAME_HEIGHT, showBoundary=0)
    frame.addFromList([para], c)

    # Property Name
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(PAGE_W / 2.0, Y_NAME, property_row["property_name"])

    # QR Code
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, QR_X, QR_Y, width=QR_SIZE, height=QR_SIZE, mask="auto")

    c.save()
    overlay_buf.seek(0)

    # --- Merge ---
    overlay_pdf = PdfReader(overlay_buf)
    template_page.merge_page(overlay_pdf.pages[0])
    writer.add_page(template_page)

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    return out_buf.getvalue()


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
        row = fetch_property_row(property_id)
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))