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

# --- Layout constants ---
X_LEFT_BLUE = 350    # left edge of blue line
X_RIGHT_BLUE = 550   # right edge of blue line
Y_CODE = 190         # property code (raised half a line)
Y_NAME = 115         # property name (moved up slightly)
QR_Y = 140           # QR code moved further down
QR_SIZE = 180        # QR code size
PAGE_WIDTH, PAGE_HEIGHT = letter

# --- Helpers ---
def fetch_property_row(property_id):
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
    template_path = os.path.join(os.path.dirname(__file__), "vss-template-flat.pdf")
    reader = PdfReader(template_path)
    writer = PdfWriter()

    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=letter)

    # Property Code (wrapped inside blue line bounds, aligned to left edge)
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Helvetica"
    style.fontSize = 12
    para = Paragraph(property_row["code"], style)
    frame_width = X_RIGHT_BLUE - X_LEFT_BLUE
    frame = Frame(X_LEFT_BLUE, Y_CODE, frame_width, 40, showBoundary=0)
    frame.addFromList([para], c)

    # Property Name (bigger, bold, centered, moved slightly up)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(PAGE_WIDTH / 2, Y_NAME, property_row["property_name"])

    # QR Code (centered under label)
    qr_img = generate_qr_code(property_row["qr_url"])
    qr_x = (PAGE_WIDTH - QR_SIZE) / 2 - 150  # adjust to center under label
    c.drawImage(qr_img, qr_x, QR_Y, width=QR_SIZE, height=QR_SIZE, mask="auto")

    c.save()
    overlay_buf.seek(0)

    overlay_pdf = PdfReader(overlay_buf)
    template_page = reader.pages[0]
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