import io
import zipfile
from typing import List, Tuple

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image
from rembg import remove


# ============================================================
# Streamlit page configuration
# ============================================================
# This should be called near the top of the app.
# It controls the browser tab title and the initial layout.
st.set_page_config(page_title="Background Remover", layout="wide")


# ============================================================
# Utility / helper functions
# ============================================================
# The goal of these helper functions is to keep the app logic
# organized and easy to follow. Each function does one clear job.


def pil_image_to_bytes(image: Image.Image, output_format: str = "PNG") -> bytes:
    """
    Convert a PIL Image into raw bytes.

    Why this exists:
    - Streamlit downloads work best when we have raw bytes.
    - We reuse this for both previewing and downloading files.

    Parameters:
    - image: The PIL image to convert.
    - output_format: File format to save as, usually PNG.

    Returns:
    - Byte string containing the encoded image.
    """
    buffer = io.BytesIO()
    image.save(buffer, format=output_format)
    return buffer.getvalue()



def remove_background_from_pil(image: Image.Image) -> Image.Image:
    """
    Remove the background from a PIL image using rembg.

    Important behavior:
    - The image is converted to RGBA first so transparency can be preserved.
    - rembg returns bytes, so we load those bytes back into a PIL image.

    Returns:
    - A new PIL image with transparent background where possible.
    """
    rgba_image = image.convert("RGBA")
    output_bytes = remove(rgba_image)
    output_image = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    return output_image



def load_uploaded_image(uploaded_file) -> Image.Image:
    """
    Load a JPG / JPEG / PNG file from Streamlit into a PIL image.

    This function keeps file reading separate from processing.
    That makes the app easier to debug and extend later.
    """
    return Image.open(uploaded_file)



def render_pdf_to_images(pdf_bytes: bytes, dpi: int = 200) -> List[Image.Image]:
    """
    Convert each page of a PDF into a PIL image.

    Why this is necessary:
    - Background removal libraries like rembg work on images, not PDF pages.
    - So for PDFs, we render every page as an image first.

    Parameters:
    - pdf_bytes: The raw uploaded PDF data.
    - dpi: Rendering quality. Higher DPI gives better detail but uses more memory.

    Returns:
    - A list of PIL images, one per PDF page.
    """
    pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []

    # PyMuPDF uses a transformation matrix to control render scale.
    # 72 DPI is the PDF default. So scale = dpi / 72.
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_index in range(len(pdf_document)):
        page = pdf_document.load_page(page_index)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)

        # Convert the PyMuPDF pixmap into a PIL image.
        page_image = Image.frombytes(
            "RGB",
            [pixmap.width, pixmap.height],
            pixmap.samples,
        )
        images.append(page_image)

    pdf_document.close()
    return images



