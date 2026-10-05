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
    rules = {}
    for col in numeric.columns:
        label = str(col).lower()
        rules[col] = (lambda values: values.sum(min_count=1)) if "energy" in label else "mean"
    return numeric.resample(freq).agg(rules), invalid_rows, ignored


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
1. Upload an Excel or CSV file.
2. Select the time column and aggregation interval.
3. Set the timezone for timestamps that do not include an offset.
4. Choose the timezone to use for aggregation and export.
5. Review and download the results.
""")
    st.sidebar.header("📖 Glossary")
    st.sidebar.markdown("""
- **Irradiance, power and temperature:** averaged over each interval.
- **Interval energy:** summed over each interval.
- **Cumulative energy counters:** convert to interval energy before uploading.
- **Other numeric columns:** averaged by default.
- **Missing data:** remains blank when an entire interval has no readings.
""")

    uploaded_file = st.file_uploader("Upload Excel/CSV file", type=["xlsx", "csv"])
    if uploaded_file is None:
        return
    try:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.lower().endswith(".csv") else pd.read_excel(uploaded_file)
    except Exception as exc:
        st.error(f"Could not read the file: {exc}")
        st.stop()

    st.subheader("Raw Data Preview")
    st.dataframe(df.head(), width="stretch")
    if df.empty:
        st.warning("The uploaded file is empty.")
        st.stop()
    time_col = st.selectbox("Select Time Column", df.columns)
    freq = st.selectbox("Select aggregation interval", ["30min", "1h", "2h", "1D"])
    naive_timezone = st.selectbox("Timezone for timestamps without an offset", ["Europe/London", "UTC"])
    output_timezone = st.selectbox("Aggregation and export timezone", ["Europe/London", "UTC"])
    st.caption("Timestamps with Z or a UTC offset retain their actual instant. Excel includes a UTC offset column to distinguish repeated clock times when daylight saving ends.")

    try:
        result, invalid_rows, ignored = aggregate_data(df, time_col, freq, naive_timezone, output_timezone)
        if invalid_rows:
            st.warning(f"Skipped {invalid_rows} rows with invalid or ambiguous timestamps.")
        if ignored:
            st.info("Columns without numeric readings were omitted: " + ", ".join(map(str, ignored)))
        st.subheader("Aggregated Data")
        st.dataframe(result.head(50), width="stretch")
        st.download_button(
            "📥 Download Aggregated Data",
            data=excel_bytes(result),
            file_name="aggregated_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        st.error(f"Could not process the data: {exc}")


if __name__ == "__main__":
    main()
