import os
import io
import qrcode
import traceback
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter

app = Flask(__name__)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")


def generate_qr_code(url: str) -> io.BytesIO:
    qr_img = qrcode.make(url)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    try:
        data = request.json
        prop_id = data.get("property_id")
        if not prop_id:
            return jsonify({"error": "Missing property_id"}), 400

        # Query properties table
        resp = supabase.table("properties").select(
            "id, code, name, qr_url"
        ).eq("id", prop_id).single().execute()

        if not resp.data:
            return jsonify({"error": f"No property found for id '{prop_id}'"}), 404

        prop = resp.data
        slug = prop.get("code", "")
        name = prop.get("name", "")
        url = prop.get("qr_url", "https://app.applyfastnow.com")

        # Generate QR
        qr_buf = generate_qr_code(url)

        # Read template
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()

        # Create overlay
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)
        can.setFont("Helvetica-Bold", 14)
        can.drawString(100, 720, f"Property Code: {slug}")
        can.drawString(100, 700, f"Property Name: {name}")
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
            download_name=f"{slug or prop_id}.pdf",
        )

    except Exception as e:
        # Print full traceback to logs for debugging
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))