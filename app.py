import os
import io
import logging
from typing import Optional, Dict

import qrcode
from flask import Flask, request, jsonify, send_file
from supabase import create_client, Client
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfReader, PdfWriter

# ------------------------------------------------------------------------------
# Logging (toggle with DEBUG_LOGS=true)
# ------------------------------------------------------------------------------
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "false").lower() in ("1", "true", "yes", "y")
logging.basicConfig(
    level=logging.DEBUG if DEBUG_LOGS else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Flask
# ------------------------------------------------------------------------------
app = Flask(__name__)

# ------------------------------------------------------------------------------
# Supabase
# ------------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    log.warning("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set; DB calls will fail.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------------------------------------------------------------------
# Static template (must be committed at repo root)
# ------------------------------------------------------------------------------
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "vss-template.pdf")
if not os.path.exists(TEMPLATE_PATH):
    log.warning("Template not found at %s", TEMPLATE_PATH)

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _qr_image_reader(url: str) -> ImageReader:
    """
    Generate a QR code PIL.Image and wrap with ReportLab ImageReader.
    This avoids BytesIO 'format' attribute errors completely.
    """
    log.debug("Generating QR for URL: %s", url)
    pil_img = qrcode.make(url)  # PIL.Image
    return ImageReader(pil_img)


def _fetch_property_row(property_id: str) -> Optional[Dict]:
    """
    Fetch a single property row by UUID. We expect columns:
      id, property_code, property_name, qr_url, landing_page_id
    """
    log.debug("Fetching property row for id=%s", property_id)
    resp = supabase.table("properties").select(
        "id, property_code, property_name, qr_url, landing_page_id"
    ).eq("id", property_id).single().execute()
    log.debug("Property query response: %s", resp.data)
    return resp.data


def _fetch_landing_page_url(landing_page_id: Optional[str]) -> Optional[str]:
    if not landing_page_id:
        return None
    log.debug("Fetching landing page url for id=%s", landing_page_id)
    resp = supabase.table("landing_pages").select("url").eq("id", landing_page_id).single().execute()
    log.debug("Landing page query response: %s", resp.data)
    if resp.data and resp.data.get("url"):
        return resp.data["url"]
    return None


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True})


@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    """
    POST JSON:
      {
        "property_id": "<uuid>"
      }

    Behavior:
      - Load vss-template.pdf
      - Fetch properties row by UUID
      - Compute target URL (properties.qr_url -> landing_pages.url -> default)
      - Draw property_code, property_name, and QR onto an overlay
      - Merge overlay with template and return PDF
    """
    try:
        data = request.get_json(silent=True) or {}
        property_id = data.get("property_id")

        if not property_id:
            return jsonify({"error": "Missing property_id"}), 400

        if not os.path.exists(TEMPLATE_PATH):
            return jsonify({"error": f"Template not found at {TEMPLATE_PATH}"}), 500

        # 1) Fetch property
        prop = _fetch_property_row(property_id)
        if not prop:
            return jsonify({"error": f"No property found for id '{property_id}'"}), 404

        property_code = prop.get("property_code") or ""
        property_name = prop.get("property_name") or ""

        # 2) Determine QR target URL
        target_url = prop.get("qr_url")
        if not target_url:
            # try from landing_pages if linked
            target_url = _fetch_landing_page_url(prop.get("landing_page_id"))
        if not target_url:
            # final fallback
            target_url = "https://app.applyfastnow.com"

        log.debug("Resolved target_url=%s", target_url)
        log.debug("Using property_code=%s property_name=%s", property_code, property_name)

        # 3) Build overlay with ReportLab (text + QR)
        overlay_packet = io.BytesIO()
        can = canvas.Canvas(overlay_packet, pagesize=letter)

        # Adjust these coordinates to place text precisely on your template
        # (0,0) is bottom-left; letter is 612x792 points.
        # Example placements:
        text_x = 72   # 1 inch from left
        text_y_name = 700
        text_y_code = 680

        can.setFont("Helvetica-Bold", 13)
        can.drawString(text_x, text_y_name, f"Property: {property_name}")
        can.drawString(text_x, text_y_code, f"Code: {property_code}")

        # QR placement & size in points
        qr_x = 430
        qr_y = 560
        qr_size = 150

        qr_reader = _qr_image_reader(target_url)
        can.drawImage(qr_reader, qr_x, qr_y, width=qr_size, height=qr_size, mask=None)

        can.save()
        overlay_packet.seek(0)

        # 4) Merge overlay onto template
        base_reader = PdfReader(TEMPLATE_PATH)
        if not base_reader.pages:
            return jsonify({"error": "Template has no pages"}), 500

        overlay_reader = PdfReader(overlay_packet)
        base_page = base_reader.pages[0]
        base_page.merge_page(overlay_reader.pages[0])

        writer = PdfWriter()
        writer.add_page(base_page)

        out_pdf = io.BytesIO()
        writer.write(out_pdf)
        out_pdf.seek(0)

        # 5) Return PDF
        filename = f"{property_code or property_id}.pdf"
        return send_file(
            out_pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        log.exception("Error in /generate_pdf")
        return jsonify({"error": str(e)}), 500


# (Optional) Keep the QR-only endpoint around if you still need it.
@app.route("/generate_qr", methods=["POST"])
def generate_qr():
    """
    POST JSON:
      {"slug": "...", "url": "https://..."}
    Returns a PNG QR uploaded to Supabase Storage (bucket 'qr-codes/landing_pages/{slug}.png')
    """
    try:
        data = request.get_json(silent=True) or {}
        slug = data.get("slug")
        url = data.get("url")

        if not slug or not url:
            return jsonify({"error": "Missing slug or url"}), 400

        # Make QR (PIL image), then convert to bytes for storage
        pil_img = qrcode.make(url)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        buf.seek(0)

        bucket = "qr-codes"
        path = f"landing_pages/{slug}.png"

        supabase.storage.from_(bucket).upload(path, buf.getvalue(), {"upsert": True})
        public_url = supabase.storage.from_(bucket).get_public_url(path)

        return jsonify({"slug": slug, "qr_code_url": public_url})

    except Exception as e:
        log.exception("Error in /generate_qr")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Render sets PORT; default to 8000 for local runs
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)