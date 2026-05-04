import fitz
import re
import json
from pathlib import Path
from typing import Optional, TypedDict


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


# --------------------------------------------------
# Document type detection patterns
# --------------------------------------------------

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
    r"\bfor the three months ended\b",
    r"\bfor the six months ended\b",
    r"\bfor the nine months ended\b",
    r"\bcondensed statement\b",
    r"\bunaudited\b",
]


# --------------------------------------------------
# Main financial statement patterns
# --------------------------------------------------

FINANCIAL_START_PATTERNS = [
    r"\bindependent auditor[’']?s? report\b",
    r"\bindependent auditors[’']? report\b",
    r"\bfinancial information\b",
    r"\bstatement of profit or loss\b",
    r"\bstatement of comprehensive income\b",
    r"\bstatement of profit or loss and other comprehensive income\b",
    r"\bincome statement\b",
    r"\bstatement of financial position\b",
    r"\bbalance sheet\b",
]

FINANCIAL_SECTION_PATTERNS = [
    r"\bindependent auditor\b",
    r"\bindependent auditors\b",
    r"\bbasis for opinion\b",
    r"\bkey audit matters\b",

    r"\bstatement of profit or loss\b",
    r"\bstatement of comprehensive income\b",
    r"\bstatement of profit or loss and other comprehensive income\b",
    r"\bincome statement\b",

    r"\bstatement of financial position\b",
    r"\bbalance sheet\b",

    r"\bstatement of cash flows\b",
    r"\bcash flow statement\b",
    r"\bcash flows from operating activities\b",

    r"\bstatement of changes in equity\b",
    r"\bchanges in equity\b",

    r"\bnotes to the financial statements\b",
    r"\bnotes to financial statements\b",
    r"\bsignificant accounting policies\b",
    r"\bmaterial accounting policies\b",
    r"\bbasis of preparation\b",
]

# Extra wanted sections found from the annual/quarterly samples.
# These pages are not always part of the audited statements,
# but your project wants them included.
WANTED_SECTION_PATTERNS = [
    r"\bfinancial highlights\b",
    r"\bperformance highlights\b",
    r"\bfinancial review\b",
    r"\brisk management\b",
    r"\bfinancial commentary\b",
    r"\boperational review\b",
    r"\bperformance review\b",
    r"\bsegment information\b",
]

# Quarterly-specific wanted sections. Quarterly reports are kept fully,
# but these keywords help with classification and future strict mode.
QUARTERLY_WANTED_SECTION_PATTERNS = [
    r"\bcontents\b",
    r"\bcontent\b",
    r"\boperational review\b",
    r"\bfinancial highlights\b",
    r"\bstatement of profit or loss\b",
    r"\bstatement of profit or loss and other comprehensive income\b",
    r"\bstatement of financial position\b",
    r"\bstatement of changes in equity\b",
    r"\bstatement of cash flows\b",
    r"\bnotes to the financial statements\b",
]

NOTES_START_PATTERNS = [
    r"\bnotes to the financial statements\b",
    r"\bnotes to financial statements\b",
    r"\bsignificant accounting policies\b",
    r"\bmaterial accounting policies\b",
    r"\bbasis of preparation\b",
]


# --------------------------------------------------
# End and unwanted patterns
# --------------------------------------------------

END_SECTION_PATTERNS = [
    r"\bshareholder information\b",
    r"\binvestor information\b",
    r"\binformation to shareholders\b",
    r"\bnotice of annual general meeting\b",
    r"\bnotice of meeting\b",
    r"\bform of proxy\b",
    r"\bproxy form\b",
    r"\bcorporate directory\b",
    r"\bten year summary\b",
    r"\bfive year summary\b",
    r"\bdistribution schedule\b",
    r"\bbranch network\b",
    r"\bbranches\b",
    r"\bglossary\b",
]

UNWANTED_PATTERNS = [
    r"\btable of contents\b",
    r"\bcontents\b",
    r"\babout us\b",

    r"\bchairman[’']?s review\b",
    r"\bchairman[’']?s message\b",
    r"\bchairperson[’']?s message\b",
    r"\bdirector/ceo[’']?s review\b",
    r"\bchief executive officer\b",
    r"\bceo[’']?s review\b",
    r"\bboard of directors\b",
    r"\bboard profiles\b",
    r"\bcorporate governance\b",
    r"\bsustainability\b",
    r"\bmanagement discussion\b",
    r"\bawards\b",
    r"\bcompany profile\b",
    r"\bour vision\b",
    r"\bour mission\b",
    r"\btransportation\b",
]


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def normalize_text(text: str) -> str:
    """
    Normalize PDF text before matching keywords.
    """
    text = text.replace("’", "'")
    text = text.replace("‘", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    return re.sub(r"\s+", " ", text.lower()).strip()


def get_heading_text(text: str, max_chars: int = 900) -> str:
    """
    Uses the first part of the page as an approximate heading area.
    This helps avoid treating footer/body mentions as section starts/ends.
    """
    normalized = normalize_text(text)
    return normalized[:max_chars]


def has_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def matched_patterns(text: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text)]


