import json
from pathlib import Path

from filter_pdf import filter_pdf


BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
LABELS_DIR = BASE_DIR / "labels"

GROUND_TRUTH_PATH = LABELS_DIR / "ground_truth_pages.json"

OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


def load_ground_truth() -> list[dict]:
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(
            f"Ground truth file not found: {GROUND_TRUTH_PATH}"
        )

    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def calculate_metrics(expected_pages: set[int], selected_pages: set[int]) -> dict:
    true_positives = expected_pages & selected_pages
    missed_pages = expected_pages - selected_pages
    extra_pages = selected_pages - expected_pages

    precision = len(true_positives) / len(selected_pages) if selected_pages else 0
    recall = len(true_positives) / len(expected_pages) if expected_pages else 0

    f1_score = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0
    )

    return {
        "expected_count": len(expected_pages),
        "selected_count": len(selected_pages),
        "correct_count": len(true_positives),
        "missed_count": len(missed_pages),
        "extra_count": len(extra_pages),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1_score": round(f1_score, 3),
        "missed_pages": sorted(missed_pages),
        "extra_pages": sorted(extra_pages),
    }


def evaluate_one_pdf(item: dict) -> dict:
    pdf_name = item["pdf_name"]
    expected_pages = set(item["expected_pages"])

    input_pdf_path = INPUT_DIR / pdf_name

    if not input_pdf_path.exists():
        return {
            "pdf_name": pdf_name,
            "error": f"PDF not found in input folder: {input_pdf_path}",
        }

    output_pdf_path = OUTPUT_DIR / f"{input_pdf_path.stem}_filtered.pdf"
    selected_json_path = OUTPUT_DIR / f"{input_pdf_path.stem}_selected_pages.json"
    log_path = LOG_DIR / f"{input_pdf_path.stem}_filter_log.json"

    result = filter_pdf(
        input_pdf_path=str(input_pdf_path),
        output_pdf_path=str(output_pdf_path),
        selected_pages_json_path=str(selected_json_path),
        log_path=str(log_path),
        include_notes="important",
        include_auditor=True,
    )

    selected_pages = set(result["wantedPages"])
    metrics = calculate_metrics(expected_pages, selected_pages)

    return {
        "pdf_name": pdf_name,
        "company_type": item.get("company_type"),
        "document_type": result["documentType"],
        "filter_profile": result["filterProfile"],
        "is_bank_report": result["isBankReport"],
        **metrics,
    }


def main() -> None:
    ground_truth = load_ground_truth()

    all_results = []

    print("\nPDF Filter Evaluation")
    print("=" * 80)

    for item in ground_truth:
        evaluation = evaluate_one_pdf(item)
        all_results.append(evaluation)

        print(f"\nPDF: {evaluation['pdf_name']}")

        if "error" in evaluation:
            print(f"ERROR: {evaluation['error']}")
            continue

        print(f"Company Type: {evaluation['company_type']}")
        print(f"Document Type: {evaluation['document_type']}")
        print(f"Filter Profile: {evaluation['filter_profile']}")
        print(f"Is Bank Report: {evaluation['is_bank_report']}")
        print(f"Expected Pages: {evaluation['expected_count']}")
        print(f"Selected Pages: {evaluation['selected_count']}")
        print(f"Correct Pages: {evaluation['correct_count']}")
        print(f"Missed Pages: {evaluation['missed_count']}")
        print(f"Extra Pages: {evaluation['extra_count']}")
        print(f"Precision: {evaluation['precision']}")
        print(f"Recall: {evaluation['recall']}")
        print(f"F1 Score: {evaluation['f1_score']}")

        if evaluation["missed_pages"]:
            print(f"Missed: {evaluation['missed_pages']}")

        if evaluation["extra_pages"]:
            print(f"Extra: {evaluation['extra_pages']}")

    evaluation_output_path = OUTPUT_DIR / "evaluation_results.json"

    with open(evaluation_output_path, "w", encoding="utf-8") as file:
        json.dump(all_results, file, indent=2)

    print("\n" + "=" * 80)
    print(f"Saved evaluation results to: {evaluation_output_path}")


if __name__ == "__main__":
    main()