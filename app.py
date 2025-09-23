import io
import os
import logging
import requests
import qrcode
from flask import Flask, request, send_file, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
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

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")

# --- Helpers ---
def fetch_property_row(property_id):
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
    logging.info("Generating QR code...")
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    logging.info(f"QR code generated, size={len(buf.getvalue())} bytes")
    return ImageReader(buf)

def build_pdf(property_row: dict) -> bytes:
    """Overlay QR, property info, and debug box on template"""
    logging.info("Building PDF...")
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()

    base_page = reader.pages[0]

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    width, height = letter

    # Debug red rectangle (expected QR area)
    c.setStrokeColorRGB(1, 0, 0)
    c.setLineWidth(2)
    c.rect(90, height - 420, 220, 220)  # adjust once we confirm alignment

    # Property code (right above QR)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(100, height - 440, f"Code: {property_row['code']}")

    # Property name (bottom center white band)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, 80, property_row['property_name'])

    # QR code
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, 100, height - 400, width=200, height=200, mask="auto")

    c.save()
    packet.seek(0)

    overlay = PdfReader(packet)
    base_page.merge_page(overlay.pages[0])
    writer.add_page(base_page)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    pdf_data = output.getvalue()
    logging.info(f"PDF generated, size={len(pdf_data)} bytes")
    logging.info(f"First 200 bytes: {pdf_data[:200]}")

    return pdf_data

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