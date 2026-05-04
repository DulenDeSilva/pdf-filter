import fitz
import pdfplumber
import re
import json
from pathlib import Path
from typing import Optional, TypedDict, Literal


class PageRange(TypedDict):
    start: int
    end: int
    reason: str


class FilterResult(TypedDict):
    inputPdfPath: str
    documentType: str
    filterProfile: str
    wantedPages: list[int]
    removedPages: list[int]
    pageRanges: list[PageRange]
    filteredPdfPath: Optional[str]
    filteredPageMap: dict[str, int]
    confidence: float
    totalPages: int
    logPath: Optional[str]
    detectionMethod: str
    detectedSections: dict[str, int]


NotesMode = Literal["none", "first", "full"]


ANNUAL_KEYWORDS = [
    r"\bannual report\b",
    r"\bindependent auditor\b",
    r"\bindependent auditors\b",
    r"\bnotes to the financial statements\b",
    r"\bstatement of financial position\b",
    r"\bstatement of profit or loss\b",
    r"\bstatement of cash flows\b",
    r"\bstatement of changes in equity\b",
]

QUARTERLY_KEYWORDS = [
    r"\binterim financial statements\b",
    r"\binterim financial statement\b",
    r"\bconsolidated interim financial statements\b",
    r"\bprovisional financial statements\b",
    r"\bprovisional financial statement\b",
    r"\bquarter ended\b",
    r"\bfor the quarter ended\b",
    r"\bthree months ended\b",
    r"\bsix months ended\b",
    r"\bnine months ended\b",
    r"\bfor the period ended\b",
    r"\bfor the year ended\b",
    r"\bcondensed statement\b",
    r"\bunaudited\b",
]


TOC_PATTERNS = [
    r"\bcontents\b",
    r"\btable of contents\b",
]


SECTION_PATTERNS = {
    "independent_auditor_report": [
        r"\bindependent auditor[’']?s? report\b",
        r"\bindependent auditors[’']? report\b",
    ],
    "statement_of_financial_position": [
        r"\bstatement of financial position\b",
        r"\bbalance sheet\b",
    ],
    "statement_of_profit_or_loss": [
        r"\bstatement of profit or loss and other comprehensive income\b",
        r"\bstatement of profit or loss\b",
        r"\bincome statement\b",
    ],
    "statement_of_comprehensive_income": [
        r"\bstatement of comprehensive income\b",
        r"\bstatement of other comprehensive income\b",
    ],
    "statement_of_changes_in_equity": [
        r"\bstatement of changes in equity\b",
        r"\bchanges in equity\b",
    ],
    "statement_of_cash_flows": [
        r"\bstatement of cash flows\b",
        r"\bcash flow statement\b",
    ],
    "notes_to_financial_statements": [
        r"\bnotes to the financial statements\b",
        r"\bnotes to financial statements\b",
    ],
}


MAIN_STATEMENT_SECTION_KEYS = [
    "statement_of_financial_position",
    "statement_of_profit_or_loss",
    "statement_of_comprehensive_income",
    "statement_of_changes_in_equity",
    "statement_of_cash_flows",
]


END_SECTION_PATTERNS = [
    r"\binvestor information\b",
    r"\bshareholder information\b",
    r"\binformation to shareholders\b",
    r"\bnotice of annual general meeting\b",
    r"\bnotice of meeting\b",
    r"\bform of proxy\b",
    r"\bproxy form\b",
    r"\bcorporate directory\b",
    r"\bcorporate information\b",
    r"\bother disclosures\b",
    r"\bsupplementary information\b",
]


UNWANTED_HEADING_PATTERNS = [
    r"\babout us\b",
    r"\bchairman[’']?s review\b",
    r"\bchairman[’']?s message\b",
    r"\bchairperson[’']?s review\b",
    r"\bchairperson[’']?s message\b",
    r"\bdirector/ceo[’']?s review\b",
    r"\bdirector ceo[’']?s review\b",
    r"\bdirectors?/ceo[’']?s review\b",
    r"\bchief executive officer\b",
    r"\bceo[’']?s review\b",
    r"\bboard of directors\b",
    r"\bboard profiles\b",
    r"\breview of operations\b",
    r"\bmanagement discussion and analysis\b",
    r"\bmanagement discussion\b",
    r"\bstewardship\b",
    r"\bcorporate governance\b",
    r"\bsustainability\b",
    r"\bawards\b",
    r"\bcompany profile\b",
    r"\bour vision\b",
    r"\bour mission\b",
    r"\btransportation\b",
    r"\bbusiness review\b",
    r"\bleadership\b",
]


