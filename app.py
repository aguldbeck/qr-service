import os
import io
import qrcode
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# Initialize Flask app
app = Flask(__name__)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Bucket name for QR codes
BUCKET_NAME = "qr-codes"


@app.route("/generate_qr", methods=["POST"])
def generate_qr():
    """
    Generates a QR code for a given slug + URL and stores it in Supabase.
    """
    try:
        data = request.json
        slug = data.get("slug")
        url = data.get("url")

        if not slug or not url:
            return jsonify({"error": "Missing slug or url"}), 400

        # Generate QR code
        img = qrcode.make(url)
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        file_path = f"landing_pages/{slug}.png"

        # Upload to Supabase
        supabase.storage.from_(BUCKET_NAME).upload(file_path, img_bytes.getvalue(), {"upsert": True})

        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

        return jsonify({
            "slug": slug,
            "qr_code_url": public_url
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    Generates a PDF that includes a QR code linking to the provided URL.
    """
    try:
        data = request.json
        slug = data.get("slug")
        url = data.get("url")

        if not slug or not url:
            return jsonify({"error": "Missing slug or url"}), 400

        # Generate QR code
        qr = qrcode.make(url)
        qr_bytes = io.BytesIO()
        qr.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)

        # Create PDF
        pdf_bytes = io.BytesIO()
        pdf = canvas.Canvas(pdf_bytes, pagesize=letter)
        pdf.drawString(100, 750, f"Property: {slug}")
        pdf.drawString(100, 730, f"URL: {url}")
        pdf.drawInlineImage(qr_bytes, 100, 550, 150, 150)
        pdf.save()
        pdf_bytes.seek(0)

        return send_file(
            pdf_bytes,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{slug}.pdf"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))