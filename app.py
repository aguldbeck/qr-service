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
      - Query Supabase for property URL using slug
      - Overlay slug (property code), name, and QR onto vss-template.pdf
      - Return final PDF
    """
    try:
        data = request.json
        slug = data.get("slug")
        name = data.get("name")

        if not slug:
            return jsonify({"error": "Missing slug"}), 400
        if not name:
            return jsonify({"error": "Missing property name"}), 400

        # Fetch URL from Supabase
        resp = supabase.table("landing_pages").select("url").eq("slug", slug).single().execute()
        if not resp.data:
            return jsonify({"error": f"No URL found for slug '{slug}'"}), 404
        url = resp.data["url"]

        # Generate QR code
        qr_buf = generate_qr_code(url)

        # Read template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay (text + QR)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        # Overlay property code & name
        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {slug}")
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
            download_name=f"{slug}.pdf",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))