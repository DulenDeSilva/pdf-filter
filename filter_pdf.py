import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Optional, TypedDict

import fitz


class PageRange(TypedDict):
    start: int
    end: int
    reason: str


class FilterResult(TypedDict):
    inputPdfPath: str
    pdfName: str
    documentType: str
    filterProfile: str
    selectedPages: list[int]
    wantedPages: list[int]
    removedPages: list[int]
    foundSections: dict[str, list[int]]
    missingSections: list[str]
    missingRequiredSections: list[str]
    missingOptionalSections: list[str]
    sectionConfidence: dict[str, float]
    pageRanges: list[PageRange]
    filteredPdfPath: Optional[str]
    selectedPagesJsonPath: Optional[str]
    filteredPageMap: dict[str, int]
    confidence: float
    totalPages: int
    logPath: Optional[str]
    detectionMethod: str
    detectedTocPrintedPages: dict[str, int]
    detectedTocPdfPages: dict[str, int]
    detectedTocPrintedPageLists: dict[str, list[int]]
    detectedTocPdfPageLists: dict[str, list[int]]
    pageOffset: Optional[int]


TARGET_SECTION_ORDER = [
    "main_table_of_contents",
    "financial_highlights",
    "independent_auditors_report",
    "financial_statements_table_of_contents",
    "profit_or_loss",
    "comprehensive_income",
    "financial_position",
    "changes_in_equity",
    "cash_flows",
    "notes_to_financial_statements",
    "notes_table_of_contents",
    "shareholder_or_investor_information",
    "ten_year_summary",
    "five_year_summary",
]


REQUIRED_SECTIONS = [
    "main_table_of_contents",
    "independent_auditors_report",
    "profit_or_loss",
    "comprehensive_income",
    "financial_position",
    "changes_in_equity",
    "cash_flows",
    "notes_to_financial_statements",
]


OPTIONAL_SECTIONS = [
    "financial_highlights",
    "financial_statements_table_of_contents",
    "notes_table_of_contents",
    "shareholder_or_investor_information",
    "ten_year_summary",
    "five_year_summary",
]


CORE_STATEMENT_KEYS = [
    "profit_or_loss",
    "comprehensive_income",
    "financial_position",
    "changes_in_equity",
    "cash_flows",
]


FINANCIAL_TOC_ALLOWED_SECTIONS = [
    "independent_auditors_report",
    "financial_statements_table_of_contents",
    "profit_or_loss",
    "comprehensive_income",
    "financial_position",
    "changes_in_equity",
    "cash_flows",
    "notes_to_financial_statements",
]


GENERAL_TOC_ALLOWED_SECTIONS = [
    "financial_highlights",
    "shareholder_or_investor_information",
    "ten_year_summary",
    "five_year_summary",
]


FINANCIAL_TOC_BLOCK_START_PATTERNS = [
    r"\bfinancial statements\b",
]


FINANCIAL_TOC_BLOCK_END_PATTERNS = [
    r"\bsupplementary information\b",
    r"\bmarket discipline\b",
    r"\bglossary\b",
    r"\bnotice of meeting\b",
    r"\bform of proxy\b",
    r"\binvestor feedback form\b",
    r"\bcorporate information\b",
]


TARGET_SECTION_PATTERNS = {
    "main_table_of_contents": [
        r"\bcontents\b",
        r"\bcontent\b",
        r"\btable of contents\b",
    ],
    "financial_highlights": [
        r"\bfinancial highlights\b",
        r"\bperformance highlights\b",
        r"\bkey financial highlights\b",
    ],
    "independent_auditors_report": [
        r"\bindependent auditor'?s report\b",
        r"\bindependent auditors'? report\b",
        r"\bindependent auditor report\b",
        r"\bindependent auditors report\b",
    ],
    "financial_statements_table_of_contents": [
        r"\bfinancial statements\s*[-–]\s*table of contents\b",
        r"\bfinancial statements table of contents\b",
        r"\bfinancial statements contents\b",
    ],
    "profit_or_loss": [
        r"\bincome statement\b",
        r"\bstatement of income\b",
        r"\bstatement of profit or loss and other comprehensive income\b",
        r"\bstatement of profit or loss\b",
        r"\bconsolidated statement of profit or loss and other comprehensive income\b",
        r"\bconsolidated statement of profit or loss\b",
    ],
    "comprehensive_income": [
        r"\bstatement of profit or loss and other comprehensive income\b",
        r"\bstatement of comprehensive income\b",
        r"\bstatement of other comprehensive income\b",
        r"\bconsolidated statement of profit or loss and other comprehensive income\b",
        r"\bconsolidated statement of comprehensive income\b",
    ],
    "financial_position": [
        r"\bstatement of financial position\b",
        r"\bconsolidated statement of financial position\b",
        r"\bbalance sheet\b",
    ],
    "changes_in_equity": [
        r"\bstatement of changes in equity\b",
        r"\bstatements of changes in equity\b",
        r"\bconsolidated statement of changes in equity\b",
        r"\bconsolidated statements of changes in equity\b",
    ],
    "cash_flows": [
        r"\bstatement of cash flows\b",
        r"\bstatements of cash flows\b",
        r"\bconsolidated statement of cash flows\b",
        r"\bconsolidated statements of cash flows\b",
    ],
    "notes_to_financial_statements": [
        r"\bnotes to the financial statements\b",
        r"\bnotes to financial statements\b",
        r"\bnotes to the consolidated financial statements\b",
    ],
    "shareholder_or_investor_information": [
        r"\bshareholder information\b",
        r"\bshareholders information\b",
        r"\bshareholders' information\b",
        r"\bshareholder'?s information\b",
        r"\bshareholder and investor information\b",
        r"\bshareholder\s*&\s*investor information\b",
        r"\bshare information\b",
        r"\binvestor information\b",
        r"\binvestor relations\b",
        r"\binformation to shareholders\b",
    ],
    "ten_year_summary": [
        r"\bten year summary\b",
        r"\bten-year summary\b",
        r"\bten years summary\b",
        r"\bten year statistical summary\b",
        r"\bten-year statistical summary\b",
        r"\bten years statistical summary\b",
        r"\bdecade at a glance\b",
        r"\bfinancial information for last ten years\b",
    ],
    "five_year_summary": [
        r"\bfive year summary\b",
        r"\bfive-year summary\b",
        r"\bfive years summary\b",
        r"\bfive years financial summary\b",
        r"\bfive year financial summary\b",
        r"\bfive year summary of financial position\b",
        r"\bfive year summary of income statement\b",
        r"\bfive-year achievements\b",
        r"\bfive year achievements\b",
        r"\b5 year summary\b",
        r"\b5-year summary\b",
        r"\b5 years summary\b",
        r"\b5 year financial summary\b",
    ],
}


