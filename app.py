from pathlib import Path

import streamlit as st

from filter_pdf import filter_pdf


BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


st.set_page_config(
    page_title="CSE PDF Filter",
    page_icon="📄",
    layout="wide",
)

st.title("CSE PDF Filtering Tool")

st.write(
    "Upload a CSE annual or quarterly report. "
    "The tool will identify target financial statement pages, auditor report, "
    "main table of contents, notes table of contents, investor/shareholder information, "
    "and summary pages."
)

uploaded_file = st.file_uploader(
    "Upload PDF document",
    type=["pdf"],
)

create_filtered_pdf = st.checkbox(
    "Create filtered PDF for manual verification",
    value=True,
)

include_auditor = st.checkbox(
    "Include Independent Auditors' Report",
    value=True,
)

if uploaded_file:
    input_path = INPUT_DIR / uploaded_file.name

    with open(input_path, "wb") as file:
        file.write(uploaded_file.getbuffer())

    st.success(f"Uploaded: {uploaded_file.name}")

    output_pdf_path = OUTPUT_DIR / f"{input_path.stem}_filtered.pdf"
    selected_pages_json_path = OUTPUT_DIR / f"{input_path.stem}_selected_pages.json"
    log_path = LOG_DIR / f"{input_path.stem}_filter_log.json"

    if st.button("Run PDF Filter"):
        with st.spinner("Filtering PDF..."):
            result = filter_pdf(
                input_pdf_path=str(input_path),
                output_pdf_path=str(output_pdf_path) if create_filtered_pdf else None,
                selected_pages_json_path=str(selected_pages_json_path),
                log_path=str(log_path),
                include_auditor=include_auditor,
            )

        st.success("Filtering completed.")

        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric("Document Type", result["documentType"])
        col2.metric("Total Pages", result["totalPages"])
        col3.metric("Selected Pages", len(result["selectedPages"]))
        col4.metric("Confidence", result["confidence"])
        col5.metric("Page Offset", result["pageOffset"])

        st.divider()

        final_json = {
            "pdf_name": result["pdfName"],
            "selected_pages": result["selectedPages"],
            "found_sections": result["foundSections"],
            "missing_required_sections": result["missingRequiredSections"],
            "missing_optional_sections": result["missingOptionalSections"],
            "section_confidence": result["sectionConfidence"],
        }

        st.subheader("Final Selected Pages JSON")
        st.json(final_json)

        st.subheader("Selected Pages")
        st.write(result["selectedPages"])

        st.subheader("Found Sections")
        st.json(result["foundSections"])

        st.subheader("Missing Required Sections")
        if result["missingRequiredSections"]:
            st.error(", ".join(result["missingRequiredSections"]))
        else:
            st.success("No required sections missing.")

        st.subheader("Missing Optional Sections")
        if result["missingOptionalSections"]:
            st.warning(", ".join(result["missingOptionalSections"]))
        else:
            st.success("No optional sections missing.")

        st.subheader("Section Confidence")
        st.json(result["sectionConfidence"])

        st.subheader("Detected TOC Page Numbers")

        st.write("Printed page numbers detected from contents:")
        st.json(result["detectedTocPrintedPages"])

        st.write("Converted and validated PDF page numbers:")
        st.json(result["detectedTocPdfPages"])

        st.subheader("Page Ranges / Reasons")
        st.json(result["pageRanges"])

        with st.expander("Full Result Log"):
            st.json(result)

        st.divider()

        if selected_pages_json_path.exists():
            with open(selected_pages_json_path, "rb") as file:
                st.download_button(
                    label="Download Selected Pages JSON",
                    data=file,
                    file_name=selected_pages_json_path.name,
                    mime="application/json",
                )

        if log_path.exists():
            with open(log_path, "rb") as file:
                st.download_button(
                    label="Download Full Filter Log JSON",
                    data=file,
                    file_name=log_path.name,
                    mime="application/json",
                )

        if create_filtered_pdf and output_pdf_path.exists():
            with open(output_pdf_path, "rb") as file:
                st.download_button(
                    label="Download Filtered PDF",
                    data=file,
                    file_name=output_pdf_path.name,
                    mime="application/pdf",
                )

            st.info(
                "Download and open the filtered PDF to manually verify the selected pages."
            )