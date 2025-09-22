import os
import io
import qrcode
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter

# Initialize Flask app
app = Flask(__name__)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Path to your static template (shipped in repo)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")

# Default URL fallback if none exists
DEFAULT_URL = "https://app.applyfastnow.com"


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
    Generate a styled PDF for a property:
      - Query Supabase for property (by property_id)
      - Use qr_url if set, else fallback to DEFAULT_URL
      - Overlay property code, name, and QR onto template
    """
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Fetch property row
        resp = supabase.table("properties").select(
            "id, code, name, qr_url"
        ).eq("id", property_id).single().execute()

        if not resp.data:
            return jsonify({"error": f"No property found for id '{property_id}'"}), 404

        prop = resp.data
        code = prop.get("code", "UNKNOWN")
        name = prop.get("name", "Unnamed Property")
        qr_url = prop.get("qr_url") or DEFAULT_URL

        # Generate QR code
        qr_buf = generate_qr_code(qr_url)

        # Read template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        # Overlay text
        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {code}")
        can.drawString(100, 700, f"Property Name: {name}")

        # Overlay QR
        can.drawInlineImage(qr_buf, 400, 600, 150, 150)

        can.save()
        packet.seek(0)

        overlay = PdfReader(packet)
        template_page = reader.pages[0]
        template_page.merge_page(overlay.pages[0])

        writer.add_page(template_page)

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{code}.pdf",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))