TOC_PATTERNS = [
    r"\bcontents\b",
    r"\btable of contents\b",
    r"\bcontent\b",
]


NOTES_TOC_PATTERNS = [
    r"\bindex to the financial statements\b",
    r"\bnotes index\b",
    r"\bnotes to the financial statements\b.{0,80}\bpage\b",
    r"\bnotes\b.{0,40}\bpage\b",
]


ANNUAL_REPORT_PATTERNS = [
    r"\bannual report\b",
    r"\bindependent auditor",
    r"\bindependent auditors",
    r"\bnotes to the financial statements\b",
    r"\bstatement of financial position\b",
    r"\bstatement of cash flows\b",
    r"\bstatements of cash flows\b",
]


QUARTERLY_REPORT_PATTERNS = [
    r"\binterim financial statements\b",
    r"\bquarter ended\b",
    r"\bthree months ended\b",
    r"\bsix months ended\b",
    r"\bnine months ended\b",
    r"\bunaudited\b",
]


FINANCIAL_ROW_LABEL_PATTERNS = [
    r"\brevenue\b",
    r"\bturnover\b",
    r"\bgross profit\b",
    r"\bprofit before tax\b",
    r"\bincome tax\b",
    r"\bprofit for the year\b",
    r"\bprofit for the period\b",
    r"\bearnings per share\b",
    r"\bassets\b",
    r"\btotal assets\b",
    r"\bliabilities\b",
    r"\btotal liabilities\b",
    r"\bequity\b",
    r"\bstated capital\b",
    r"\bretained earnings\b",
    r"\bcash and cash equivalents\b",
    r"\bcash flows from operating activities\b",
    r"\bcash flows from investing activities\b",
    r"\bcash flows from financing activities\b",
]


SECTION_VALIDATION_PATTERNS = {
    "independent_auditors_report": [
        r"\bindependent auditor'?s report\b",
        r"\bindependent auditors'? report\b",
        r"\breport on the audit of the financial statements\b",
        r"\bbasis for opinion\b",
        r"\bkey audit matter\b",
    ],
    "financial_statements_table_of_contents": [
        r"\bfinancial statements\s*[-–]\s*table of contents\b",
        r"\bfinancial statements table of contents\b",
        r"\bfinancial statements contents\b",
    ],
    "profit_or_loss": [
        r"\bincome statement\b",
        r"\bstatement of income\b",
        r"\bstatement of profit or loss\b",
        r"\bprofit or loss and other comprehensive income\b",
        r"\brevenue\b",
        r"\bprofit for the year\b",
    ],
    "comprehensive_income": [
        r"\bstatement of comprehensive income\b",
        r"\bother comprehensive income\b",
        r"\bprofit or loss and other comprehensive income\b",
    ],
    "financial_position": [
        r"\bstatement of financial position\b",
        r"\bbalance sheet\b",
        r"\bassets\b",
        r"\bliabilities\b",
        r"\bequity\b",
    ],
    "changes_in_equity": [
        r"\bstatement of changes in equity\b",
        r"\bchanges in equity\b",
        r"\bstated capital\b",
        r"\bretained earnings\b",
    ],
    "cash_flows": [
        r"\bstatement of cash flows\b",
        r"\bstatements of cash flows\b",
        r"\bcash flows from operating activities\b",
        r"\bcash flows from investing activities\b",
        r"\bcash flows from financing activities\b",
    ],
    "notes_to_financial_statements": [
        r"\bnotes to the financial statements\b",
        r"\bnotes to financial statements\b",
        r"\bnotes to the consolidated financial statements\b",
    ],
    "shareholder_or_investor_information": [
        r"\bshareholders'? information\b",
        r"\bshareholder information\b",
        r"\binvestor information\b",
        r"\binvestor relations\b",
        r"\btwenty largest shareholders\b",
        r"\bpublic holding\b",
    ],
    "ten_year_summary": [
        r"\bten year summary\b",
        r"\bten-year summary\b",
        r"\bten years summary\b",
        r"\bten year statistical summary\b",
        r"\bdecade at a glance\b",
    ],
    "five_year_summary": [
        r"\bfive year summary\b",
        r"\bfive-year summary\b",
        r"\b5 year summary\b",
        r"\b5-year summary\b",
    ],
    "financial_highlights": [
        r"\bfinancial highlights\b",
        r"\bperformance highlights\b",
        r"\bkey financial highlights\b",
    ],
}


