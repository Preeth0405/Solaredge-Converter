from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st


def prepare_times(values, naive_timezone):
    """Normalise offset-aware and local timestamps to a UTC index."""
    def parse(value):
        try:
            timestamp = pd.to_datetime(value, dayfirst=True, format="mixed", errors="coerce")
            if pd.isna(timestamp):
                return pd.NaT
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize(
                    naive_timezone, ambiguous="NaT", nonexistent="NaT"
                )
            return timestamp.tz_convert("UTC") if not pd.isna(timestamp) else pd.NaT
        except (ValueError, TypeError, OverflowError):
            return pd.NaT

    return pd.to_datetime(values.map(parse), utc=True)


def aggregate_data(df, time_col, freq, naive_timezone, output_timezone):
    df = df.copy()
    df[time_col] = prepare_times(df[time_col], naive_timezone)
    invalid_rows = int(df[time_col].isna().sum())
    df = df.dropna(subset=[time_col]).set_index(time_col).sort_index()
    df.index = df.index.tz_convert(output_timezone)
    numeric = df.apply(pd.to_numeric, errors="coerce")
    ignored = [col for col in numeric.columns if not numeric[col].notna().any()]
    numeric = numeric.drop(columns=ignored)
    if numeric.empty:
        raise ValueError("No valid timestamps and numeric data were found.")
    # Remove identical overlapping samples, including their timestamp.
    records = numeric.reset_index()
    original_count = len(records)
    records = records.drop_duplicates()
    duplicates_removed = original_count - len(records)
    if records[time_col].duplicated().any():
        conflicts = records.loc[records[time_col].duplicated(keep=False), time_col].nunique()
        raise ValueError(
            f"Found {conflicts} overlapping timestamps with different readings. "
            "Remove the overlapping files/sheets or resolve those readings before combining."
        )
    numeric = records.set_index(time_col).sort_index()
    rules = {}
    for col in numeric.columns:
        label = str(col).lower()
        rules[col] = (lambda values: values.sum(min_count=1)) if "energy" in label else "mean"
    return numeric.resample(freq).agg(rules), invalid_rows, ignored, duplicates_removed


def combine_sources(sources, time_col):
    missing = [name for name, frame in sources if time_col not in frame.columns]
    if missing:
        raise ValueError(f"Time column '{time_col}' is missing in: " + ", ".join(missing))
    return pd.concat([frame for _, frame in sources], ignore_index=True, sort=False)


def excel_bytes(df):
    export = df.copy()
    # Keep the displayed local clock time; Excel cannot store timezone metadata.
    labels = export.index.strftime("%z")
    export.index = export.index.tz_localize(None)
    export.insert(0, "UTC offset", labels)
    buffer = BytesIO()
    export.to_excel(buffer, engine="openpyxl", sheet_name="Aggregated Data")
    return buffer.getvalue()


def main():
    st.set_page_config(layout="wide")
    with st.sidebar:
        logo = Path(__file__).with_name("image.png")
        if logo.exists():
            st.image(str(logo), width=150)
        st.header("🔒 Secure Login")
        if "authenticated" not in st.session_state:
            st.session_state.authenticated = False
        if not st.session_state.authenticated:
            password = st.text_input("Enter password", type="password")
            if password == "pushpower123":
                st.session_state.authenticated = True
                st.rerun()
        else:
            st.success("Logged in")
            if st.button("⏻ Logout"):
                st.session_state.authenticated = False
                st.rerun()

    if not st.session_state.authenticated:
        st.warning("Please enter the correct password to access the app.")
        st.stop()

    st.title("⏱ Data Aggregation Tool")
    st.sidebar.header("ℹ️ How to Use")
    st.sidebar.markdown("""
1. Upload one or more monthly Excel or CSV files.
2. Select the data sheets, time column and aggregation interval.
3. Set the timezone for timestamps that do not include an offset.
4. Choose the timezone to use for aggregation and export.
5. Download all selected months as one Excel file.
""")
    st.sidebar.header("📖 Glossary")
    st.sidebar.markdown("""
- **Irradiance, power and temperature:** averaged over each interval.
- **Interval energy:** summed over each interval.
- **Cumulative energy counters:** convert to interval energy before uploading.
- **Other numeric columns:** averaged by default.
- **Missing data:** remains blank when an entire interval has no readings.
""")

    uploaded_files = st.file_uploader(
        "Upload monthly Excel/CSV files", type=["xlsx", "csv"], accept_multiple_files=True
    )
    if not uploaded_files:
        return
    sources = []
    for file_number, uploaded_file in enumerate(uploaded_files):
        try:
            uploaded_file.seek(0)
            if uploaded_file.name.lower().endswith(".csv"):
                sources.append((uploaded_file.name, pd.read_csv(uploaded_file)))
            else:
                book = pd.ExcelFile(uploaded_file)
                selected_sheets = st.multiselect(
                    f"Data sheets in {uploaded_file.name}",
                    options=book.sheet_names,
                    default=book.sheet_names,
                    key=f"sheets_{file_number}_{uploaded_file.name}",
                    help="Select only sheets containing the monthly raw data. Deselect summary or instruction sheets.",
                )
                for sheet in selected_sheets:
                    sources.append((f"{uploaded_file.name} / {sheet}", book.parse(sheet)))
        except Exception as exc:
            st.error(f"Could not read {uploaded_file.name}: {exc}")
            st.stop()
    sources = [(name, frame) for name, frame in sources if not frame.empty]
    if not sources:
        st.warning("Select at least one sheet containing data.")
        st.stop()

    st.subheader("Selected Data Sources")
    st.dataframe(pd.DataFrame([
        {"File / sheet": name, "Rows": len(frame)} for name, frame in sources
    ]), width="stretch", hide_index=True)
    common_columns = [col for col in sources[0][1].columns if all(col in frame.columns for _, frame in sources)]
    if not common_columns:
        st.error("The selected data sheets do not share a time column. Use matching column headings or deselect unrelated sheets.")
        st.stop()
    time_col = st.selectbox("Select Time Column", common_columns)
    df = combine_sources(sources, time_col)

    st.subheader("Raw Data Preview")
    st.dataframe(df.head(), width="stretch")
    if df.empty:
        st.warning("The uploaded file is empty.")
        st.stop()
    freq = st.selectbox("Select aggregation interval", ["30min", "1h", "2h", "1D"])
    naive_timezone = st.selectbox("Timezone for timestamps without an offset", ["Europe/London", "UTC"])
    output_timezone = st.selectbox("Aggregation and export timezone", ["Europe/London", "UTC"])
    st.caption("Timestamps with Z or a UTC offset retain their actual instant. Excel includes a UTC offset column to distinguish repeated clock times when daylight saving ends.")

    try:
        result, invalid_rows, ignored, duplicates_removed = aggregate_data(df, time_col, freq, naive_timezone, output_timezone)
        if invalid_rows:
            st.warning(f"Skipped {invalid_rows} rows with invalid or ambiguous timestamps.")
        if ignored:
            st.info("Columns without numeric readings were omitted: " + ", ".join(map(str, ignored)))
        if duplicates_removed:
            st.info(f"Removed {duplicates_removed} identical overlapping samples to prevent double counting.")
        st.caption(f"Combined {len(sources)} data sources into one chronological dataset.")
        st.subheader("Aggregated Data")
        st.dataframe(result.head(50), width="stretch")
        st.download_button(
            "📥 Download Aggregated Data",
            data=excel_bytes(result),
            file_name="combined_aggregated_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        st.error(f"Could not process the data: {exc}")


if __name__ == "__main__":
    main()
