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
    "Upload an annual, quarterly, or other CSE PDF report. "
    "The tool will identify selected pages and optionally generate a filtered PDF."
)

uploaded_file = st.file_uploader(
    "Upload PDF document",
    type=["pdf"],
)

create_filtered_pdf = st.checkbox(
    "Create filtered PDF",
    value=True,
)

include_auditor = st.checkbox(
    "Include Independent Auditor's Report pages",
    value=True,
)

include_notes = st.selectbox(
    "Include Notes to Financial Statements",
    options=["none", "first", "important", "full"],
    index=2,
    help=(
        "none = do not include notes, "
        "first = include only the notes starting page, "
        "important = include only important note topics, "
        "full = include the full notes section if detected"
    ),
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
                include_notes=include_notes,
                include_auditor=include_auditor,
            )

        st.success("Filtering completed.")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Document Type", result["documentType"])
        col2.metric("Total Pages", result["totalPages"])
        col3.metric("Selected Pages", len(result["wantedPages"]))
        col4.metric("Confidence", result["confidence"])

        st.divider()

        st.subheader("Selected Pages JSON Format")
        st.json(
            {
                "pdf_name": input_path.name,
                "selected_pages": result["wantedPages"],
            }
        )

        st.subheader("Selected Pages")
        st.write(result["wantedPages"])

        st.subheader("Removed Pages")
        st.write(result["removedPages"])

        st.subheader("Page Ranges / Reasons")
        st.json(result["pageRanges"])

        st.subheader("Full Result")
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
                    label="Download Filter Log JSON",
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
                "Download and open the filtered PDF to manually verify whether the selected pages are correct."
            )