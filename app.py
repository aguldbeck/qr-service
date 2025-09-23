import io
import os
import logging
import requests
import qrcode
from flask import Flask, request, send_file, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pdf2image import convert_from_path  # ✅ new dependency

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
    if DEBUG_MODE:
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
    """Overlay template as background, then draw QR + text"""
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=letter)
    width, height = letter

    # Step 1: render template PDF as image
    logging.info("Rendering template PDF to image...")
    template_img = convert_from_path(TEMPLATE_PATH, dpi=150)[0]  # first page only
    img_buf = io.BytesIO()
    template_img.save(img_buf, format="PNG")
    img_buf.seek(0)
    bg = ImageReader(img_buf)
    c.drawImage(bg, 0, 0, width=width, height=height)

    # Step 2: draw QR + code + name ON TOP
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, 72, height - 400, width=150, height=150, mask="auto")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(300, height - 250, property_row["code"])  # code in line on right

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, 80, property_row["property_name"])  # bottom centered

    # Finalize
    c.showPage()
    c.save()
    pdf_data = output.getvalue()
    output.close()

    logging.info(f"Generated PDF size={len(pdf_data)} bytes")
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