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
    return ImageReader(buf)

def build_pdf(property_row: dict) -> bytes:
    """Generate PDF using template, overlay text + QR"""
    logging.info("Building PDF...")

    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    width, height = letter

    # --- Mask old QR with white rectangle ---
    c.setFillColorRGB(1, 1, 1)  # white
    c.rect(80, height - 420, 240, 240, fill=1, stroke=0)

    # --- Debug red box for QR ---
    c.setStrokeColorRGB(1, 0, 0)
    c.rect(80, height - 420, 240, 240, fill=0)

    # --- Place QR ---
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, 100, height - 400, width=200, height=200, mask="auto")

    # --- Property code text ---
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(350, height - 200, f"Code: {property_row['code']}")

    # --- Property name centered at bottom ---
    c.setFont("Helvetica-Bold", 12)
    prop_name = property_row['property_name']
    text_width = c.stringWidth(prop_name, "Helvetica-Bold", 12)
    x = (width - text_width) / 2
    y = 80
    c.drawString(x, y, prop_name)

    # --- Debug red box for property name area ---
    c.setStrokeColorRGB(1, 0, 0)
    c.rect(x - 10, y - 5, text_width + 20, 20, fill=0)

    c.save()
    packet.seek(0)

    overlay = PdfReader(packet)
    base_page = reader.pages[0]
    base_page.merge_page(overlay.pages[0])
    writer.add_page(base_page)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    pdf_bytes = output.getvalue()

    logging.info(f"PDF generated, size={len(pdf_bytes)} bytes")
    logging.info(f"First 200 bytes: {pdf_bytes[:200]}")

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