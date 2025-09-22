import os
import io
import qrcode
import logging
from flask import Flask, request, jsonify, Response
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfReader, PdfWriter

# Initialize Flask app
app = Flask(__name__)

# Logging setup
DEBUG_MODE = os.getenv("DEBUG_LOGS", "false").lower() == "true"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"Logging initialized. DEBUG_MODE={DEBUG_MODE}")

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Path to your static template (shipped in repo)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")


def generate_qr_code(url: str) -> io.BytesIO:
    """Generate a QR code image for given URL and return BytesIO."""
    qr_img = qrcode.make(url)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    Generate a styled PDF:
      - Query Supabase for property data using property_id
      - Overlay code, name, and QR onto vss-template.pdf
      - Return final PDF as download
    """
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Fetch property info
        resp = (
            supabase.table("properties")
            .select("id, code, property_name, qr_url")
            .eq("id", property_id)
            .single()
            .execute()
        )

        if not resp.data:
            return jsonify({"error": f"No property found for id '{property_id}'"}), 404

        prop = resp.data
        prop_code = prop["code"]
        prop_name = prop["property_name"]
        qr_url = prop.get("qr_url")

        if not qr_url:
            return jsonify({"error": f"No qr_url set for property '{prop_code}'"}), 400

        if DEBUG_MODE:
            logger.info(f"Property fetched: {prop}")

        # Generate QR code
        qr_buf = generate_qr_code(qr_url)
        qr_img = ImageReader(qr_buf)

        # Read template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay (text + QR)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        # Overlay property code & name
        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {prop_code}")
        can.drawString(100, 700, f"Property Name: {prop_name}")

        # Overlay QR code
        can.drawImage(qr_img, 400, 600, 150, 150)

        can.save()
        packet.seek(0)

        overlay = PdfReader(packet)
        template_page = reader.pages[0]
        template_page.merge_page(overlay.pages[0])

        writer.add_page(template_page)

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        # Debug header check
        if DEBUG_MODE:
            head = output.getvalue()[:200]
            logger.info(f"PDF header bytes: {head}")

        return Response(
            output.getvalue(),
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={prop_code}.pdf"},
        )

    except Exception as e:
        logger.exception("Error in /generate_pdf")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))