FINANCIAL_ROW_LABEL_PATTERNS = [
    r"\brevenue\b",
    r"\bturnover\b",
    r"\bgross profit\b",
    r"\bgross income\b",
    r"\binterest income\b",
    r"\binterest expense\b",
    r"\bnet interest income\b",
    r"\bprofit before tax\b",
    r"\bprofit before income tax\b",
    r"\bincome tax expense\b",
    r"\bprofit for the year\b",
    r"\bprofit for the period\b",
    r"\bprofit after tax\b",
    r"\bearnings per share\b",
    r"\bbasic earnings per share\b",
    r"\bdiluted earnings per share\b",
    r"\bassets\b",
    r"\btotal assets\b",
    r"\bcurrent assets\b",
    r"\bnon-current assets\b",
    r"\bliabilities\b",
    r"\btotal liabilities\b",
    r"\bcurrent liabilities\b",
    r"\bnon-current liabilities\b",
    r"\bequity\b",
    r"\btotal equity\b",
    r"\bstated capital\b",
    r"\bretained earnings\b",
    r"\breserves\b",
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
    return re.sub(r"\s+", " ", text.lower()).strip()


def get_heading_text(text: str, max_chars: int = 900) -> str:
    return normalize_text(text)[:max_chars]


def has_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def count_matches(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text))


def count_numbers(text: str) -> int:
    return len(re.findall(r"\(?\d[\d,\.]*\)?", text))


def count_sentences(text: str) -> int:
    return len(re.findall(r"[.!?]", text))


