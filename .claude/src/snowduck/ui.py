"""
Streamlit Dashboard for DuckDB/Snowflake Cost Optimization Agent
Displays execution metrics, cost savings, and engine selection.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(
    page_title="Smart Engine Selector Dashboard",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Smart DuckDB/Snowflake Agent Dashboard")
st.caption("Monitoring cost optimization and engine selection for dbt models")

# Load results
results_path = Path(__file__).parent.parent / 'execution_results.csv'
if results_path.exists():
    df = pd.read_csv(results_path)
else:
    st.warning("No execution results found. Run the agent first.")
    df = pd.DataFrame()

if not df.empty:
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Models", len(df))
    with col2:
        duckdb_count = len(df[df['engine'] == 'duckdb'])
        st.metric("DuckDB Models", duckdb_count)
    with col3:
        avg_savings = df['cost_savings_percent'].mean() if 'cost_savings_percent' in df.columns else 0
        st.metric("Avg Cost Savings", f"{avg_savings:.1f}%")
    with col4:
        total_savings = df['cost_savings_usd'].sum() if 'cost_savings_usd' in df.columns else 0
        st.metric("Total Savings (USD)", f"${total_savings:.6f}")

    # Engine selection pie chart
    if 'engine' in df.columns:
        fig_pie = px.pie(df, names='engine', title="Engine Selection Distribution")
        st.plotly_chart(fig_pie, use_container_width=True)

    # Cost savings bar chart
    if 'model' in df.columns and 'cost_savings_usd' in df.columns:
        fig_bar = px.bar(df, x='model', y='cost_savings_usd', color='engine',
                         title="Cost Savings by Model (USD)")
        st.plotly_chart(fig_bar, use_container_width=True)

    # Execution time comparison
    if 'execution_time_seconds' in df.columns:
        fig_time = px.box(df, x='engine', y='execution_time_seconds',
                          title="Execution Time by Engine")
        st.plotly_chart(fig_time, use_container_width=True)

    # Detailed table
    st.subheader("Detailed Results")
    st.dataframe(df)

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="Download Results as CSV",
        data=csv,
        file_name='agent_results.csv',
        mime='text/csv'
    )
else:
    st.info("Run the agent to generate results and see the dashboard.")

# Sidebar with agent info
st.sidebar.header("About")
st.sidebar.info(
    """
    This agent intelligently routes dbt models to either
    DuckDB (for cost savings) or Snowflake (for compatibility
    and performance) based on:

    1. SQL dialect compatibility (using sqlglot)
    2. Estimated cost and performance
    3. Data size and complexity

    When DuckDB is selected, results are written back to
    Snowflake via Parquet upload and COPY INTO.
    """
)

st.sidebar.header("Instructions")
st.sidebar.markdown(
    """
    1. Ensure dbt project is compiled (`dbt run --profiles-dir . --target dev`)
    2. Set Snowflake environment variables
    3. Run the agent: `python scripts/agent.py`
    4. Launch dashboard: `streamlit run scripts/ui.py`
    """
)