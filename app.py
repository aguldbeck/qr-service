import os
import io
from flask import Flask, request, jsonify
import qrcode
from supabase import create_client, Client
from dotenv import load_dotenv
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

# Load env
load_dotenv(dotenv_path=".env")

app = Flask(__name__)

SUPABASE_URL = "https://bcxmqfediieeppmrusxj.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

BUCKET = "pdfs"   # create this in Supabase Storage


def _generate_qr_code_bytes(data: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_property_pdf(property_name: str, property_code: str, qr_url: str) -> bytes:
    qr_bytes = _generate_qr_code_bytes(qr_url)

    # Make PDF
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    # Header
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, height - 1.5 * inch, f"Property: {property_name}")

    c.setFont("Helvetica", 14)
    c.drawString(1 * inch, height - 2.0 * inch, f"Property Code: {property_code}")

    # Insert QR code
    qr_buf = io.BytesIO(qr_bytes)
    from PIL import Image
    qr_img = Image.open(qr_buf)
    qr_path = "/tmp/qr.png"
    qr_img.save(qr_path)
    c.drawImage(qr_path, 1 * inch, height - 4 * inch, width=2*inch, height=2*inch)

    c.showPage()
    c.save()

    buf.seek(0)
    return buf.getvalue()


def _upload_pdf_and_get_url(property_id: str, pdf_bytes: bytes) -> str:
    file_path = f"properties/{property_id}.pdf"
    supabase.storage.from_(BUCKET).upload(
        file_path,
        pdf_bytes,
        file_options={
            "content-type": "application/pdf",
            "x-upsert": "true",
        },
    )
    return supabase.storage.from_(BUCKET).get_public_url(file_path)


@app.post("/generate_property_pdf")
def generate_property_pdf():
    payload = request.get_json(force=True, silent=True) or {}
    property_id = payload.get("property_id")
    property_name = payload.get("property_name")
    property_code = payload.get("property_code")
    qr_url = payload.get("qr_url")

    if not property_id or not property_name or not property_code or not qr_url:
        return jsonify({"error": "Missing property_id, property_name, property_code, or qr_url"}), 400

    # Make PDF
    pdf_bytes = _generate_property_pdf(property_name, property_code, qr_url)

    # Upload
    public_url = _upload_pdf_and_get_url(property_id, pdf_bytes)

    # Update DB
    supabase.table("properties").update(
        {"pdf_url": public_url}
    ).eq("id", property_id).execute()

    return jsonify({"property_id": property_id, "pdf_url": public_url}), 200