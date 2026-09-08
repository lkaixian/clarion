"""
Document AI layer: turns a scanned/photographed clinical document into raw
text, ready for structuring into FHIR-lite resources.

Uses Tesseract via pytesseract if available. Falls back to a clear error
message so the rest of the pipeline can still be demoed with typed text
if Tesseract isn't installed in a given environment (e.g. during early dev
on a laptop without the binary yet).

INSTALL NOTE (Week 2 task): `sudo apt-get install tesseract-ocr` then
`pip install pytesseract pillow`.
"""


def extract_text_from_image(image_path: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return (
            "[OCR unavailable in this environment — install pytesseract, "
            "pillow, and the tesseract-ocr binary. See ai/ocr.py docstring.]"
        )

    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        return f"[OCR failed: {e}]"


def extract_structured_fields(raw_text: str) -> dict:
    """
    Very lightweight rule-based extraction as a Week-2 placeholder for a
    proper NLP/LLM extraction pass. Looks for common prescription/report
    patterns. Replace with an LLM-based extractor (see summarize.py for the
    pattern to follow) once OCR text quality is validated on real samples.
    """
    import re

    fields = {"possible_drug_names": [], "possible_dosages": [], "raw_text": raw_text}

    # crude heuristic: "<Word> <number>mg" patterns
    dosage_pattern = re.compile(r"([A-Za-z]+)\s+(\d+\s?mg)", re.IGNORECASE)
    for match in dosage_pattern.finditer(raw_text):
        fields["possible_drug_names"].append(match.group(1))
        fields["possible_dosages"].append(match.group(2))

    return fields
