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
# Reference from extracted bounding boxes
QR_LABEL_X0 = 60.47
QR_LABEL_X1 = 238.87
QR_LABEL_Y0 = 326.52
QR_LABEL_Y1 = 345.07

QR_SIZE = 140
QR_Y_OFFSET = -30  # lower from the label, so no overlap
CODE_X_LEFT = 375  # align with left edge of blue line
CODE_Y = 205       # nudged up more than before
NAME_Y = 100       # property name stays unchanged

# --- Helpers ---
def fetch_property_row(property_id):
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
    logging.info("Generating QR code...")
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
    template_path = os.path.join(os.path.dirname(__file__), "vss-template-flat.pdf")
    reader = PdfReader(template_path)
    writer = PdfWriter()

    # Overlay
    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=letter)
    width, height = letter

    # Property Code
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Helvetica"
    style.fontSize = 12
    para = Paragraph(property_row["code"], style)
    frame_width = 200
    frame = Frame(CODE_X_LEFT, CODE_Y, frame_width, 40, showBoundary=0)
    frame.addFromList([para], c)

    # Property Name
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, NAME_Y, property_row["property_name"])

    # QR Code centered under "Scan the QR Code:" text
    qr_img = generate_qr_code(property_row["qr_url"])
    qr_center_x = (QR_LABEL_X0 + QR_LABEL_X1) / 2
    qr_x = qr_center_x - (QR_SIZE / 2)
    qr_y = QR_LABEL_Y0 + QR_Y_OFFSET - QR_SIZE
    c.drawImage(qr_img, qr_x, qr_y, width=QR_SIZE, height=QR_SIZE, mask="auto")

    c.save()
    overlay_buf.seek(0)

    # Merge with template
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