def count_lines(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def clamp_range(start: int, end: int, total_pages: int) -> tuple[int, int]:
    return max(1, start), min(total_pages, end)


def add_page_range(
    wanted_pages: set[int],
    page_ranges: list[PageRange],
    start: int,
    end: int,
    total_pages: int,
    reason: str,
) -> None:
    start, end = clamp_range(start, end, total_pages)

    if start > end:
        return

    for page_number in range(start, end + 1):
        wanted_pages.add(page_number)

    page_ranges.append({
        "start": start,
        "end": end,
        "reason": reason,
    })


def get_pdfplumber_table_count(input_pdf_path: str) -> dict[int, int]:
    table_counts: dict[int, int] = {}

    try:
        with pdfplumber.open(input_pdf_path) as pdf:
            for index, page in enumerate(pdf.pages):
                page_number = index + 1

                try:
                    table_counts[page_number] = len(page.find_tables())
                except Exception:
                    table_counts[page_number] = 0
    except Exception:
        return {}

    return table_counts


def extract_printed_page_number(raw_text: str) -> Optional[int]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    candidates = lines[:10] + lines[-10:]

    for line in candidates:
        if re.fullmatch(r"\d{1,3}", line):
            value = int(line)
            if 1 <= value <= 500:
                return value

    for line in candidates:
        match = re.search(r"\b(?:annual report|interim report|financial statements).*?\b(\d{1,3})\s*$", line, re.I)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 500:
                return value

    return None


def read_pdf_pages(input_pdf_path: str) -> list[dict]:
    table_counts = get_pdfplumber_table_count(input_pdf_path)

    doc = fitz.open(input_pdf_path)
    pages = []

    for index, page in enumerate(doc):
        page_number = index + 1
        text = page.get_text("text") or ""
        normalized = normalize_text(text)
        heading_text = get_heading_text(text)

        number_count = count_numbers(normalized)
        sentence_count = count_sentences(text)
        line_count = count_lines(text)
        table_count = table_counts.get(page_number, 0)
        financial_label_count = count_matches(normalized, FINANCIAL_ROW_LABEL_PATTERNS)

        is_toc = has_pattern(heading_text, TOC_PATTERNS)

        is_unwanted = has_pattern(heading_text, UNWANTED_HEADING_PATTERNS)

        has_statement_heading = any(
            count_matches(heading_text, patterns) > 0
            for key, patterns in SECTION_PATTERNS.items()
            if key in MAIN_STATEMENT_SECTION_KEYS
        )

        has_auditor_heading = count_matches(
            heading_text,
            SECTION_PATTERNS["independent_auditor_report"],
        ) > 0

        has_notes_heading = count_matches(
            heading_text,
            SECTION_PATTERNS["notes_to_financial_statements"],
        ) > 0

        is_table_like = (
            (table_count >= 1 and number_count >= 15)
            or (number_count >= 45 and line_count >= 20 and sentence_count <= 10)
            or (financial_label_count >= 5 and number_count >= 20)
        )

        is_paragraph_heavy = (
            not has_statement_heading
            and not has_auditor_heading
            and not has_notes_heading
            and not is_toc
            and (
                sentence_count >= 12
                or (line_count >= 30 and financial_label_count < 4)
            )
        )

        pages.append({
            "pageNumber": page_number,
            "text": text,
            "normalizedText": normalized,
            "headingText": heading_text,
            "printedPageNumber": extract_printed_page_number(text),
            "numberCount": number_count,
            "sentenceCount": sentence_count,
            "lineCount": line_count,
            "tableCount": table_count,
            "financialLabelCount": financial_label_count,
            "isToc": is_toc,
            "isUnwanted": is_unwanted,
            "hasStatementHeading": has_statement_heading,
            "hasAuditorHeading": has_auditor_heading,
            "hasNotesHeading": has_notes_heading,
            "isTableLike": is_table_like,
            "isParagraphHeavy": is_paragraph_heavy,
            "textLength": len(normalized),
        })

    doc.close()
    return pages


def detect_document_type(pages: list[dict]) -> tuple[str, str, float]:
    total_pages = len(pages)

    first_pages_text = " ".join(
        page["normalizedText"] for page in pages[: min(10, total_pages)]
    )

    broader_text_sample = " ".join(
        page["normalizedText"] for page in pages[: min(30, total_pages)]
    )

    annual_score = sum(
        1
        for pattern in ANNUAL_KEYWORDS
        if re.search(pattern, first_pages_text) or re.search(pattern, broader_text_sample)
    )

    quarterly_score = sum(
        1
        for pattern in QUARTERLY_KEYWORDS
        if re.search(pattern, first_pages_text) or re.search(pattern, broader_text_sample)
    )

    full_text_length = sum(page["textLength"] for page in pages)
    avg_text_length = full_text_length / max(total_pages, 1)

    if avg_text_length < 80:
        return "scanned_unknown", "ocr_required_filter", 0.45

    if total_pages <= 80 and quarterly_score >= 1:
        return "quarterly_report", "toc_statement_filter", 0.9

    if annual_score >= 2 or total_pages > 80:
        return "annual_report", "toc_statement_filter", 0.88

    return "other_report", "toc_statement_filter", 0.65


def get_report_page_offset(pages: list[dict]) -> Optional[int]:
    offsets: dict[int, int] = {}

    for page in pages:
        printed = page.get("printedPageNumber")

        if not printed:
            continue

        pdf_page = page["pageNumber"]
        offset = pdf_page - printed
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

    return None


def get_toc_pages(pages: list[dict]) -> list[int]:
    toc_pages = []

    for page in pages:
        if page["isToc"]:
            toc_pages.append(page["pageNumber"])

    return toc_pages


def extract_financial_block_from_toc_text(text: str) -> str:
    normalized = normalize_text(text)

    start = normalized.find("financial statements")

    if start == -1:
        return normalized

    end_candidates = []

    for marker in [
        "financial information for last ten years",
        "quarterly statement",
        "investor information",
        "other disclosures",
        "supplementary information",
        "notice of annual general meeting",
    ]:
        index = normalized.find(marker, start + 1)

        if index != -1:
            end_candidates.append(index)

    end = min(end_candidates) if end_candidates else len(normalized)

    return normalized[start:end]


def extract_toc_section_printed_pages(pages: list[dict]) -> dict[str, int]:
    detected: dict[str, int] = {}

    toc_pages = [page for page in pages if page["isToc"]]

    for page in toc_pages:
        block = extract_financial_block_from_toc_text(page["text"])

        for section_key, patterns in SECTION_PATTERNS.items():
            if section_key in detected:
                continue

            for pattern in patterns:
                # Section title followed by a report page number.
                regex = pattern + r".{0,140}?\b(\d{1,3})\b"
                match = re.search(regex, block)

                if match:
                    value = int(match.group(1))

                    if 1 <= value <= 500:
                        detected[section_key] = value
                        break

    return detected


def toc_based_filter(
    pages: list[dict],
    include_notes: NotesMode = "none",
    include_auditor: bool = True,
) -> tuple[list[int], list[PageRange], float, dict[str, int]]:
    total_pages = len(pages)
    wanted_pages: set[int] = set()
    page_ranges: list[PageRange] = []

    toc_page_numbers = get_toc_pages(pages)

    for page_number in toc_page_numbers:
        add_page_range(
            wanted_pages,
            page_ranges,
            page_number,
            page_number,
            total_pages,
            "table_of_contents",
        )

    detected_printed_pages = extract_toc_section_printed_pages(pages)

    if len(detected_printed_pages) < 3:
        return [], [], 0.0, {}

    offset = get_report_page_offset(pages)

    detected_pdf_pages: dict[str, int] = {}

    for section_key, printed_page in detected_printed_pages.items():
        pdf_page = printed_to_pdf_page(printed_page, pages, offset)

        if pdf_page:
            detected_pdf_pages[section_key] = pdf_page

    if len(detected_pdf_pages) < 3:
        return [], [], 0.0, {}

    ordered_sections = sorted(
        detected_pdf_pages.items(),
        key=lambda item: item[1],
    )

    for index, (section_key, start_page) in enumerate(ordered_sections):
        if section_key == "notes_to_financial_statements" and include_notes == "none":
            continue

        if section_key == "independent_auditor_report" and not include_auditor:
            continue

        next_start = None

        for later_key, later_page in ordered_sections[index + 1:]:
            if later_page > start_page:
                next_start = later_page
                break

        if section_key == "independent_auditor_report":
            if next_start:
                end_page = next_start - 1
            else:
                end_page = start_page + 3

            add_page_range(
                wanted_pages,
                page_ranges,
                start_page,
                end_page,
                total_pages,
                "independent_auditor_report_from_toc",
            )

        elif section_key in MAIN_STATEMENT_SECTION_KEYS:
            if next_start:
                end_page = min(next_start - 1, start_page + 3)
            else:
                end_page = start_page + 2

            add_page_range(
                wanted_pages,
                page_ranges,
                start_page,
                end_page,
                total_pages,
                f"{section_key}_from_toc",
            )

        elif section_key == "notes_to_financial_statements":
            if include_notes == "first":
                end_page = start_page
            elif include_notes == "full":
                end_page = find_notes_end_page(pages, start_page)
            else:
                continue

            add_page_range(
                wanted_pages,
                page_ranges,
                start_page,
                end_page,
                total_pages,
                "notes_to_financial_statements_from_toc",
            )

    cleaned_pages = clean_selected_pages(
        pages,
        wanted_pages,
        keep_toc=True,
        keep_auditor=include_auditor,
    )

    confidence = 0.93 if len(cleaned_pages) >= 4 else 0.65

    return sorted(cleaned_pages), page_ranges, confidence, detected_pdf_pages


def find_notes_end_page(pages: list[dict], notes_start_page: int) -> int:
    for page in pages:
        page_number = page["pageNumber"]

        if page_number <= notes_start_page:
            continue

        if has_pattern(page["headingText"], END_SECTION_PATTERNS):
            return page_number - 1

    return len(pages)


def fallback_heading_filter(
    pages: list[dict],
    include_notes: NotesMode = "none",
    include_auditor: bool = True,
) -> tuple[list[int], list[PageRange], float, dict[str, int]]:
    total_pages = len(pages)
    wanted_pages: set[int] = set()
    page_ranges: list[PageRange] = []
    detected: dict[str, int] = {}

    for page in pages:
        page_number = page["pageNumber"]

        if page["isToc"]:
            add_page_range(
                wanted_pages,
                page_ranges,
                page_number,
                page_number,
                total_pages,
                "table_of_contents",
            )
            detected["table_of_contents"] = page_number
            continue

        if page["isUnwanted"] or page["isParagraphHeavy"]:
            continue

        if include_auditor and page["hasAuditorHeading"]:
            add_page_range(
                wanted_pages,
                page_ranges,
                page_number,
                page_number + 2,
                total_pages,
                "auditor_heading_fallback",
            )
            detected["independent_auditor_report"] = page_number
            continue

        if page["hasStatementHeading"]:
            add_page_range(
                wanted_pages,
                page_ranges,
                page_number,
                page_number + 1,
                total_pages,
                "statement_heading_fallback",
            )
            detected[f"statement_page_{page_number}"] = page_number
            continue

        if include_notes != "none" and page["hasNotesHeading"]:
            if include_notes == "first":
                end_page = page_number
            else:
                end_page = find_notes_end_page(pages, page_number)

            add_page_range(
                wanted_pages,
                page_ranges,
                page_number,
                end_page,
                total_pages,
                "notes_heading_fallback",
            )
            detected["notes_to_financial_statements"] = page_number

    cleaned_pages = clean_selected_pages(
        pages,
        wanted_pages,
        keep_toc=True,
        keep_auditor=include_auditor,
    )

    confidence = 0.75 if len(cleaned_pages) >= 3 else 0.45

    return sorted(cleaned_pages), page_ranges, confidence, detected


def clean_selected_pages(
    pages: list[dict],
    wanted_pages: set[int],
    keep_toc: bool,
    keep_auditor: bool,
) -> set[int]:
    cleaned: set[int] = set()

    for page_number in wanted_pages:
        page = pages[page_number - 1]

        if keep_toc and page["isToc"]:
            cleaned.add(page_number)
            continue

        if keep_auditor and page["hasAuditorHeading"]:
            cleaned.add(page_number)
            continue

        if page["hasStatementHeading"]:
            cleaned.add(page_number)
            continue

        if page["hasNotesHeading"]:
            cleaned.add(page_number)
            continue

        if page["isUnwanted"]:
            continue

        if page["isParagraphHeavy"]:
            continue

        # Keep continuation pages only when they are table-like and financial.
        if page["isTableLike"] and page["financialLabelCount"] >= 2:
            cleaned.add(page_number)

    return cleaned


def filter_report(
    pages: list[dict],
    include_notes: NotesMode = "none",
    include_auditor: bool = True,
) -> tuple[list[int], list[PageRange], float, str, dict[str, int]]:
    wanted_pages, page_ranges, confidence, detected = toc_based_filter(
        pages,
        include_notes=include_notes,
        include_auditor=include_auditor,
    )

    if wanted_pages:
        return wanted_pages, page_ranges, confidence, "toc_based_filter", detected

    wanted_pages, page_ranges, confidence, detected = fallback_heading_filter(
        pages,
        include_notes=include_notes,
        include_auditor=include_auditor,
    )

    return wanted_pages, page_ranges, confidence, "heading_fallback_filter", detected


def create_filtered_pdf(
    input_pdf_path: str,
    output_pdf_path: str,
    wanted_pages: list[int],
) -> dict[str, int]:
    source = fitz.open(input_pdf_path)
    output = fitz.open()
    page_map: dict[str, int] = {}

    for filtered_index, original_page_number in enumerate(wanted_pages, start=1):
        output.insert_pdf(
            source,
            from_page=original_page_number - 1,
            to_page=original_page_number - 1,
        )
        page_map[str(filtered_index)] = original_page_number

    if wanted_pages:
        Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path)

    output.close()
    source.close()

    return page_map


