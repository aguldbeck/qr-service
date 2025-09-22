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


def generate_qr_code(url: str) -> str:
    """Generate a QR code image, save it to a temporary file, and return path."""
    buf = io.BytesIO()
    img = qrcode.make(url)
    img.save(buf, format="PNG")
    buf.seek(0)

    tmp_path = "/tmp/qr.png"
    with open(tmp_path, "wb") as f:
        f.write(buf.getvalue())
    return tmp_path


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    Generate a styled PDF:
      - Fetch property by ID from Supabase
      - Use properties.code, properties.property_name, properties.qr_url
      - Overlay onto vss-template.pdf
    """
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Query Supabase for property details
        resp = (
            supabase.table("properties")
            .select("code, property_name, qr_url")
            .eq("id", property_id)
            .single()
            .execute()
        )

        if not resp.data:
            return jsonify({"error": f"No property found for id '{property_id}'"}), 404

        code = resp.data.get("code", "")
        name = resp.data.get("property_name", "")
        url = resp.data.get("qr_url", "https://app.applyfastnow.com")

        # Generate QR code to temp file
        qr_path = generate_qr_code(url)

        # Load template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay (text + QR)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {code}")
        can.drawString(100, 700, f"Property Name: {name}")
        can.drawString(100, 680, f"URL: {url}")

        # Overlay QR code from file
        can.drawImage(qr_path, 400, 600, 150, 150)

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