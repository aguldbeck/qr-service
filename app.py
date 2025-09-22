import os
import io
import logging
import requests
import qrcode
from flask import Flask, request, Response
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader

app = Flask(__name__)

# Enable debug logs via env var
DEBUG_MODE = os.getenv("DEBUG_LOGS", "false").lower() == "true"
logging.basicConfig(level=logging.DEBUG if DEBUG_MODE else logging.INFO)


def fetch_property_row(property_id):
    """Fetch property details from Supabase REST API"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }

    url = f"{supabase_url}/rest/v1/properties?id=eq.{property_id}&select=id,code,property_name,qr_url"
    logging.info(f"Fetching property from {url}")

    r = requests.get(url, headers=headers)
    r.raise_for_status()
    rows = r.json()

    if DEBUG_MODE:
        logging.debug(f"Supabase response: {rows}")

    if not rows:
        raise ValueError(f"No property found with id {property_id}")

    return rows[0]


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    try:
        data = request.json
        property_id = data.get("property_id")

        if not property_id:
            return {"error": "Missing property_id"}, 400

        # Get property details
        row = fetch_property_row(property_id)
        property_code = row.get("code", "")
        property_name = row.get("property_name", "")
        qr_url = row.get("qr_url", "https://app.applyfastnow.com")

        # Create QR code
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Convert QR to ImageReader safely
        qr_bytes = io.BytesIO()
        qr_img.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)
        qr_reader = ImageReader(qr_bytes)

        # Create PDF in memory
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=letter)
        c.setFont("Helvetica", 14)
        c.drawString(72, 720, f"Property: {property_name}")
        c.drawString(72, 700, f"Code: {property_code}")
        c.drawImage(qr_reader, 72, 500, width=200, height=200)
        c.showPage()
        c.save()

        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()

        # 🔎 Force debug printout of first 100 bytes
        logging.info("First 100 bytes of generated PDF:\n" + str(pdf_bytes[:100]))

        # ✅ Return proper PDF
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": "attachment; filename=test.pdf"}
        )

    except Exception as e:
        logging.exception("PDF generation failed")
        return {"error": str(e)}, 500


@app.route("/")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)