def filter_pdf(
    input_pdf_path: str,
    output_pdf_path: Optional[str] = None,
    log_path: Optional[str] = None,
    include_notes: NotesMode = "none",
    include_auditor: bool = True,
) -> FilterResult:
    pages = read_pdf_pages(input_pdf_path)

    document_type, filter_profile, type_confidence = detect_document_type(pages)

    if document_type in ["annual_report", "quarterly_report", "other_report"]:
        wanted_pages, page_ranges, filter_confidence, detection_method, detected_sections = filter_report(
            pages,
            include_notes=include_notes,
            include_auditor=include_auditor,
        )
    else:
        wanted_pages = []
        page_ranges = []
        filter_confidence = 0.4
        detection_method = "unsupported_or_scanned"
        detected_sections = {}

    all_pages = set(range(1, len(pages) + 1))
    removed_pages = sorted(all_pages - set(wanted_pages))

    filtered_page_map: dict[str, int] = {}

    if output_pdf_path and wanted_pages:
        filtered_page_map = create_filtered_pdf(
            input_pdf_path=input_pdf_path,
            output_pdf_path=output_pdf_path,
            wanted_pages=wanted_pages,
        )

    confidence = round((type_confidence + filter_confidence) / 2, 2)

    result: FilterResult = {
        "inputPdfPath": input_pdf_path,
        "documentType": document_type,
        "filterProfile": filter_profile,
        "wantedPages": wanted_pages,
        "removedPages": removed_pages,
        "pageRanges": page_ranges,
        "filteredPdfPath": output_pdf_path if output_pdf_path and wanted_pages else None,
        "filteredPageMap": filtered_page_map,
        "confidence": confidence,
        "totalPages": len(pages),
        "logPath": log_path,
        "detectionMethod": detection_method,
        "detectedSections": detected_sections,
    }

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="TOC-based financial statement page filter."
    )

    parser.add_argument("input_pdf", help="Original input PDF path")
    parser.add_argument("--output-pdf", help="Optional filtered PDF output path")
    parser.add_argument("--log", help="Optional JSON filter log path")
    parser.add_argument(
        "--include-notes",
        choices=["none", "first", "full"],
        default="none",
        help="none = do not include notes, first = only notes start page, full = full notes range",
    )
    parser.add_argument(
        "--no-auditor",
        action="store_true",
        help="Exclude independent auditor report pages",
    )

    args = parser.parse_args()

    result = filter_pdf(
        input_pdf_path=args.input_pdf,
        output_pdf_path=args.output_pdf,
        log_path=args.log,
        include_notes=args.include_notes,
        include_auditor=not args.no_auditor,
    )

    print(json.dumps(result, indent=2))