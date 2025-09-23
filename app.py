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

def draw_wrapped_text(c, text, x, y, max_width, font_name="Helvetica", font_size=14, leading=16):
    """Draw text with wrapping at max_width"""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    c.setFont(font_name, font_size)
    words = text.split()
    line = ""
    for word in words:
        test_line = f"{line} {word}".strip()
        if stringWidth(test_line, font_name, font_size) <= max_width:
            line = test_line
        else:
            c.drawString(x, y, line)
            y -= leading
            line = word
    if line:
        c.drawString(x, y, line)

def build_pdf(property_row: dict) -> bytes:
    """Generate PDF with QR code and property info"""
    logging.info("Building PDF...")
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=letter)
    width, height = letter

    # --- Coordinates (hardcoded for template) ---
    qr_x, qr_y = 72, height - 350  # bottom-left of QR
    qr_size = 150

    code_x = 300       # left edge of blue line
    code_y = height - 250
    code_width = 200   # wrap width until right edge of blue line

    name_y = 150       # bottom of white box
    name_font_size = 18

    # --- Draw Property Code (wrapped) ---
    logging.info("Drawing property code...")
    draw_wrapped_text(
        c,
        property_row['code'],
        code_x,
        code_y,
        max_width=code_width,
        font_name="Helvetica",
        font_size=14,
        leading=16
    )

    # --- Draw Property Name (bold, centered) ---
    logging.info("Drawing property name...")
    c.setFont("Helvetica-Bold", name_font_size)
    text_width = c.stringWidth(property_row['property_name'], "Helvetica-Bold", name_font_size)
    c.drawString((width - text_width) / 2, name_y, property_row['property_name'])

    # --- QR Code ---
    logging.info("Embedding QR code...")
    qr_img = generate_qr_code(property_row["qr_url"])
    c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size)

    # Finalize
    c.showPage()
    c.save()
    pdf_data = output.getvalue()
    output.close()

    logging.info(f"PDF generated, size={len(pdf_data)} bytes")
    logging.info(f"First 100 bytes: {pdf_data[:100]}")
    logging.info(f"First 1000 bytes: {pdf_data[:1000]}")

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