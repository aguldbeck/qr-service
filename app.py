import io
import os
import logging
import requests
import qrcode
from flask import Flask, request, send_file, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

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
    """Generate PDF with template, QR code, and property info"""
    from PyPDF2 import PdfReader, PdfWriter

    # Load template
    reader = PdfReader(TEMPLATE_PATH)
    template_page = reader.pages[0]

    # Create overlay
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    width, height = letter

    # --- QR Code placement (left side under "Scan the QR Code") ---
    qr_img = generate_qr_code(property_row["qr_url"])
    qr_x, qr_y = 72, height - 400
    c.drawImage(qr_img, qr_x, qr_y, width=200, height=200, mask="auto")
    # Debug red box
    c.setStrokeColorRGB(1, 0, 0)
    c.rect(qr_x, qr_y, 200, 200)

    # --- Property Code placement (right side, above blue line) ---
    code_x, code_y = 350, height - 250
    c.setFont("Helvetica-Bold", 16)
    c.drawString(code_x, code_y, property_row["code"])
    # Debug red box
    c.setStrokeColorRGB(1, 0, 0)
    c.rect(code_x - 5, code_y - 5, 150, 25)

    # --- Property Name placement (bottom center) ---
    name_x, name_y = width / 2, 80
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(name_x, name_y, property_row["property_name"])
    # Debug red box
    c.setStrokeColorRGB(1, 0, 0)
    c.rect(name_x - 150, name_y - 10, 300, 25)

    c.save()
    packet.seek(0)

    # Merge overlay with template
    overlay = PdfReader(packet)
    writer = PdfWriter()
    template_page.merge_page(overlay.pages[0])
    writer.add_page(template_page)

    # Export final PDF
    output = io.BytesIO()
    writer.write(output)
    pdf_bytes = output.getvalue()
    output.close()

    logging.info(f"PDF generated, size={len(pdf_bytes)} bytes")
    logging.info(f"First 100 bytes: {pdf_bytes[:100]}")
    logging.info(f"First 1000 bytes: {pdf_bytes[:1000]}")

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