def build_zip_from_images(images: List[Tuple[str, Image.Image]]) -> bytes:
    """
    Package multiple processed images into a ZIP file.

    This is especially useful for PDFs because each page becomes its own PNG.

    Parameters:
    - images: A list of tuples in the form (filename, PIL_image)

    Returns:
    - ZIP archive as bytes.
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for filename, image in images:
            image_bytes = pil_image_to_bytes(image, output_format="PNG")
            zip_file.writestr(filename, image_bytes)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


# ============================================================
# Cached processing functions
# ============================================================
# Streamlit reruns the script often. Caching helps avoid repeating
# expensive work if the same file is processed again.


@st.cache_data(show_spinner=False)
def process_single_image_file(file_bytes: bytes) -> bytes:
    """
    Cached processor for a single image file.

    Why bytes in / bytes out?
    - Bytes are hashable-friendly for Streamlit caching.
    - It avoids issues with passing complex objects into cache.
    """
    input_image = Image.open(io.BytesIO(file_bytes))
    output_image = remove_background_from_pil(input_image)
    return pil_image_to_bytes(output_image, output_format="PNG")


@st.cache_data(show_spinner=False)
def process_pdf_file(file_bytes: bytes, dpi: int) -> bytes:
    """
    Cached processor for a PDF file.

    Workflow:
    1. Render each PDF page into an image.
    2. Remove the background from each page image.
    3. Save processed pages as PNG files inside a ZIP archive.

    Returns:
    - ZIP bytes ready for download.
    """
    page_images = render_pdf_to_images(file_bytes=file_bytes, dpi=dpi)
    processed_pages = []

    for page_number, page_image in enumerate(page_images, start=1):
        cleaned_page = remove_background_from_pil(page_image)
        filename = f"page_{page_number}.png"
        processed_pages.append((filename, cleaned_page))

    return build_zip_from_images(processed_pages)


# ============================================================
# User interface
# ============================================================
# The UI is intentionally simple:
# - A title and short explanation
# - A file uploader
# - Small settings section for PDFs
# - Preview + download area

st.title("Background Remover")
st.write(
    "Upload a **JPG**, **JPEG**, **PNG**, or **PDF** file. "
    "Images are processed directly. PDFs are processed page by page and returned as a ZIP of transparent PNGs."
)


with st.sidebar:
    st.header("Settings")

    # PDF render quality setting.
    # Higher DPI gives better detail but is slower and uses more RAM.
    pdf_dpi = st.slider(
        "PDF render DPI",
        min_value=100,
        max_value=300,
        value=200,
        step=50,
        help="Used only for PDFs. Higher DPI improves quality but increases processing time.",
    )

    st.markdown("---")
    st.caption(
        "Notes:\n"
        "- JPG/JPEG/PNG output is downloaded as PNG so transparency can be preserved.\n"
        "- PDF output is returned as a ZIP of PNG pages."
    )


uploaded_file = st.file_uploader(
    "Choose a file",
    type=["jpg", "jpeg", "png", "pdf"],
)


if uploaded_file is None:
    st.info("Upload a file to begin.")
    st.stop()


# Read the uploaded file once.
# This is important because some file-like objects may not behave well if read multiple times.
file_name = uploaded_file.name
file_bytes = uploaded_file.getvalue()
extension = file_name.lower().split(".")[-1]


# ============================================================
# Processing branch: image files
# ============================================================
if extension in {"jpg", "jpeg", "png"}:
    st.subheader("Image Preview")

    # Display the original image in one column and the processed image in another.
    original_col, processed_col = st.columns(2)

    with original_col:
        st.markdown("**Original**")
        original_image = Image.open(io.BytesIO(file_bytes))
        st.image(original_image, use_container_width=True)

    with st.spinner("Removing background..."):
        processed_image_bytes = process_single_image_file(file_bytes)
        processed_image = Image.open(io.BytesIO(processed_image_bytes))

    with processed_col:
        st.markdown("**Processed**")
        st.image(processed_image, use_container_width=True)

    # Force PNG output because PNG supports transparency.
    output_name = f"{file_name.rsplit('.', 1)[0]}_no_bg.png"

    st.download_button(
        label="Download processed image",
        data=processed_image_bytes,
        file_name=output_name,
        mime="image/png",
    )


# ============================================================
# Processing branch: PDF files
# ============================================================
elif extension == "pdf":
    st.subheader("PDF Processing")
    st.write(
        "Each PDF page will be converted to an image, processed individually, "
        "and packaged into a ZIP file."
    )

    # Show page count and a small preview of the first page before processing.
    pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
    total_pages = len(pdf_doc)
    st.write(f"Pages detected: **{total_pages}**")

    if total_pages > 0:
        preview_page = pdf_doc.load_page(0)
        preview_pixmap = preview_page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        preview_image = Image.frombytes(
            "RGB",
            [preview_pixmap.width, preview_pixmap.height],
            preview_pixmap.samples,
        )
        st.markdown("**First page preview**")
        st.image(preview_image, use_container_width=True)

    pdf_doc.close()

    with st.spinner("Processing PDF pages..."):
        zip_bytes = process_pdf_file(file_bytes=file_bytes, dpi=pdf_dpi)

    output_zip_name = f"{file_name.rsplit('.', 1)[0]}_no_bg_pages.zip"

    st.success("PDF processed successfully.")
    st.download_button(
        label="Download processed pages as ZIP",
        data=zip_bytes,
        file_name=output_zip_name,
        mime="application/zip",
    )


# ============================================================
# Fallback branch
# ============================================================
# This should normally never happen because the uploader already filters types,
# but keeping a fallback makes the app more robust and explicit.
else:
    st.error("Unsupported file type. Please upload JPG, JPEG, PNG, or PDF.")


# ============================================================
# Footer notes
# ============================================================
st.markdown("---")
st.caption(
    "Implementation notes: rembg is used for image background removal, "
    "Pillow handles image operations, and PyMuPDF renders PDF pages into images."
)
