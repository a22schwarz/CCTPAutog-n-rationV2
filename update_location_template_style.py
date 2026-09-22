from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import os
import re
import shutil
import tempfile


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE = BASE_DIR / "TemplateCCTP.updated2.docx"
BACKUP = BASE_DIR / "TemplateCCTP.updated2.before_location_style.docx"
MARKERS = (
    "INVERTER_LOCATION_TEXT",
    "INVERTER_LOCATION_REQUIREMENTS",
    "DC_BOX_LOCATION_TEXT",
)

RUN_PROPERTIES = (
    '<w:rPr>'
    '<w:rFonts w:ascii="Source Sans Pro" w:hAnsi="Source Sans Pro" '
    'w:eastAsia="Source Sans Pro" w:cs="Source Sans Pro"/>'
    '<w:b w:val="0"/><w:bCs w:val="0"/>'
    '<w:i w:val="0"/><w:iCs w:val="0"/>'
    '<w:sz w:val="18"/><w:szCs w:val="18"/>'
    '<w:lang w:val="fr-FR"/>'
    '</w:rPr>'
)


def update_document_xml(xml: str) -> str:
    for marker in MARKERS:
        token = '{{r ' + marker + ' }}'
        token_position = xml.find(token)
        if token_position < 0:
            raise RuntimeError(f"Balise introuvable : {marker}")
        run_matches = list(re.finditer(r'<w:r(?=\s|>)', xml[:token_position]))
        run_start = run_matches[-1].start() if run_matches else -1
        run_end = xml.find('</w:r>', token_position)
        if run_start < 0 or run_end < 0:
            raise RuntimeError(f"Run Word introuvable pour : {marker}")
        run_end += len('</w:r>')
        replacement = f'<w:r>{RUN_PROPERTIES}<w:t>{{{{ {marker} }}}}</w:t></w:r>'
        xml = xml[:run_start] + replacement + xml[run_end:]
    return xml


def main() -> None:
    if not BACKUP.exists():
        shutil.copy2(TEMPLATE, BACKUP)

    handle, temporary_name = tempfile.mkstemp(suffix=".docx", dir=BASE_DIR)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with ZipFile(TEMPLATE, "r") as source, ZipFile(temporary, "w", ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    data = update_document_xml(data.decode("utf-8")).encode("utf-8")
                target.writestr(item, data)
        os.replace(temporary, TEMPLATE)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
