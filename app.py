import os
import io
import logging
import qrcode
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfReader, PdfWriter

# --------------------------------------------------
# Logging setup with toggle
# --------------------------------------------------
DEBUG_MODE = os.getenv("DEBUG_LOGS", "false").lower() == "true"
log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)
logger.info(f"Logging initialized. DEBUG_MODE={DEBUG_MODE}")

# --------------------------------------------------
# Flask app
# --------------------------------------------------
app = Flask(__name__)

# --------------------------------------------------
# Supabase client
# --------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Path to static template (shipped in repo)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")


def generate_qr_code(url: str) -> io.BytesIO:
    """Generate a QR code PNG in memory and return BytesIO."""
    qr_img = qrcode.make(url)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    Generate a styled PDF for a property:
      - Look up property by id in Supabase
      - Use its code, property_name, qr_url
      - Overlay onto vss-template.pdf
    """
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Fetch property info
        logger.debug(f"Fetching property {property_id} from Supabase")
        resp = (
            supabase.table("properties")
            .select("code, property_name, qr_url")
            .eq("id", property_id)
            .single()
            .execute()
        )

        if not resp.data:
            logger.error(f"No property found for id {property_id}")
            return jsonify({"error": f"No property found for id {property_id}"}), 404

        code = resp.data.get("code")
        name = resp.data.get("property_name")
        url = resp.data.get("qr_url")

        if not url:
            logger.error(f"Property {property_id} has no qr_url set")
            return jsonify({"error": "Property has no qr_url set"}), 400

        logger.debug(f"Generating QR code for URL: {url}")
        qr_buf = generate_qr_code(url)
        qr_img = ImageReader(qr_buf)

        # Read template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        # Overlay property code & name
        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {code}")
        can.drawString(100, 700, f"Property Name: {name}")

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

        # Debug: log first bytes of PDF
        if DEBUG_MODE:
            preview = output.getvalue()[:100]
            logger.debug(f"PDF header bytes: {preview!r}")

        logger.info(f"Successfully generated PDF for {property_id} ({code}, {name})")

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{code}.pdf",
        )

    except Exception as e:
        logger.exception("Error while generating PDF")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))