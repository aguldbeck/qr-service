import os
import io
from flask import Flask, request, jsonify
import qrcode
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=".env")

app = Flask(__name__)

# --- Supabase client ---
SUPABASE_URL = "https://bcxmqfediieeppmrusxj.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY env var")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Storage bucket + path prefix
BUCKET = "qr-codes"
PATH_PREFIX = "landing_pages"  # folder inside bucket


@app.get("/health")
def health():
    return {"ok": True}


def _upload_png_and_get_public_url(slug: str, png_bytes: bytes) -> str:
    file_path = f"{PATH_PREFIX}/{slug}.png"
    print(f"📤 Uploading QR for slug={slug} to {BUCKET}/{file_path}")

    supabase.storage.from_(BUCKET).upload(
        path=file_path,
        file=png_bytes,
        file_options={
            "content-type": "image/png",
            "x-upsert": "true",
        },
    )

    public_url = supabase.storage.from_(BUCKET).get_public_url(file_path)
    print(f"✅ Public URL generated: {public_url}")
    return public_url


def _generate_png_bytes(data: str, box_size=10, border=4) -> bytes:
    print(f"🔗 Generating QR for: {data}")
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.post("/generate_qr")
def generate_qr():
    """Generate QR for a single slug + URL (manual mode)."""
    payload = request.get_json(force=True, silent=True) or {}
    slug = payload.get("slug")
    url = payload.get("url")

    if not slug or not url:
        return jsonify({"error": "Missing slug or url"}), 400

    print(f"\n--- Generating single QR ---")
    print(f"Slug: {slug}")
    print(f"URL: {url}")

    # Make PNG
    png_bytes = _generate_png_bytes(url)

    # Upload to storage
    public_url = _upload_png_and_get_public_url(slug, png_bytes)

    # Update DB
    print(f"📝 Updating DB for slug={slug}")
    supabase.table("landing_pages").update(
        {"qr_code_url": public_url}
    ).eq("slug", slug).execute()

    print(f"🎉 Done for slug={slug}")
    return jsonify({"slug": slug, "qr_code_url": public_url}), 200


@app.post("/generate_missing")
def generate_missing():
    """Bulk-generate QRs for any landing_pages without qr_code_url."""
    print("\n=== Running bulk QR generation ===")
    resp = supabase.table("landing_pages").select(
        "slug,qr_code_url"
    ).is_("qr_code_url", None).execute()

    rows = resp.data or []
    print(f"Found {len(rows)} landing pages missing QR codes")

    updated = []

    for row in rows:
        slug = row.get("slug")
        if not slug:
            continue

        # Auto-build URL from slug
        url = f"https://app.applyfastnow.com/landing/{slug}"
        print(f"\nProcessing slug={slug} → url={url}")

        png_bytes = _generate_png_bytes(url)
        public_url = _upload_png_and_get_public_url(slug, png_bytes)

        print(f"📝 Updating DB for slug={slug}")
        supabase.table("landing_pages").update(
            {"qr_code_url": public_url}
        ).eq("slug", slug).execute()

        updated.append({"slug": slug, "qr_code_url": public_url})
        print(f"✅ Completed slug={slug}")

    print(f"\n=== Bulk generation finished: {len(updated)} updated ===")
    return jsonify({"count": len(updated), "items": updated}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))