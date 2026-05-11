import argparse
import json
import re
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


TARGET_SECTION_ORDER = [
    "financial_highlights",
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


TARGET_SECTION_PATTERNS = {
    "financial_highlights": [
        r"\bfinancial highlights\b",
        r"\bperformance highlights\b",
        r"\bkey financial highlights\b",
        r"\bfinancial goals and achievements\b",
    ],
    "profit_or_loss": [
        r"\bstatement of profit or loss and other comprehensive income\b",
        r"\bstatement of profit or loss\b",
        r"\bincome statement\b",
        r"\bstatement of income\b",
        r"\bconsolidated statement of profit or loss and other comprehensive income\b",
        r"\bconsolidated statement of profit or loss\b",
    ],
    "comprehensive_income": [
        r"\bstatement of comprehensive income\b",
        r"\bstatement of other comprehensive income\b",
        r"\bstatement of profit or loss and other comprehensive income\b",
        r"\bconsolidated statement of comprehensive income\b",
        r"\bconsolidated statement of profit or loss and other comprehensive income\b",
    ],
    "financial_position": [
        r"\bstatement of financial position\b",
        r"\bconsolidated statement of financial position\b",
        r"\bbalance sheet\b",
    ],
    "changes_in_equity": [
        r"\bstatement of changes in equity\b",
        r"\bconsolidated statement of changes in equity\b",
        r"\bchanges in equity\b",
    ],
    "cash_flows": [
        r"\bstatement of cash flows\b",
        r"\bconsolidated statement of cash flows\b",
        r"\bcash flow statement\b",
    ],
    "notes_to_financial_statements": [
        r"\bnotes to the financial statements\b",
        r"\bnotes to financial statements\b",
        r"\bnotes to the consolidated financial statements\b",
    ],
    "shareholder_or_investor_information": [
        r"\bshareholder information\b",
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
        r"\bten-year achievements\b",
        r"\bten year achievements\b",
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
    ],
}


CORE_STATEMENT_KEYS = [
    "profit_or_loss",
    "comprehensive_income",
    "financial_position",
    "changes_in_equity",
    "cash_flows",
]


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
    r"\bnotes to the financial statements\b",
    r"\bstatement of financial position\b",
    r"\bstatement of cash flows\b",
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


def normalize_text(text: str) -> str:
    text = text.replace("’", "'")
    text = text.replace("‘", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    text = text.replace("￾", "")
    return re.sub(r"\s+", " ", text.lower()).strip()


def normalize_line(text: str) -> str:
    text = text.replace("’", "'")
    text = text.replace("‘", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    text = text.replace("￾", "")
    return re.sub(r"\s+", " ", text.lower()).strip()


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
    candidates = lines[:12] + lines[-12:]

    for line in candidates:
        if re.fullmatch(r"\d{1,3}", line):
            value = int(line)
            if 1 <= value <= 800:
                return value

    for line in candidates:
        match = re.search(r"\bannual report.*?\b(\d{1,3})\s*$", line, re.I)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 800:
                return value

    return None


def looks_like_main_toc_page(text: str) -> bool:
    normalized = normalize_text(text)
    lines = [normalize_line(line) for line in text.splitlines() if line.strip()]

    if has_pattern(normalized[:1200], TOC_PATTERNS):
        return True

    numbered_lines = 0

    for line in lines:
        if re.search(r"^\s*\d{1,3}\s+[a-z]", line):
            numbered_lines += 1
        elif re.search(r"[a-z].{3,80}\s+\d{1,3}\s*$", line):
            numbered_lines += 1

    has_financial_statement_list = (
        "statement of financial position" in normalized
        and "statement of cash flows" in normalized
        and "notes to the financial statements" in normalized
    )

    return numbered_lines >= 8 or has_financial_statement_list


def count_note_index_lines(text: str) -> int:
    count = 0
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in lines:
        normalized = normalize_line(line)

        if re.search(
            r"^\s*\d{1,2}(\.\d{1,2})?\s+[a-z][a-z0-9,&()/\-\s]{3,100}\s+\d{1,3}\s*$",
            normalized,
        ):
            count += 1

        elif re.search(
            r"^\s*\d{1,2}(\.\d{1,2})?\s+[a-z][a-z0-9,&()/\-\s]{3,100}$",
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

    if note_index_count >= 6:
        return True

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

    return has_note_index_keywords


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
    offsets: dict[int, int] = {}

    for page in pages:
        printed_page = page.get("printedPageNumber")

        if not printed_page:
            continue

        pdf_page = page["pageNumber"]
        offset = pdf_page - printed_page

        if -30 <= offset <= 30:
            offsets[offset] = offsets.get(offset, 0) + 1

    if not offsets:
        return None

    return max(offsets.items(), key=lambda item: item[1])[0]


def printed_to_pdf_page(
    printed_page: int,
    pages: list[dict],
    offset: Optional[int],
) -> Optional[int]:
    for page in pages:
        if page.get("printedPageNumber") == printed_page:
            return page["pageNumber"]

    if offset is not None:
        candidate = printed_page + offset
        if 1 <= candidate <= len(pages):
            return candidate

    if 1 <= printed_page <= len(pages):
        return printed_page

    return None


def extract_toc_printed_pages(pages: list[dict]) -> dict[str, int]:
    detected: dict[str, int] = {}

    toc_pages = [
        page for page in pages
        if page["isMainToc"] or page["pageNumber"] <= 8
    ]

    for page in toc_pages:
        lines = [normalize_line(line) for line in page["text"].splitlines() if line.strip()]
        full_text = normalize_text(page["text"])

        for section_key, patterns in TARGET_SECTION_PATTERNS.items():
            if section_key == "notes_table_of_contents":
                continue

            if section_key in detected:
                continue

            for line in lines:
                for pattern in patterns:
                    # Format: 279 Statement of Profit or Loss
                    before_match = re.search(
                        r"^\s*(\d{1,3})\s+.{0,30}?" + pattern,
                        line,
                    )

                    if before_match:
                        value = int(before_match.group(1))
                        if 1 <= value <= 800:
                            detected[section_key] = value
                            break

                    # Format: Statement of Profit or Loss 279
                    after_match = re.search(
                        pattern + r".{0,100}?\b(\d{1,3})\s*$",
                        line,
                    )

                    if after_match:
                        value = int(after_match.group(1))
                        if 1 <= value <= 800:
                            detected[section_key] = value
                            break

                if section_key in detected:
                    break

            if section_key in detected:
                continue

            for pattern in patterns:
                # Block fallback: prefer number before title.
                before_match = re.search(
                    r"\b(\d{1,3})\b.{0,80}?" + pattern,
                    full_text,
                )

                if before_match:
                    value = int(before_match.group(1))
                    if 1 <= value <= 800:
                        detected[section_key] = value
                        break

                after_match = re.search(
                    pattern + r".{0,120}?\b(\d{1,3})\b",
                    full_text,
                )

                if after_match:
                    value = int(after_match.group(1))
                    if 1 <= value <= 800:
                        detected[section_key] = value
                        break

    return detected


def convert_toc_printed_to_pdf_pages(
    detected_printed_pages: dict[str, int],
    pages: list[dict],
) -> dict[str, int]:
    offset = get_report_page_offset(pages)
    detected_pdf_pages: dict[str, int] = {}

    for section_key, printed_page in detected_printed_pages.items():
        pdf_page = printed_to_pdf_page(printed_page, pages, offset)

        if pdf_page:
            detected_pdf_pages[section_key] = pdf_page

    return detected_pdf_pages


def page_matches_section(page: dict, section_key: str) -> bool:
    patterns = TARGET_SECTION_PATTERNS[section_key]
    top_text = page["topText"]

    return has_pattern(top_text, patterns)


def is_probably_real_statement_page(page: dict, section_key: str) -> bool:
    if page["isMainToc"]:
        return False

    if not page_matches_section(page, section_key):
        return False

    if section_key in CORE_STATEMENT_KEYS:
        return page["numberCount"] >= 8 or page["financialLabelCount"] >= 2

    return True


def heading_scan_pdf_pages(pages: list[dict]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {key: [] for key in TARGET_SECTION_ORDER}

    for page in pages:
        for section_key in TARGET_SECTION_ORDER:
            if section_key == "notes_table_of_contents":
                continue

            if found[section_key]:
                continue

            if is_probably_real_statement_page(page, section_key):
                found[section_key].append(page["pageNumber"])

    return found


def get_next_boundary_page(
    current_section: str,
    current_page: int,
    detected_pdf_pages: dict[str, int],
    total_pages: int,
) -> Optional[int]:
    boundary_keys = CORE_STATEMENT_KEYS + [
        "notes_to_financial_statements",
        "shareholder_or_investor_information",
        "ten_year_summary",
        "five_year_summary",
    ]

    future_pages = []

    for key in boundary_keys:
        page_number = detected_pdf_pages.get(key)

        if page_number and page_number > current_page:
            future_pages.append(page_number)

    if not future_pages:
        return None

    return min(future_pages)


def build_section_pages_from_toc(
    detected_pdf_pages: dict[str, int],
    pages: list[dict],
) -> tuple[dict[str, list[int]], list[PageRange]]:
    total_pages = len(pages)
    found_sections: dict[str, list[int]] = {key: [] for key in TARGET_SECTION_ORDER}
    page_ranges: list[PageRange] = []

    for section_key in TARGET_SECTION_ORDER:
        if section_key == "notes_table_of_contents":
            continue

        start_page = detected_pdf_pages.get(section_key)

        if not start_page:
            continue

        if section_key in CORE_STATEMENT_KEYS:
            next_boundary = get_next_boundary_page(
                current_section=section_key,
                current_page=start_page,
                detected_pdf_pages=detected_pdf_pages,
                total_pages=total_pages,
            )

            if next_boundary:
                end_page = min(next_boundary - 1, start_page + 2)
            else:
                end_page = min(start_page + 1, total_pages)

            add_pages(
                found_sections,
                page_ranges,
                section_key,
                list(range(start_page, end_page + 1)),
                total_pages,
                f"{section_key}_from_toc",
            )

        elif section_key == "notes_to_financial_statements":
            add_pages(
                found_sections,
                page_ranges,
                section_key,
                [start_page],
                total_pages,
                "notes_to_financial_statements_start_from_toc",
            )

        elif section_key == "shareholder_or_investor_information":
            add_pages(
                found_sections,
                page_ranges,
                section_key,
                [start_page, start_page + 1],
                total_pages,
                "shareholder_or_investor_information_from_toc",
            )

        elif section_key in ["ten_year_summary", "five_year_summary"]:
            add_pages(
                found_sections,
                page_ranges,
                section_key,
                [start_page, start_page + 1],
                total_pages,
                f"{section_key}_from_toc",
            )

        elif section_key == "financial_highlights":
            add_pages(
                found_sections,
                page_ranges,
                section_key,
                [start_page, start_page + 1],
                total_pages,
                "financial_highlights_from_toc",
            )

    return found_sections, page_ranges


def detect_notes_toc_pages(
    pages: list[dict],
    found_sections: dict[str, list[int]],
    detected_pdf_pages: dict[str, int],
) -> list[int]:
    total_pages = len(pages)
    candidate_pages: set[int] = set()

    notes_start_pages = found_sections.get("notes_to_financial_statements", [])

    if not notes_start_pages and detected_pdf_pages.get("notes_to_financial_statements"):
        notes_start_pages = [detected_pdf_pages["notes_to_financial_statements"]]

    if notes_start_pages:
        notes_start = min(notes_start_pages)

        for page_number in range(
            max(1, notes_start - 3),
            min(total_pages, notes_start + 4) + 1,
        ):
            page = pages[page_number - 1]

            if page["isNotesToc"]:
                candidate_pages.add(page_number)

        # Many reports place the notes index immediately before notes.
        previous_page = notes_start - 1
        if previous_page >= 1 and pages[previous_page - 1]["isNotesToc"]:
            candidate_pages.add(previous_page)

        # Some reports use the notes start page itself as the notes contents/index page.
        if pages[notes_start - 1]["isNotesToc"]:
            candidate_pages.add(notes_start)

    # Global fallback: only accept strong notes TOC pages, not normal main contents pages.
    for page in pages:
        if page["isNotesToc"] and not page["isMainToc"]:
            candidate_pages.add(page["pageNumber"])

    return sorted(candidate_pages)


def merge_heading_scan_results(
    found_sections: dict[str, list[int]],
    page_ranges: list[PageRange],
    heading_results: dict[str, list[int]],
    total_pages: int,
) -> None:
    for section_key, pages_found in heading_results.items():
        if section_key == "notes_table_of_contents":
            continue

        if found_sections.get(section_key):
            continue

        if not pages_found:
            continue

        add_pages(
            found_sections,
            page_ranges,
            section_key,
            pages_found,
            total_pages,
            f"{section_key}_from_heading_scan",
        )


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
) -> None:
    data = {
        "pdf_name": Path(input_pdf_path).name,
        "selected_pages": selected_pages,
        "found_sections": found_sections,
        "missing_sections": missing_sections,
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
    include_auditor: bool = False,
) -> FilterResult:
    pages = read_pdf_pages(input_pdf_path)
    total_pages = len(pages)

    document_type, type_confidence = detect_document_type(pages)

    detected_printed_pages = extract_toc_printed_pages(pages)
    detected_pdf_pages = convert_toc_printed_to_pdf_pages(
        detected_printed_pages,
        pages,
    )

    found_sections, page_ranges = build_section_pages_from_toc(
        detected_pdf_pages,
        pages,
    )

    heading_results = heading_scan_pdf_pages(pages)

    merge_heading_scan_results(
        found_sections=found_sections,
        page_ranges=page_ranges,
        heading_results=heading_results,
        total_pages=total_pages,
    )

    notes_toc_pages = detect_notes_toc_pages(
        pages=pages,
        found_sections=found_sections,
        detected_pdf_pages=detected_pdf_pages,
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
        )

    found_count = len(TARGET_SECTION_ORDER) - len(missing_sections)
    section_confidence = found_count / len(TARGET_SECTION_ORDER)
    confidence = round((type_confidence + section_confidence) / 2, 2)

    result: FilterResult = {
        "inputPdfPath": input_pdf_path,
        "pdfName": Path(input_pdf_path).name,
        "documentType": document_type,
        "filterProfile": "target_section_filter_v2",
        "selectedPages": selected_pages,
        "wantedPages": selected_pages,
        "removedPages": removed_pages,
        "foundSections": found_sections,
        "missingSections": missing_sections,
        "pageRanges": page_ranges,
        "filteredPdfPath": output_pdf_path if output_pdf_path and selected_pages else None,
        "selectedPagesJsonPath": selected_pages_json_path,
        "filteredPageMap": filtered_page_map,
        "confidence": confidence,
        "totalPages": total_pages,
        "logPath": log_path,
        "detectionMethod": "toc_first_with_heading_fallback",
        "detectedTocPrintedPages": detected_printed_pages,
        "detectedTocPdfPages": detected_pdf_pages,
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

    args = parser.parse_args()

    result = filter_pdf(
        input_pdf_path=args.input_pdf,
        output_pdf_path=args.output_pdf,
        selected_pages_json_path=args.selected_pages_json,
        log_path=args.log,
    )

    print(json.dumps(result, indent=2))