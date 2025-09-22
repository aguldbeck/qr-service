import os
import io
import tempfile
import logging
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfReader, PdfWriter
import qrcode
from PIL import Image

# Initialize Flask app
app = Flask(__name__)

# Debug logging toggle
DEBUG_MODE = os.getenv("DEBUG_LOGS", "false").lower() == "true"
logging.basicConfig(level=logging.DEBUG if DEBUG_MODE else logging.INFO)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Path to your static template (shipped in repo)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")


def generate_qr_code(url: str) -> str:
    """Generate a QR code image for given URL and return path to temp PNG."""
    qr_img = qrcode.make(url)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    qr_img.save(tmp_file, format="PNG")
    tmp_file.close()
    logging.debug(f"Generated QR code for {url}, saved at {tmp_file.name}")
    return tmp_file.name


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    Generate a styled PDF:
      - Query Supabase for property data using property_id
      - Overlay property code, name, and QR onto vss-template.pdf
      - Return final PDF
    """
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Fetch property row from Supabase
        resp = supabase.table("properties").select(
            "id, code, property_name, qr_url"
        ).eq("id", property_id).single().execute()

        if not resp.data:
            return jsonify({"error": f"No property found for id '{property_id}'"}), 404

        prop = resp.data
        code = prop.get("code", "N/A")
        name = prop.get("property_name", "Unknown Property")
        url = prop.get("qr_url", "https://app.applyfastnow.com")

        logging.debug(f"Fetched property: {prop}")

        # Generate QR code
        qr_path = generate_qr_code(url)
        qr_img = Image.open(qr_path)
        qr_reader = ImageReader(qr_img)

        # Read template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay (text + QR)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        # Overlay property code & name
        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {code}")
        can.drawString(100, 700, f"Property Name: {name}")

        # Overlay QR code
        can.drawImage(qr_reader, 400, 600, 150, 150, mask='auto')

        can.save()
        packet.seek(0)

        overlay = PdfReader(packet)
        template_page = reader.pages[0]
        template_page.merge_page(overlay.pages[0])

        writer.add_page(template_page)

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        logging.debug(f"Successfully generated PDF for property_id {property_id}")

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{code}.pdf",
        )

    except Exception as e:
        logging.exception("Error generating PDF")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))