SECTION_MAX_PAGES = {
    "financial_highlights": 2,
    "independent_auditors_report": 5,
    "financial_statements_table_of_contents": 1,
    "profit_or_loss": 1,
    "comprehensive_income": 1,
    "financial_position": 1,
    "changes_in_equity": 12,
    "cash_flows": 2,
    "notes_to_financial_statements": 1,
    "notes_table_of_contents": 3,
    "shareholder_or_investor_information": 3,
    "ten_year_summary": 3,
    "five_year_summary": 3,
}


def normalize_text(text: str) -> str:
    text = text.replace("’", "'")
    text = text.replace("‘", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    text = text.replace("￾", "")
    return re.sub(r"\s+", " ", text.lower()).strip()


def normalize_line(text: str) -> str:
    return normalize_text(text)


def has_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def count_numbers(text: str) -> int:
    return len(re.findall(r"\(?\d[\d,\.]*\)?", text))


def count_matches(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text))


def get_top_text(text: str, max_lines: int = 16) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return normalize_text(" ".join(lines[:max_lines]))


def get_bottom_text(text: str, max_lines: int = 12) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return normalize_text(" ".join(lines[-max_lines:]))


def clamp_page(page_number: int, total_pages: int) -> int:
    return max(1, min(total_pages, page_number))


def add_pages(
    found_sections: dict[str, list[int]],
    page_ranges: list[PageRange],
    section_key: str,
    pages_to_add: list[int],
    total_pages: int,
    reason: str,
) -> None:
    cleaned_pages = sorted(
        {
            clamp_page(page_number, total_pages)
            for page_number in pages_to_add
            if 1 <= page_number <= total_pages
        }
    )

    if not cleaned_pages:
        return

    existing = set(found_sections.get(section_key, []))
    existing.update(cleaned_pages)
    found_sections[section_key] = sorted(existing)

    page_ranges.append(
        {
            "start": min(cleaned_pages),
            "end": max(cleaned_pages),
            "reason": reason,
        }
    )


def extract_printed_page_number(raw_text: str) -> Optional[int]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    candidates = lines[:10] + lines[-10:]

    for line in candidates:
        clean = normalize_line(line)

        if re.fullmatch(r"\d{1,3}", clean):
            value = int(clean)
            if 1 <= value <= 800:
                return value

        match = re.search(r"\bannual report.*?\b(\d{1,3})\s*$", clean)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 800:
                return value

    return None


def count_toc_style_lines(text: str) -> int:
    count = 0

    for line in text.splitlines():
        normalized = normalize_line(line)

        if re.search(r"^\s*\d{1,3}\s+[a-z].{2,120}$", normalized):
            count += 1
        elif re.search(r"^[a-z].{3,120}\s+\d{1,3}\s*$", normalized):
            count += 1
        elif re.search(r"[a-z].{3,80}\s+\d{1,3}\s*[-–]\s*\d{1,3}\s*$", normalized):
            count += 1

    return count


def looks_like_main_toc_page(text: str) -> bool:
    normalized = normalize_text(text)

    has_financial_statement_items = (
        "financial statements" in normalized
        and (
            "income statement" in normalized
            or "statement of profit or loss" in normalized
        )
        and "statement of financial position" in normalized
        and (
            "statement of cash flows" in normalized
            or "statements of cash flows" in normalized
        )
        and "notes to the financial statements" in normalized
    )

    toc_line_count = count_toc_style_lines(text)

    if has_financial_statement_items:
        return True

    if has_pattern(normalized[:1200], TOC_PATTERNS) and toc_line_count >= 8:
        return True

    return False


def count_note_index_lines(text: str) -> int:
    count = 0

    for line in text.splitlines():
        normalized = normalize_line(line)

        if re.search(
            r"^\s*\d{1,2}(\.\d{1,2})?\s+[a-z][a-z0-9,&()/\-\s]{3,100}\s+\d{1,3}\s*$",
            normalized,
        ):
            count += 1

    return count


def looks_like_notes_toc_page(text: str) -> bool:
    normalized = normalize_text(text)
    top_text = get_top_text(text, max_lines=20)

    if has_pattern(top_text, NOTES_TOC_PATTERNS):
        return True

    note_index_count = count_note_index_lines(text)

    has_note_index_keywords = (
        "notes to the financial statements" in normalized
        and (
            "corporate information" in normalized
            or "basis of preparation" in normalized
            or "accounting policies" in normalized
            or "revenue" in normalized
        )
        and note_index_count >= 3
    )

    return note_index_count >= 6 or has_note_index_keywords


