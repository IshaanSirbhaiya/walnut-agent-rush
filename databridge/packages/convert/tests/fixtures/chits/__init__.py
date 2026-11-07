"""Chit fixtures rendered to PDF / page raster for the T-36 docling extraction tests.

Deterministic, hermetic — no checked-in binaries. The source text is the synthetic clinic chit
corpus in ``databridge/fixtures/clinic/chits``; this package only changes its container.
"""
from __future__ import annotations

from .build import (
    BALLOT_TICKED,
    BALLOT_UNTICKED,
    ballot_font_path,
    pdf_page_to_png,
    text_to_pdf,
)

__all__ = ["BALLOT_TICKED", "BALLOT_UNTICKED", "ballot_font_path", "pdf_page_to_png",
           "text_to_pdf"]
