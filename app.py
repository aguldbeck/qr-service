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
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return ImageReader(buf)

def build_pdf(property_row: dict) -> bytes:
    """Overlay QR code, code, and name on template"""
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()

    # Coordinates (hardcoded debug)
    qr_x, qr_y = 72, 120        # left-bottom area
    code_x, code_y = 350, 180   # right area near line
    name_x, name_y = 300, 80    # centered bottom

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)

    # Draw QR code
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, qr_x, qr_y, width=120, height=120, mask="auto")

    # Red debug box around QR
    c.setStrokeColorRGB(1, 0, 0)
    c.rect(qr_x, qr_y, 120, 120, fill=0)

    # Draw property code
    c.setFont("Helvetica-Bold", 14)
    c.drawString(code_x, code_y, property_row["code"])
    c.rect(code_x, code_y - 5, 120, 20, fill=0)

    # Draw property name
    c.setFont("Helvetica", 12)
    c.drawCentredString(name_x, name_y, property_row["property_name"])
    c.rect(name_x - 100, name_y - 5, 200, 20, fill=0)

    c.save()
    packet.seek(0)

    overlay = PdfReader(packet)
    page = reader.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output.getvalue()

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

# --- Main Entrypoint ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))