def read_pdf_pages(input_pdf_path: str) -> list[dict]:
    doc = fitz.open(input_pdf_path)
    pages: list[dict] = []

    for index, page in enumerate(doc):
        page_number = index + 1
        text = page.get_text("text") or ""
        normalized = normalize_text(text)
        top_text = get_top_text(text)
        bottom_text = get_bottom_text(text)

        pages.append(
            {
                "pageNumber": page_number,
                "text": text,
                "normalizedText": normalized,
                "topText": top_text,
                "bottomText": bottom_text,
                "printedPageNumber": extract_printed_page_number(text),
                "isMainToc": looks_like_main_toc_page(text),
                "isNotesToc": looks_like_notes_toc_page(text),
                "numberCount": count_numbers(normalized),
                "financialLabelCount": count_matches(
                    normalized,
                    FINANCIAL_ROW_LABEL_PATTERNS,
                ),
                "textLength": len(normalized),
            }
        )

    doc.close()
    return pages


def detect_document_type(pages: list[dict]) -> tuple[str, float]:
    sample_text = " ".join(
        page["normalizedText"] for page in pages[: min(30, len(pages))]
    )

    annual_score = count_matches(sample_text, ANNUAL_REPORT_PATTERNS)
    quarterly_score = count_matches(sample_text, QUARTERLY_REPORT_PATTERNS)

    average_text_length = (
        sum(page["textLength"] for page in pages) / max(len(pages), 1)
    )

    if average_text_length < 60:
        return "scanned_or_low_text_pdf", 0.45

    if quarterly_score >= 2 and len(pages) <= 100:
        return "quarterly_report", 0.85

    if annual_score >= 2 or len(pages) > 80:
        return "annual_report", 0.9

    return "other_report", 0.65


def get_report_page_offset(pages: list[dict]) -> Optional[int]:
    offsets: list[int] = []

    for page in pages:
        printed_page = page.get("printedPageNumber")

        if not printed_page:
            continue

        pdf_page = page["pageNumber"]
        offset = pdf_page - printed_page

        if -20 <= offset <= 40:
            offsets.append(offset)

    if not offsets:
        return None

    offset_counter = Counter(offsets)
    most_common_offset, _ = offset_counter.most_common(1)[0]

    return most_common_offset


def append_detected_page(
    detected: dict[str, list[int]],
    section_key: str,
    value: int,
) -> None:
    if not (1 <= value <= 800):
        return

    detected.setdefault(section_key, [])

    if value not in detected[section_key]:
        detected[section_key].append(value)
        detected[section_key].sort()


def extract_text_block_between_patterns(
    text: str,
    start_patterns: list[str],
    end_patterns: list[str],
) -> str:
    normalized = normalize_text(text)

    start_positions = []

    for pattern in start_patterns:
        match = re.search(pattern, normalized)

        if match:
            start_positions.append(match.start())

    if not start_positions:
        return ""

    start = min(start_positions)

    end_candidates = []

    for pattern in end_patterns:
        match = re.search(pattern, normalized[start + 1:])

        if match:
            end_candidates.append(start + 1 + match.start())

    end = min(end_candidates) if end_candidates else len(normalized)

    return normalized[start:end]


def extract_page_number_after_match(text: str, match_end: int) -> Optional[int]:
    after_text = text[match_end: match_end + 140]
    after_number = re.search(r"\b(\d{1,3})\b", after_text)

    if after_number:
        value = int(after_number.group(1))

        if 1 <= value <= 800:
            return value

    return None


def extract_page_number_near_section(line: str, pattern: str) -> Optional[int]:
    match = re.search(pattern, line)

    if not match:
        return None

    before_text = line[: match.start()]
    after_text = line[match.end() :]

    before_numbers = re.findall(r"\b(\d{1,3})\b", before_text)

    if before_numbers:
        value = int(before_numbers[-1])

        if 1 <= value <= 800:
            return value

    after_match = re.search(r"\b(\d{1,3})\b", after_text)

    if after_match:
        value = int(after_match.group(1))

        if 1 <= value <= 800:
            return value

    return None