def count_numbers(text: str) -> int:
    return len(re.findall(r"\(?\d[\d,\.]*\)?", text))


def read_pdf_pages(input_pdf_path: str) -> list[dict]:
    doc = fitz.open(input_pdf_path)
    pages = []

    for index, page in enumerate(doc):
        page_number = index + 1
        text = page.get_text("text") or ""
        normalized = normalize_text(text)
        heading_text = get_heading_text(text)

        pages.append({
            "pageNumber": page_number,
            "text": text,
            "normalizedText": normalized,
            "headingText": heading_text,
            "numberCount": count_numbers(normalized),
            "textLength": len(normalized),
        })

    doc.close()
    return pages


# --------------------------------------------------
# Document type detection
# --------------------------------------------------

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

    quarterly_wanted_score = sum(
        1
        for pattern in QUARTERLY_WANTED_SECTION_PATTERNS
        if re.search(pattern, first_pages_text) or re.search(pattern, broader_text_sample)
    )

    full_text_length = sum(page["textLength"] for page in pages)
    avg_text_length = full_text_length / max(total_pages, 1)

    if avg_text_length < 80:
        return "scanned_unknown", "ocr_required_filter", 0.45

    # Quarterly reports are usually short and contain interim/period keywords.
    if total_pages <= 80 and (quarterly_score >= 1 or quarterly_wanted_score >= 3):
        return "quarterly_report", "quarterly_report_filter", 0.9

    # Annual reports are usually larger, but can also be detected by annual keywords.
    if annual_score >= 2 or total_pages > 80:
        return "annual_report", "annual_report_filter", 0.88

    return "other_report", "other_report_classifier", 0.65


# --------------------------------------------------
# Page classification
# --------------------------------------------------

def classify_page(page: dict) -> dict:
    text = page["normalizedText"]
    heading_text = page["headingText"]

    score = 0
    matched = []

    financial_matches = matched_patterns(text, FINANCIAL_SECTION_PATTERNS)
    wanted_matches = matched_patterns(heading_text, WANTED_SECTION_PATTERNS)
    unwanted_matches = matched_patterns(heading_text, UNWANTED_PATTERNS)

    if financial_matches:
        score += 15 * len(financial_matches)
        matched.extend(financial_matches)

    if wanted_matches:
        score += 12 * len(wanted_matches)
        matched.extend(wanted_matches)

    if page["numberCount"] > 25:
        score += 5

    if page["textLength"] < 100:
        score -= 5

    # Unwanted terms only affect classification when they appear near heading area.
    if unwanted_matches:
        score -= 10 * len(unwanted_matches)
        matched.extend(unwanted_matches)

    if score >= 15:
        label = "wanted"
    elif score >= 5:
        label = "maybe_wanted"
    else:
        label = "unwanted"

    return {
        **page,
        "score": score,
        "label": label,
        "matchedPatterns": matched,
    }


# --------------------------------------------------
# Annual report filtering
# --------------------------------------------------

def find_annual_financial_range(
    classified_pages: list[dict],
) -> tuple[Optional[int], Optional[int]]:
    start_page = None
    end_page = None
    notes_started = False

    # Start only from heading area.
    # Do not use full_text here, because table of contents and body text
    # can mention financial statements and cause early false starts.
    for page in classified_pages:
        heading_text = page["headingText"]

        if has_pattern(heading_text, FINANCIAL_START_PATTERNS):
            start_page = page["pageNumber"]
            break

    if start_page is None:
        return None, None

    for page in classified_pages:
        page_number = page["pageNumber"]
        heading_text = page["headingText"]
        full_text = page["normalizedText"]

        if page_number < start_page:
            continue

        if has_pattern(full_text, NOTES_START_PATTERNS):
            notes_started = True

        # End only after notes have started.
        # End markers are checked only in heading area.
        if notes_started and has_pattern(heading_text, END_SECTION_PATTERNS):
            end_page = page_number - 1
            break

    if end_page is None:
        end_page = classified_pages[-1]["pageNumber"]

    return start_page, end_page


def collect_extra_wanted_pages(classified_pages: list[dict]) -> set[int]:
    """
    Collect pages like Financial Highlights, Risk Management,
    Operational Review, Segment Information, etc.
    These can appear outside the main financial statement range.
    """
    total_pages = len(classified_pages)
    extra_pages: set[int] = set()

    for page in classified_pages:
        page_number = page["pageNumber"]
        heading_text = page["headingText"]

        if has_pattern(heading_text, WANTED_SECTION_PATTERNS):
            start = max(1, page_number)
            end = min(total_pages, page_number + 2)

            for p in range(start, end + 1):
                extra_pages.add(p)

    return extra_pages


