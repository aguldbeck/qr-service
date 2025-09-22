import os
import io
import qrcode
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image

# Initialize Flask app
app = Flask(__name__)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Path to your static template
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")


def generate_qr_code(url: str) -> Image.Image:
    """Generate a QR code image for given URL and return PIL Image."""
    qr_img = qrcode.make(url)
    return qr_img


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    Generate a styled PDF:
      - Query Supabase for property info using property_id
      - Overlay code, property_name, and QR onto vss-template.pdf
      - Return final PDF
    """
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Fetch property details from Supabase
        resp = supabase.table("properties").select("code, property_name, qr_url").eq("id", property_id).single().execute()
        if not resp.data:
            return jsonify({"error": f"No property found for id '{property_id}'"}), 404

        code = resp.data["code"]
        name = resp.data["property_name"]
        url = resp.data.get("qr_url") or f"https://app.applyfastnow.com/landing/{code}"

        # Generate QR code (PIL Image)
        qr_img = generate_qr_code(url)
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)

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