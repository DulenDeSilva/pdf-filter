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
    selectedPagesJsonPath: Optional[str]
    filteredPageMap: dict[str, int]
    confidence: float
    totalPages: int
    logPath: Optional[str]
    detectionMethod: str
    detectedSections: dict[str, int]


NotesMode = Literal["none", "first", "important", "full"]


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

LEGAL_DOCUMENT_KEYWORDS = [
    r"\btrust deed\b",
    r"\bdebenture\b",
    r"\bdebentures\b",
    r"\btrustee\b",
    r"\bevent of default\b",
    r"\bdate of allotment\b",
    r"\bdate of redemption\b",
    r"\bredemption\b",
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

TRADER_USEFUL_SECTION_PATTERNS = {
    "financial_highlights": [
        r"\bfinancial highlights\b",
        r"\bperformance highlights\b",
        r"\bkey financial highlights\b",
        r"\bfinancial goals and achievements\b",
    ],
    "investor_information": [
        r"\binvestor information\b",
        r"\binvestor relations\b",
        r"\bshareholder information\b",
        r"\binformation to shareholders\b",
        r"\blargest shareholders\b",
        r"\bmarket information\b",
    ],
    "historical_summary": [
        r"\bfive year summary\b",
        r"\bten year summary\b",
        r"\bfinancial information for last ten years\b",
        r"\bhistorical summary\b",
    ],
    "bank_key_ratios": [
        r"\bcapital adequacy\b",
        r"\bliquidity coverage ratio\b",
        r"\bnet stable funding ratio\b",
        r"\bcommon equity tier 1\b",
        r"\btier 1 capital\b",
        r"\btotal capital ratio\b",
        r"\bimpaired loans\b",
        r"\bnet interest margin\b",
    ],
}

IMPORTANT_NOTE_PATTERNS = {
    "property_plant_and_equipment": [
        r"\bproperty[,]?\s+plant\s+and\s+equipment\b",
        r"\bproperty\s+plant\s+equipment\b",
    ],
    "other_intangible_assets": [
        r"\bother\s+intangible\s+assets\b",
        r"\bintangible\s+assets\b",
    ],
    "financial_assets": [
        r"\bfinancial\s+assets\b",
        r"\bfinancial\s+assets\s+at\s+amortised\s+cost\b",
        r"\bfinancial\s+assets\s+measured\s+at\s+fair\s+value\b",
        r"\bfinancial\s+assets\s+at\s+fair\s+value\b",
    ],
    "investment_property": [
        r"\binvestment\s+property\b",
    ],
    "biological_assets": [
        r"\bbiological\s+assets\b",
        r"\bbearer\s+biological\s+assets\b",
        r"\bconsumable\s+biological\s+assets\b",
        r"\bmature\s+plantations\b",
        r"\bimmature\s+plantations\b",
    ],
    "inventories": [
        r"\binventories\b",
    ],
    "trade_and_other_receivables": [
        r"\btrade\s+and\s+other\s+receivables\b",
        r"\btrade\s+receivables\b",
    ],
    "cash_and_cash_equivalents": [
        r"\bcash\s+and\s+cash\s+equivalents\b",
    ],
    "borrowings": [
        r"\bborrowings\b",
        r"\binterest[-\s]?bearing\s+borrowings\b",
        r"\bloans\s+and\s+borrowings\b",
    ],
    "trade_and_other_payables": [
        r"\btrade\s+and\s+other\s+payables\b",
        r"\btrade\s+payables\b",
    ],
    "revenue": [
        r"\brevenue\b",
        r"\bturnover\b",
    ],
    "finance_income_and_cost": [
        r"\bfinance\s+income\b",
        r"\bfinance\s+cost\b",
        r"\bnet\s+finance\s+cost\b",
    ],
    "taxation": [
        r"\bincome\s+tax\b",
        r"\btax\s+expense\b",
        r"\bdeferred\s+tax\b",
    ],
    "earnings_per_share": [
        r"\bearnings\s+per\s+share\b",
    ],
    "stated_capital": [
        r"\bstated\s+capital\b",
        r"\bshare\s+capital\b",
    ],
    "related_party_transactions": [
        r"\brelated\s+party\s+transactions\b",
        r"\brelated\s+party\s+disclosures\b",
        r"\bamounts\s+due\s+from\s+related\s+parties\b",
        r"\bamounts\s+due\s+to\s+related\s+parties\b",
    ],
    "segment_information": [
        r"\bsegment\s+information\b",
        r"\boperating\s+segments\b",
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
    r"\bnet assets per share\b",
    r"\bmarket capitalisation\b",
    r"\bdividend per share\b",
    r"\breturn on equity\b",
    r"\breturn on assets\b",
    r"\bnet interest margin\b",
]

BANK_REPORT_KEYWORDS = [
    r"\bbank\b",
    r"\bbanking\b",
    r"\bloans and advances\b",
    r"\bdeposits from customers\b",
    r"\bnet interest income\b",
    r"\bcapital adequacy\b",
    r"\bliquidity coverage ratio\b",
    r"\bimpairment allowance\b",
    r"\bstage 1\b",
    r"\bstage 2\b",
    r"\bstage 3\b",
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

    page_ranges.append(
        {
            "start": start,
            "end": end,
            "reason": reason,
        }
    )


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
            if 1 <= value <= 700:
                return value

    for line in candidates:
        match = re.search(
            r"\b(?:annual report|interim report|financial statements).*?\b(\d{1,3})\s*$",
            line,
            re.I,
        )
        if match:
            value = int(match.group(1))
            if 1 <= value <= 700:
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

        has_auditor_heading = (
            count_matches(
                heading_text,
                SECTION_PATTERNS["independent_auditor_report"],
            )
            > 0
        )

        has_notes_heading = (
            count_matches(
                heading_text,
                SECTION_PATTERNS["notes_to_financial_statements"],
            )
            > 0
        )

        trader_useful_match_count = sum(
            count_matches(heading_text, patterns)
            for patterns in TRADER_USEFUL_SECTION_PATTERNS.values()
        )

        has_trader_useful_heading = trader_useful_match_count > 0

        is_table_like = (
            (table_count >= 1 and number_count >= 15)
            or (number_count >= 45 and line_count >= 20 and sentence_count <= 10)
            or (financial_label_count >= 5 and number_count >= 20)
        )

        is_financial_summary_like = (
            has_trader_useful_heading
            and number_count >= 15
            and financial_label_count >= 2
        )

        is_paragraph_heavy = (
            not has_statement_heading
            and not has_auditor_heading
            and not has_notes_heading
            and not is_toc
            and not is_financial_summary_like
            and (
                sentence_count >= 12
                or (line_count >= 30 and financial_label_count < 4)
            )
        )

        pages.append(
            {
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
                "traderUsefulMatchCount": trader_useful_match_count,
                "isToc": is_toc,
                "isUnwanted": is_unwanted,
                "hasStatementHeading": has_statement_heading,
                "hasAuditorHeading": has_auditor_heading,
                "hasNotesHeading": has_notes_heading,
                "hasTraderUsefulHeading": has_trader_useful_heading,
                "isTableLike": is_table_like,
                "isFinancialSummaryLike": is_financial_summary_like,
                "isParagraphHeavy": is_paragraph_heavy,
                "textLength": len(normalized),
            }
        )

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
        if re.search(pattern, first_pages_text)
        or re.search(pattern, broader_text_sample)
    )

    quarterly_score = sum(
        1
        for pattern in QUARTERLY_KEYWORDS
        if re.search(pattern, first_pages_text)
        or re.search(pattern, broader_text_sample)
    )

    legal_score = sum(
        1
        for pattern in LEGAL_DOCUMENT_KEYWORDS
        if re.search(pattern, first_pages_text)
        or re.search(pattern, broader_text_sample)
    )

    full_text_length = sum(page["textLength"] for page in pages)
    avg_text_length = full_text_length / max(total_pages, 1)

    if avg_text_length < 80:
        return "scanned_unknown", "ocr_required_filter", 0.45

    if legal_score >= 4 and annual_score < 2 and quarterly_score < 2:
        return "legal_document", "unsupported_document_filter", 0.95

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
        "investor relations",
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

    combined_patterns = {
        **SECTION_PATTERNS,
        **TRADER_USEFUL_SECTION_PATTERNS,
    }

    for page in toc_pages:
        full_normalized_text = normalize_text(page["text"])
        financial_block = extract_financial_block_from_toc_text(page["text"])

        for section_key, patterns in combined_patterns.items():
            if section_key in detected:
                continue

            search_blocks = [financial_block]

            if section_key in TRADER_USEFUL_SECTION_PATTERNS:
                search_blocks.append(full_normalized_text)

            for block in search_blocks:
                for pattern in patterns:
                    regex = pattern + r".{0,140}?\b(\d{1,3})\b"
                    match = re.search(regex, block)

                    if match:
                        value = int(match.group(1))

                        if 1 <= value <= 700:
                            detected[section_key] = value
                            break

                if section_key in detected:
                    break

    return detected


def find_notes_end_page(pages: list[dict], notes_start_page: int) -> int:
    for page in pages:
        page_number = page["pageNumber"]

        if page_number <= notes_start_page:
            continue

        if has_pattern(page["headingText"], END_SECTION_PATTERNS):
            return page_number - 1

    return len(pages)


def detect_important_note_topic(text: str) -> Optional[str]:
    normalized = normalize_text(text)

    for topic, patterns in IMPORTANT_NOTE_PATTERNS.items():
        if has_pattern(normalized, patterns):
            return topic

    return None


def looks_like_note_heading(text: str) -> bool:
    normalized = normalize_text(text)

    return bool(
        re.search(
            r"\b\d{1,2}(\.\d{1,2})?\s+([a-z][a-z,&()/\-\s]{3,})",
            normalized,
        )
    )


def detect_note_heading_title(text: str) -> Optional[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidate_text = " ".join(lines[:10])
    normalized = normalize_text(candidate_text)

    match = re.search(
        r"\b\d{1,2}(\.\d{1,2})?\s+([a-z][a-z,&()/\-\s]{3,120})",
        normalized,
    )

    if match:
        return match.group(2).strip()

    return None


def detect_all_note_headings(
    pages: list[dict],
    notes_start_page: int,
    notes_end_page: int,
) -> list[dict]:
    note_headings = []

    for page in pages:
        page_number = page["pageNumber"]

        if page_number < notes_start_page or page_number > notes_end_page:
            continue

        heading_source = page["headingText"]
        title = detect_note_heading_title(page["text"])
        topic = detect_important_note_topic(heading_source)

        if title or topic or looks_like_note_heading(heading_source):
            note_headings.append(
                {
                    "page": page_number,
                    "title": title,
                    "topic": topic,
                    "important": topic is not None,
                }
            )

    note_headings = sorted(note_headings, key=lambda item: item["page"])

    deduped = []
    seen_pages = set()

    for heading in note_headings:
        if heading["page"] in seen_pages:
            continue

        deduped.append(heading)
        seen_pages.add(heading["page"])

    return deduped


def detect_important_note_pages(
    pages: list[dict],
    notes_start_page: int,
    notes_end_page: int,
) -> tuple[set[int], dict[str, list[int]]]:
    note_headings = detect_all_note_headings(
        pages=pages,
        notes_start_page=notes_start_page,
        notes_end_page=notes_end_page,
    )

    selected_pages: set[int] = set()
    detected_important_notes: dict[str, list[int]] = {}

    for index, note in enumerate(note_headings):
        if not note["important"]:
            continue

        start_page = note["page"]

        if index + 1 < len(note_headings):
            end_page = note_headings[index + 1]["page"] - 1
        else:
            end_page = start_page

        start_page, end_page = clamp_range(
            start_page,
            end_page,
            len(pages),
        )

        selected_range = list(range(start_page, end_page + 1))

        for page_number in selected_range:
            selected_pages.add(page_number)

        topic = note["topic"] or "unknown_important_note"
        detected_important_notes.setdefault(topic, [])
        detected_important_notes[topic].extend(selected_range)

    return selected_pages, detected_important_notes


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

        if page["hasTraderUsefulHeading"] and (
            page["isFinancialSummaryLike"] or page["isTableLike"]
        ):
            cleaned.add(page_number)
            continue

        if detect_important_note_topic(page["headingText"]):
            cleaned.add(page_number)
            continue

        if page["isUnwanted"]:
            continue

        if page["isParagraphHeavy"]:
            continue

        if page["isTableLike"] and page["financialLabelCount"] >= 2:
            cleaned.add(page_number)

    return cleaned


def toc_based_filter(
    pages: list[dict],
    include_notes: NotesMode = "none",
    include_auditor: bool = True,
) -> tuple[list[int], list[PageRange], float, dict[str, int]]:
    total_pages = len(pages)
    wanted_pages: set[int] = set()
    page_ranges: list[PageRange] = []

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

        for later_key, later_page in ordered_sections[index + 1 :]:
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
                add_page_range(
                    wanted_pages,
                    page_ranges,
                    start_page,
                    start_page,
                    total_pages,
                    "notes_to_financial_statements_first_page_from_toc",
                )

            elif include_notes == "full":
                end_page = find_notes_end_page(pages, start_page)

                add_page_range(
                    wanted_pages,
                    page_ranges,
                    start_page,
                    end_page,
                    total_pages,
                    "notes_to_financial_statements_full_from_toc",
                )

            elif include_notes == "important":
                notes_end_page = find_notes_end_page(pages, start_page)

                important_note_pages, detected_important_notes = detect_important_note_pages(
                    pages=pages,
                    notes_start_page=start_page,
                    notes_end_page=notes_end_page,
                )

                for page_number in sorted(important_note_pages):
                    wanted_pages.add(page_number)

                for topic, topic_pages in detected_important_notes.items():
                    page_ranges.append(
                        {
                            "start": min(topic_pages),
                            "end": max(topic_pages),
                            "reason": f"important_note_{topic}",
                        }
                    )

        elif section_key in TRADER_USEFUL_SECTION_PATTERNS:
            if next_start:
                end_page = min(next_start - 1, start_page + 2)
            else:
                end_page = start_page

            add_page_range(
                wanted_pages,
                page_ranges,
                start_page,
                end_page,
                total_pages,
                f"{section_key}_from_toc",
            )

    cleaned_pages = clean_selected_pages(
        pages,
        wanted_pages,
        keep_toc=False,
        keep_auditor=include_auditor,
    )

    confidence = 0.93 if len(cleaned_pages) >= 4 else 0.65

    return sorted(cleaned_pages), page_ranges, confidence, detected_pdf_pages


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
                add_page_range(
                    wanted_pages,
                    page_ranges,
                    page_number,
                    page_number,
                    total_pages,
                    "notes_first_page_heading_fallback",
                )

            elif include_notes == "full":
                end_page = find_notes_end_page(pages, page_number)

                add_page_range(
                    wanted_pages,
                    page_ranges,
                    page_number,
                    end_page,
                    total_pages,
                    "notes_full_heading_fallback",
                )

            elif include_notes == "important":
                notes_end_page = find_notes_end_page(pages, page_number)

                important_note_pages, detected_important_notes = detect_important_note_pages(
                    pages=pages,
                    notes_start_page=page_number,
                    notes_end_page=notes_end_page,
                )

                for selected_page in sorted(important_note_pages):
                    wanted_pages.add(selected_page)

                for topic, topic_pages in detected_important_notes.items():
                    page_ranges.append(
                        {
                            "start": min(topic_pages),
                            "end": max(topic_pages),
                            "reason": f"important_note_{topic}",
                        }
                    )

            detected["notes_to_financial_statements"] = page_number
            continue

        if page["hasTraderUsefulHeading"] and (
            page["isFinancialSummaryLike"] or page["isTableLike"]
        ):
            add_page_range(
                wanted_pages,
                page_ranges,
                page_number,
                page_number,
                total_pages,
                "trader_useful_heading_fallback",
            )
            detected[f"trader_useful_page_{page_number}"] = page_number
            continue

    cleaned_pages = clean_selected_pages(
        pages,
        wanted_pages,
        keep_toc=False,
        keep_auditor=include_auditor,
    )

    confidence = 0.75 if len(cleaned_pages) >= 3 else 0.45

    return sorted(cleaned_pages), page_ranges, confidence, detected


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


def create_selected_pages_json(
    input_pdf_path: str,
    selected_pages_json_path: str,
    wanted_pages: list[int],
) -> None:
    data = {
        "pdf_name": Path(input_pdf_path).name,
        "selected_pages": wanted_pages,
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
    include_notes: NotesMode = "important",
    include_auditor: bool = True,
) -> FilterResult:
    pages = read_pdf_pages(input_pdf_path)

    document_type, filter_profile, type_confidence = detect_document_type(pages)

    if document_type in ["annual_report", "quarterly_report", "other_report"]:
        (
            wanted_pages,
            page_ranges,
            filter_confidence,
            detection_method,
            detected_sections,
        ) = filter_report(
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

    wanted_pages = sorted(set(wanted_pages))

    all_pages = set(range(1, len(pages) + 1))
    removed_pages = sorted(all_pages - set(wanted_pages))

    filtered_page_map: dict[str, int] = {}

    if output_pdf_path and wanted_pages:
        filtered_page_map = create_filtered_pdf(
            input_pdf_path=input_pdf_path,
            output_pdf_path=output_pdf_path,
            wanted_pages=wanted_pages,
        )

    if selected_pages_json_path:
        create_selected_pages_json(
            input_pdf_path=input_pdf_path,
            selected_pages_json_path=selected_pages_json_path,
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
        "selectedPagesJsonPath": selected_pages_json_path,
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
        description="CSE financial and trader-useful page filter."
    )

    parser.add_argument("input_pdf", help="Original input PDF path")
    parser.add_argument("--output-pdf", help="Optional filtered PDF output path")
    parser.add_argument("--selected-pages-json", help="Simple selected pages JSON path")
    parser.add_argument("--log", help="Optional JSON filter log path")
    parser.add_argument(
        "--include-notes",
        choices=["none", "first", "important", "full"],
        default="important",
        help=(
            "none = do not include notes, "
            "first = only notes start page, "
            "important = only important note topics, "
            "full = full notes range"
        ),
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
        selected_pages_json_path=args.selected_pages_json,
        log_path=args.log,
        include_notes=args.include_notes,
        include_auditor=not args.no_auditor,
    )

    print(json.dumps(result, indent=2))