def extract_toc_printed_page_lists(pages: list[dict]) -> dict[str, list[int]]:
    detected: dict[str, list[int]] = {}

    toc_pages = [
        page
        for page in pages
        if page["pageNumber"] <= 12 and page["isMainToc"]
    ]

    if not toc_pages:
        toc_pages = [
            page
            for page in pages
            if page["pageNumber"] <= 12
        ]

    for page in toc_pages:
        full_text = normalize_text(page["text"])

        financial_block = extract_text_block_between_patterns(
            page["text"],
            FINANCIAL_TOC_BLOCK_START_PATTERNS,
            FINANCIAL_TOC_BLOCK_END_PATTERNS,
        )

        # Financial statement related sections must be extracted only from
        # the Financial Statements block. This avoids false hits from
        # governance, risk, and supplementary sections.
        if financial_block:
            for section_key in FINANCIAL_TOC_ALLOWED_SECTIONS:
                patterns = TARGET_SECTION_PATTERNS.get(section_key, [])

                for pattern in patterns:
                    for match in re.finditer(pattern, financial_block):
                        value = extract_page_number_after_match(
                            financial_block,
                            match.end(),
                        )

                        if value:
                            append_detected_page(detected, section_key, value)

        # General sections can be extracted from the whole contents page.
        for section_key in GENERAL_TOC_ALLOWED_SECTIONS:
            patterns = TARGET_SECTION_PATTERNS.get(section_key, [])

            for pattern in patterns:
                for match in re.finditer(pattern, full_text):
                    value = extract_page_number_after_match(
                        full_text,
                        match.end(),
                    )

                    if not value:
                        continue

                    # Avoid selecting "Financial Highlights - Bank" inside
                    # financial statements as the overview financial highlights.
                    if section_key == "financial_highlights" and value > 80:
                        continue

                    append_detected_page(detected, section_key, value)

    # If combined P&L + OCI exists and comprehensive income was not separately found.
    if "profit_or_loss" in detected and "comprehensive_income" not in detected:
        detected["comprehensive_income"] = detected["profit_or_loss"][:]

    return detected


def section_page_score(page: dict, section_key: str) -> int:
    text = page["normalizedText"]
    top_text = page["topText"]
    score = 0

    patterns = SECTION_VALIDATION_PATTERNS.get(
        section_key,
        TARGET_SECTION_PATTERNS.get(section_key, []),
    )

    if has_pattern(top_text, patterns):
        score += 5

    if has_pattern(text[:2500], patterns):
        score += 2

    if section_key in CORE_STATEMENT_KEYS:
        if page["numberCount"] >= 8:
            score += 1
        if page["financialLabelCount"] >= 2:
            score += 1

    if section_key == "independent_auditors_report":
        if "opinion" in text[:2500]:
            score += 1
        if "basis for opinion" in text[:2500]:
            score += 1

    if section_key == "shareholder_or_investor_information":
        if "twenty largest shareholders" in text:
            score += 2
        if "public holding" in text:
            score += 1

    return score


def validate_and_correct_pdf_page(
    section_key: str,
    candidate_page: int,
    pages: list[dict],
    search_radius: int = 1,
    trust_candidate: bool = True,
) -> int:
    total_pages = len(pages)
    candidate_page = clamp_page(candidate_page, total_pages)

    candidate_score = section_page_score(pages[candidate_page - 1], section_key)

    # If TOC + offset gives a reasonable page, trust it.
    if trust_candidate and candidate_score >= 1:
        return candidate_page

    best_page = candidate_page
    best_score = candidate_score

    for page_number in range(
        max(1, candidate_page - search_radius),
        min(total_pages, candidate_page + search_radius) + 1,
    ):
        score = section_page_score(pages[page_number - 1], section_key)

        if score > best_score:
            best_score = score
            best_page = page_number

    # Avoid aggressive shifting when the heading scan is weak.
    if trust_candidate and candidate_score == 0 and best_score < 5:
        return candidate_page

    return best_page


def printed_to_pdf_page(
    printed_page: int,
    pages: list[dict],
    offset: Optional[int],
    section_key: str,
) -> Optional[int]:
    total_pages = len(pages)

    if offset is not None:
        candidate = printed_page + offset

        if 1 <= candidate <= total_pages:
            return validate_and_correct_pdf_page(
                section_key=section_key,
                candidate_page=candidate,
                pages=pages,
                search_radius=1,
                trust_candidate=True,
            )

    for page in pages:
        if page.get("printedPageNumber") == printed_page:
            return validate_and_correct_pdf_page(
                section_key=section_key,
                candidate_page=page["pageNumber"],
                pages=pages,
                search_radius=1,
                trust_candidate=True,
            )

    if 1 <= printed_page <= total_pages:
        return validate_and_correct_pdf_page(
            section_key=section_key,
            candidate_page=printed_page,
            pages=pages,
            search_radius=1,
            trust_candidate=True,
        )

    return None


def convert_toc_printed_to_pdf_page_lists(
    detected_printed_page_lists: dict[str, list[int]],
    pages: list[dict],
    offset: Optional[int],
) -> dict[str, list[int]]:
    detected_pdf_page_lists: dict[str, list[int]] = {}

    for section_key, printed_pages in detected_printed_page_lists.items():
        for printed_page in printed_pages:
            pdf_page = printed_to_pdf_page(
                printed_page=printed_page,
                pages=pages,
                offset=offset,
                section_key=section_key,
            )

            if pdf_page:
                detected_pdf_page_lists.setdefault(section_key, [])

                if pdf_page not in detected_pdf_page_lists[section_key]:
                    detected_pdf_page_lists[section_key].append(pdf_page)
                    detected_pdf_page_lists[section_key].sort()

    return detected_pdf_page_lists


def first_page_dict(page_lists: dict[str, list[int]]) -> dict[str, int]:
    return {
        section_key: pages[0]
        for section_key, pages in page_lists.items()
        if pages
    }


def page_matches_section(page: dict, section_key: str) -> bool:
    patterns = TARGET_SECTION_PATTERNS[section_key]
    return has_pattern(page["topText"], patterns)


