"""Shared fixtures: build small synthetic EPUB files on the fly."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:language>pl</dc:language>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cover-img" href="images/cover.jpg" media-type="image/jpeg"/>
    <item id="coverpage" href="text/cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="title" href="text/title%20page.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="coverpage"/>
    <itemref idref="title"/>
    <itemref idref="ch2"/>
    <itemref idref="ch1"/>
  </spine>
</package>"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol>
  <li><a href="text/title%20page.xhtml">Title Page</a></li>
  <li><a href="text/ch2.xhtml#start">Prologue</a></li>
</ol></nav></body></html>"""

NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>
  <navPoint id="p1"><navLabel><text>From NCX</text></navLabel>
    <content src="text/title%20page.xhtml"/></navPoint>
</navMap></ncx>"""


def xhtml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ignored</title>'
        "<style>p { color: red; }</style></head>"
        f"<body>{body}</body></html>"
    )


DOCUMENTS = {
    "OEBPS/text/cover.xhtml": xhtml('<div><img src="../images/cover.jpg" alt="Cover"/></div>'),
    "OEBPS/text/title page.xhtml": xhtml("<p>Jane Doe</p><p>TEST&#160;BOOK</p>"),
    "OEBPS/text/ch2.xhtml": xhtml(
        '<h1 id="x"><a>Prologue  The Storm</a> </h1>'
        "<p>It was a dark and <i>stormy</i> night.</p>"
        "<script>alert('no')</script>"
        "<p>&#8222;Quotes&#8221; &amp; entities.</p>"
        "<p>   </p>"
    ),
    "OEBPS/text/ch1.xhtml": xhtml(
        "<h2>Chapter 1<br/>The Orphan</h2>"
        "<p>First line<br/>second line.</p>"
        "<h3>A sub-heading</h3>"
        "<div><p>Nested paragraph.</p></div>"
    ),
}

COVER_BYTES = b"\xff\xd8\xff\xe0fake-jpeg"


def write_epub(path: Path, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def epub_files() -> dict[str, str | bytes]:
    return {
        "META-INF/container.xml": CONTAINER,
        "OEBPS/content.opf": OPF,
        "OEBPS/nav.xhtml": NAV,
        "OEBPS/toc.ncx": NCX,
        "OEBPS/images/cover.jpg": COVER_BYTES,
        "OEBPS/style.css": "p {}",
        **DOCUMENTS,
    }


@pytest.fixture
def sample_epub(tmp_path: Path, epub_files: dict[str, str | bytes]) -> Path:
    return write_epub(tmp_path / "book.epub", epub_files)
