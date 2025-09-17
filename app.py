import streamlit as st
import pandas as pd

st.title("⏱ Data Aggregation Tool")

# Upload file
uploaded_file = st.file_uploader("Upload Excel/CSV file", type=["xlsx", "csv"])

if uploaded_file:
    # Read file
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.write("### Raw Data Preview", df.head())

    # Time column
    time_col = st.selectbox("Select Time Column", df.columns)

    # Convert time to datetime
    df[time_col] = pd.to_datetime(df[time_col])

    # Set index
    df = df.set_index(time_col)

    # Select aggregation interval
    freq = st.selectbox("Select aggregation interval", ["30min", "1H", "2H", "1D"])

    # Define aggregation rules
    agg_rules = {}
    for col in df.columns:
        col_lower = col.lower()
        if "irradiance" in col_lower or "power" in col_lower or "temp" in col_lower:
            agg_rules[col] = "mean"
        elif "energy" in col_lower:
            agg_rules[col] = "sum"
        else:
            agg_rules[col] = "mean"  # default

    # Resample
    df_resampled = df.resample(freq).agg(agg_rules)

    st.write("### Aggregated Data", df_resampled.head())

    # Download option
    output_file = "aggregated_data.xlsx"
    df_resampled.to_excel(output_file)

    with open(output_file, "rb") as f:
        st.download_button(
            "📥 Download Aggregated Data",
            f,
            file_name=output_file,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