def is_probably_real_statement_page(page: dict, section_key: str) -> bool:
    if page["isMainToc"]:
        return False

    if section_key in ["main_table_of_contents", "notes_table_of_contents"]:
        return False

    if section_key in CORE_STATEMENT_KEYS and page["pageNumber"] < 50:
        return False

    if section_key in CORE_STATEMENT_KEYS and page["pageNumber"] > 0.85 * page.get("totalPages", 999999):
        return False

    if section_key == "financial_highlights":
        return (
            "financial highlights" in page["topText"]
            or "performance highlights" in page["topText"]
        )

    if section_key == "independent_auditors_report":
        return section_page_score(page, section_key) >= 5

    if section_key == "financial_statements_table_of_contents":
        return section_page_score(page, section_key) >= 5

    if not page_matches_section(page, section_key):
        return False

    if section_key in CORE_STATEMENT_KEYS:
        return page["numberCount"] >= 8 or page["financialLabelCount"] >= 2

    return True


def heading_scan_pdf_pages(pages: list[dict]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {key: [] for key in TARGET_SECTION_ORDER}
    total_pages = len(pages)

    for page in pages:
        page["totalPages"] = total_pages

        for section_key in TARGET_SECTION_ORDER:
            if section_key in ["main_table_of_contents", "notes_table_of_contents"]:
                continue

            if found[section_key]:
                continue

            if is_probably_real_statement_page(page, section_key):
                found[section_key].append(page["pageNumber"])

    return found


def get_next_boundary_page(
    current_page: int,
    detected_pdf_page_lists: dict[str, list[int]],
) -> Optional[int]:
    boundary_keys = [
        "independent_auditors_report",
        "financial_statements_table_of_contents",
        "profit_or_loss",
        "comprehensive_income",
        "financial_position",
        "changes_in_equity",
        "cash_flows",
        "notes_to_financial_statements",
        "shareholder_or_investor_information",
        "ten_year_summary",
        "five_year_summary",
    ]

    future_pages = []

    for key in boundary_keys:
        for page_number in detected_pdf_page_lists.get(key, []):
            if page_number > current_page:
                future_pages.append(page_number)

    if not future_pages:
        return None

    return min(future_pages)


def build_section_pages_from_toc(
    detected_pdf_page_lists: dict[str, list[int]],
    pages: list[dict],
) -> tuple[dict[str, list[int]], list[PageRange]]:
    total_pages = len(pages)
    found_sections: dict[str, list[int]] = {key: [] for key in TARGET_SECTION_ORDER}
    page_ranges: list[PageRange] = []

    for section_key in TARGET_SECTION_ORDER:
        if section_key in ["main_table_of_contents", "notes_table_of_contents"]:
            continue

        start_pages = detected_pdf_page_lists.get(section_key, [])

        if not start_pages:
            continue

        if section_key == "profit_or_loss":
            start_pages = [min(start_pages)]

        if section_key == "comprehensive_income":
            start_pages = [max(start_pages)]

        for start_page in start_pages:
            max_pages = SECTION_MAX_PAGES.get(section_key, 1)

            if section_key == "notes_to_financial_statements":
                add_pages(
                    found_sections,
                    page_ranges,
                    section_key,
                    [start_page],
                    total_pages,
                    "notes_to_financial_statements_start_from_toc",
                )
                continue

            next_boundary = get_next_boundary_page(
                current_page=start_page,
                detected_pdf_page_lists=detected_pdf_page_lists,
            )

            if next_boundary:
                end_page = min(next_boundary - 1, start_page + max_pages - 1)
            else:
                end_page = min(start_page + max_pages - 1, total_pages)

            add_pages(
                found_sections,
                page_ranges,
                section_key,
                list(range(start_page, end_page + 1)),
                total_pages,
                f"{section_key}_from_toc",
            )

    return found_sections, page_ranges


def detect_main_toc_pages(pages: list[dict]) -> list[int]:
    toc_pages: list[int] = []

    for page in pages:
        page_number = page["pageNumber"]

        if page_number > 12:
            continue

        text = page["normalizedText"]

        has_financial_statement_items = (
            "financial statements" in text
            and (
                "income statement" in text
                or "statement of profit or loss" in text
            )
            and "statement of financial position" in text
            and (
                "statement of cash flows" in text
                or "statements of cash flows" in text
            )
            and "notes to the financial statements" in text
        )

        toc_line_count = count_toc_style_lines(page["text"])

        if has_financial_statement_items or (
            "contents" in text and toc_line_count >= 8
        ):
            toc_pages.append(page_number)

    return sorted(set(toc_pages))


def detect_combined_profit_or_loss_and_oci_page(pages: list[dict]) -> Optional[int]:
    for page in pages:
        if page["isMainToc"]:
            continue

        if page["pageNumber"] < 50:
            continue

        top_text = page["topText"]

        if "profit or loss and other comprehensive income" in top_text:
            return page["pageNumber"]

    return None


def detect_notes_toc_pages(
    pages: list[dict],
    found_sections: dict[str, list[int]],
    detected_pdf_page_lists: dict[str, list[int]],
) -> list[int]:
    total_pages = len(pages)
    candidate_pages: set[int] = set()

    notes_start_pages = found_sections.get("notes_to_financial_statements", [])

    if not notes_start_pages:
        notes_start_pages = detected_pdf_page_lists.get("notes_to_financial_statements", [])

    if not notes_start_pages:
        return []

    notes_start = min(notes_start_pages)

    for page_number in range(
        max(1, notes_start - 3),
        min(total_pages, notes_start + 4) + 1,
    ):
        page = pages[page_number - 1]

        if page["isNotesToc"]:
            candidate_pages.add(page_number)

    previous_page = notes_start - 1

    if previous_page >= 1 and pages[previous_page - 1]["isNotesToc"]:
        candidate_pages.add(previous_page)

    if pages[notes_start - 1]["isNotesToc"]:
        candidate_pages.add(notes_start)

    return sorted(candidate_pages)


def merge_heading_scan_results(
    found_sections: dict[str, list[int]],
    page_ranges: list[PageRange],
    heading_results: dict[str, list[int]],
    total_pages: int,
) -> None:
    for section_key, pages_found in heading_results.items():
        if section_key in ["main_table_of_contents", "notes_table_of_contents"]:
            continue

        if found_sections.get(section_key):
            continue

        if not pages_found:
            continue

        if section_key in CORE_STATEMENT_KEYS:
            candidate = pages_found[0]

            if candidate < 50:
                continue

            if candidate > total_pages * 0.85:
                continue

        add_pages(
            found_sections,
            page_ranges,
            section_key,
            pages_found,
            total_pages,
            f"{section_key}_from_heading_scan",
        )


def remove_invalid_financial_statement_detections(
    found_sections: dict[str, list[int]],
) -> None:
    notes_pages = found_sections.get("notes_to_financial_statements", [])

    if not notes_pages:
        return

    notes_start = min(notes_pages)

    for section_key in CORE_STATEMENT_KEYS:
        pages = found_sections.get(section_key, [])

        if not pages:
            continue

        found_sections[section_key] = [
            page
            for page in pages
            if page < notes_start
        ]


def build_section_confidence(
    found_sections: dict[str, list[int]],
    page_ranges: list[PageRange],
) -> dict[str, float]:
    section_confidence: dict[str, float] = {}
    reason_by_section: dict[str, str] = {}

    for page_range in page_ranges:
        reason = page_range["reason"]

        for section_key in TARGET_SECTION_ORDER:
            if reason.startswith(section_key):
                reason_by_section[section_key] = reason

    for section_key in TARGET_SECTION_ORDER:
        pages = found_sections.get(section_key, [])

        if not pages:
            section_confidence[section_key] = 0.0
            continue

        reason = reason_by_section.get(section_key, "")

        if "from_toc" in reason:
            section_confidence[section_key] = 0.95
        elif "detected" in reason:
            section_confidence[section_key] = 0.9
        elif "heading_scan" in reason:
            section_confidence[section_key] = 0.75
        else:
            section_confidence[section_key] = 0.7

    return section_confidence


def create_filtered_pdf(
    input_pdf_path: str,
    output_pdf_path: str,
    selected_pages: list[int],
) -> dict[str, int]:
    source = fitz.open(input_pdf_path)
    output = fitz.open()
    page_map: dict[str, int] = {}

    for filtered_index, original_page_number in enumerate(selected_pages, start=1):
        output.insert_pdf(
            source,
            from_page=original_page_number - 1,
            to_page=original_page_number - 1,
        )
        page_map[str(filtered_index)] = original_page_number

    if selected_pages:
        Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path)

    output.close()
    source.close()

    return page_map


