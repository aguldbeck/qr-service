import io
import os
import logging
import requests
import qrcode
from flask import Flask, request, send_file, jsonify
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
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
    "Content-Type": "application/json",
}

# Path to your template PDF
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")


# --- Helpers ---
def fetch_property_row(property_id):
    """Fetch property row from Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/properties"
    params = {"id": f"eq.{property_id}", "select": "id,code,property_name,qr_url"}
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
    """Overlay QR code, property code, and name onto the template"""
    # Step 1: Load template
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()
    base_page = reader.pages[0]

    # Step 2: Create overlay
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    width, height = letter

    # QR code → bottom-left under "Scan the QR Code"
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, 70, 180, width=180, height=180, mask="auto")

    # Property code → bottom-right above the blue line
    c.setFont("Helvetica-Bold", 18)
    c.drawString(380, 200, property_row["code"])

    # Property name → centered bottom just before footer
    c.setFont("Helvetica", 14)
    text_width = c.stringWidth(property_row["property_name"], "Helvetica", 14)
    c.drawString((width - text_width) / 2, 120, property_row["property_name"])

    c.save()
    packet.seek(0)

    # Step 3: Merge overlay onto template
    overlay_pdf = PdfReader(packet)
    base_page.merge_page(overlay_pdf.pages[0])
    writer.add_page(base_page)

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
            download_name="qr_property.pdf",
        )

    except Exception as e:
        logging.exception("PDF generation failed")
        return jsonify({"error": str(e)}), 500


# --- Main Entrypoint ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))