def filter_annual_report(
    classified_pages: list[dict],
) -> tuple[list[int], list[PageRange], float]:
    total_pages = len(classified_pages)
    wanted_pages: set[int] = set()
    page_ranges: list[PageRange] = []

    start_page, end_page = find_annual_financial_range(classified_pages)

    # Main rule: keep full audited financial section.
    if start_page and end_page:
        for page_number in range(start_page, end_page + 1):
            wanted_pages.add(page_number)

        page_ranges.append({
            "start": start_page,
            "end": end_page,
            "reason": "financial_statement_section",
        })

    # Extra wanted pages requested by project team.
    extra_wanted_pages = collect_extra_wanted_pages(classified_pages)

    if extra_wanted_pages:
        wanted_pages.update(extra_wanted_pages)
        page_ranges.append({
            "start": min(extra_wanted_pages),
            "end": max(extra_wanted_pages),
            "reason": "extra_wanted_sections",
        })

    # Backup rule: keep pages with strong financial headings and nearby continuation pages.
    for page in classified_pages:
        text = page["normalizedText"]
        page_number = page["pageNumber"]

        if has_pattern(text, FINANCIAL_SECTION_PATTERNS):
            buffer_before = 1
            buffer_after = 3

            start = max(1, page_number - buffer_before)
            end = min(total_pages, page_number + buffer_after)

            for p in range(start, end + 1):
                wanted_pages.add(p)

    # If no range found, fallback to wanted/maybe pages.
    if not wanted_pages:
        for page in classified_pages:
            if page["label"] in ["wanted", "maybe_wanted"]:
                page_number = page["pageNumber"]

                start = max(1, page_number - 1)
                end = min(total_pages, page_number + 2)

                for p in range(start, end + 1):
                    wanted_pages.add(p)

    confidence = 0.92 if start_page and end_page else 0.65

    return sorted(wanted_pages), page_ranges, confidence


# --------------------------------------------------
# Quarterly report filtering
# --------------------------------------------------

def filter_quarterly_report(
    classified_pages: list[dict],
) -> tuple[list[int], list[PageRange], float]:
    total_pages = len(classified_pages)

    # Quarterly/interim reports are usually short and mostly financial.
    # Based on the sample quarterly reports, safest rule is to keep all pages.
    wanted_pages = list(range(1, total_pages + 1))

    page_ranges = [{
        "start": 1,
        "end": total_pages,
        "reason": "quarterly_reports_are_short_keep_all",
    }]

    return wanted_pages, page_ranges, 0.9


# --------------------------------------------------
# Other report filtering
# --------------------------------------------------

def filter_other_report(
    classified_pages: list[dict],
) -> tuple[list[int], list[PageRange], float]:
    wanted_pages: set[int] = set()
    total_pages = len(classified_pages)

    for page in classified_pages:
        text = page["normalizedText"]
        heading_text = page["headingText"]
        page_number = page["pageNumber"]

        if has_pattern(text, FINANCIAL_SECTION_PATTERNS) or has_pattern(heading_text, WANTED_SECTION_PATTERNS):
            start = max(1, page_number - 1)
            end = min(total_pages, page_number + 1)

            for p in range(start, end + 1):
                wanted_pages.add(p)

    if wanted_pages:
        return sorted(wanted_pages), [{
            "start": min(wanted_pages),
            "end": max(wanted_pages),
            "reason": "financial_or_wanted_keywords_found_in_other_report",
        }], 0.65

    return [], [], 0.5


# --------------------------------------------------
# Filtered PDF creation
# --------------------------------------------------

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


# --------------------------------------------------
# Main function
# --------------------------------------------------

def filter_pdf(
    input_pdf_path: str,
    output_pdf_path: Optional[str] = None,
    log_path: Optional[str] = None,
) -> FilterResult:
    pages = read_pdf_pages(input_pdf_path)
    classified_pages = [classify_page(page) for page in pages]

    document_type, filter_profile, type_confidence = detect_document_type(classified_pages)

    if document_type == "annual_report":
        wanted_pages, page_ranges, filter_confidence = filter_annual_report(classified_pages)
    elif document_type == "quarterly_report":
        wanted_pages, page_ranges, filter_confidence = filter_quarterly_report(classified_pages)
    elif document_type == "other_report":
        wanted_pages, page_ranges, filter_confidence = filter_other_report(classified_pages)
    else:
        wanted_pages = []
        page_ranges = []
        filter_confidence = 0.4

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
    }

    # Clean log only.
    # No page-by-page scores in normal JSON output.
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

    return result


# --------------------------------------------------
# CLI
# --------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Filter wanted pages from CSE PDF documents."
    )

    parser.add_argument("input_pdf", help="Original input PDF path")
    parser.add_argument("--output-pdf", help="Optional filtered PDF output path")
    parser.add_argument("--log", help="Optional JSON filter log path")

    args = parser.parse_args()

    result = filter_pdf(
        input_pdf_path=args.input_pdf,
        output_pdf_path=args.output_pdf,
        log_path=args.log,
    )

    print(json.dumps(result, indent=2))