def create_selected_pages_json(
    input_pdf_path: str,
    selected_pages_json_path: str,
    selected_pages: list[int],
    found_sections: dict[str, list[int]],
    missing_sections: list[str],
    missing_required_sections: list[str],
    missing_optional_sections: list[str],
    section_confidence: dict[str, float],
) -> None:
    data = {
        "pdf_name": Path(input_pdf_path).name,
        "selected_pages": selected_pages,
        "found_sections": found_sections,
        "missing_sections": missing_sections,
        "missing_required_sections": missing_required_sections,
        "missing_optional_sections": missing_optional_sections,
        "section_confidence": section_confidence,
    }

    Path(selected_pages_json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(selected_pages_json_path).write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def filter_pdf(
    input_pdf_path: str,
    output_pdf_path: Optional[str] = None,
    selected_pages_json_path: Optional[str] = None,
    log_path: Optional[str] = None,
    include_notes: str = "first",
    include_auditor: bool = True,
) -> FilterResult:
    pages = read_pdf_pages(input_pdf_path)
    total_pages = len(pages)

    document_type, type_confidence = detect_document_type(pages)
    page_offset = get_report_page_offset(pages)

    detected_printed_page_lists = extract_toc_printed_page_lists(pages)

    detected_pdf_page_lists = convert_toc_printed_to_pdf_page_lists(
        detected_printed_page_lists,
        pages,
        page_offset,
    )

    detected_printed_pages = first_page_dict(detected_printed_page_lists)
    detected_pdf_pages = first_page_dict(detected_pdf_page_lists)

    found_sections, page_ranges = build_section_pages_from_toc(
        detected_pdf_page_lists,
        pages,
    )

    main_toc_pages = detect_main_toc_pages(pages)

    if main_toc_pages:
        add_pages(
            found_sections,
            page_ranges,
            "main_table_of_contents",
            main_toc_pages,
            total_pages,
            "main_table_of_contents_detected",
        )

    heading_results = heading_scan_pdf_pages(pages)

    merge_heading_scan_results(
        found_sections=found_sections,
        page_ranges=page_ranges,
        heading_results=heading_results,
        total_pages=total_pages,
    )

    remove_invalid_financial_statement_detections(found_sections)

    combined_page = detect_combined_profit_or_loss_and_oci_page(pages)

    if combined_page:
        if not found_sections.get("profit_or_loss"):
            found_sections["profit_or_loss"] = [combined_page]

        if not found_sections.get("comprehensive_income"):
            found_sections["comprehensive_income"] = [combined_page]

        page_ranges.append(
            {
                "start": combined_page,
                "end": combined_page,
                "reason": "combined_profit_or_loss_and_comprehensive_income_detected",
            }
        )

    notes_toc_pages = detect_notes_toc_pages(
        pages=pages,
        found_sections=found_sections,
        detected_pdf_page_lists=detected_pdf_page_lists,
    )

    if notes_toc_pages:
        add_pages(
            found_sections,
            page_ranges,
            "notes_table_of_contents",
            notes_toc_pages,
            total_pages,
            "notes_table_of_contents_detected",
        )

    if not include_auditor:
        found_sections["independent_auditors_report"] = []

    selected_pages = sorted(
        {
            page_number
            for page_list in found_sections.values()
            for page_number in page_list
            if 1 <= page_number <= total_pages
        }
    )

    missing_sections = [
        section_key
        for section_key in TARGET_SECTION_ORDER
        if not found_sections.get(section_key)
    ]

    missing_required_sections = [
        section_key
        for section_key in REQUIRED_SECTIONS
        if not found_sections.get(section_key)
    ]

    missing_optional_sections = [
        section_key
        for section_key in OPTIONAL_SECTIONS
        if not found_sections.get(section_key)
    ]

    section_confidence = build_section_confidence(found_sections, page_ranges)

    all_pages = set(range(1, total_pages + 1))
    removed_pages = sorted(all_pages - set(selected_pages))

    filtered_page_map: dict[str, int] = {}

    if output_pdf_path and selected_pages:
        filtered_page_map = create_filtered_pdf(
            input_pdf_path=input_pdf_path,
            output_pdf_path=output_pdf_path,
            selected_pages=selected_pages,
        )

    if selected_pages_json_path:
        create_selected_pages_json(
            input_pdf_path=input_pdf_path,
            selected_pages_json_path=selected_pages_json_path,
            selected_pages=selected_pages,
            found_sections=found_sections,
            missing_sections=missing_sections,
            missing_required_sections=missing_required_sections,
            missing_optional_sections=missing_optional_sections,
            section_confidence=section_confidence,
        )

    found_required_count = len(REQUIRED_SECTIONS) - len(missing_required_sections)
    required_confidence = found_required_count / len(REQUIRED_SECTIONS)

    average_section_confidence = (
        sum(section_confidence.values()) / len(section_confidence)
        if section_confidence
        else 0
    )

    confidence = round(
        (type_confidence + required_confidence + average_section_confidence) / 3,
        2,
    )

    result: FilterResult = {
        "inputPdfPath": input_pdf_path,
        "pdfName": Path(input_pdf_path).name,
        "documentType": document_type,
        "filterProfile": "target_section_filter_v7_financial_toc_block",
        "selectedPages": selected_pages,
        "wantedPages": selected_pages,
        "removedPages": removed_pages,
        "foundSections": found_sections,
        "missingSections": missing_sections,
        "missingRequiredSections": missing_required_sections,
        "missingOptionalSections": missing_optional_sections,
        "sectionConfidence": section_confidence,
        "pageRanges": page_ranges,
        "filteredPdfPath": output_pdf_path if output_pdf_path and selected_pages else None,
        "selectedPagesJsonPath": selected_pages_json_path,
        "filteredPageMap": filtered_page_map,
        "confidence": confidence,
        "totalPages": total_pages,
        "logPath": log_path,
        "detectionMethod": "main_contents_financial_block_offset_validated_v7",
        "detectedTocPrintedPages": detected_printed_pages,
        "detectedTocPdfPages": detected_pdf_pages,
        "detectedTocPrintedPageLists": detected_printed_page_lists,
        "detectedTocPdfPageLists": detected_pdf_page_lists,
        "pageOffset": page_offset,
    }

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CSE target financial statement page filter."
    )

    parser.add_argument("input_pdf", help="Original input PDF path")
    parser.add_argument("--output-pdf", help="Optional filtered PDF output path")
    parser.add_argument("--selected-pages-json", help="Selected pages JSON path")
    parser.add_argument("--log", help="Optional full filter log JSON path")
    parser.add_argument(
        "--no-auditor",
        action="store_true",
        help="Exclude independent auditor report pages",
    )

    args = parser.parse_args()

    result = filter_pdf(
        input_pdf_path=args.input_pdf,
        output_pdf_path=args.output_pdf,
        selected_pages_json_path=args.selected_pages_json,
        log_path=args.log,
        include_auditor=not args.no_auditor,
    )

    print(json.dumps(result, indent=2))