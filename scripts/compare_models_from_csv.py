"""Model Comparison Analysis Script

This script analyzes model comparison CSV files exported from the ML pipeline
and provides comprehensive metrics and visualizations to compare model performance.

Usage:
    python scripts/compare_models_from_csv.py

Purpose: Offline model evaluation and comparison from exported training results
"""

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# ==============================================================================
# CONFIGURATION - Update this path to your CSV file
# ==============================================================================
# CSV_PATH = r"C:\Software\gitlab_unisystems_rdi\energy-comfortness-tool\model_reports\model_comparison\temperature_c_Living Room_20251017T104521_comparison.csv"
CSV_PATH = r"C:\Software\gitlab_unisystems_rdi\energy-comfortness-tool\model_reports\model_comparison\rh_percent_Living Room_20251017T104521_comparison.csv"

# Output directory for plots and reports
OUTPUT_DIR = Path(__file__).parent.parent / "model_reports" / "comparison_analysis"
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

# Plot styling
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 10

# ==============================================================================
# ANALYSIS FUNCTIONS
# ==============================================================================

def load_and_validate_csv(csv_path: str) -> tuple[pd.DataFrame, str, list[str]]:
    """Load CSV and identify observed column and prediction columns.
    
    Returns:
        tuple: (dataframe, target_name, list_of_model_names)
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    df = pd.read_csv(csv_path, parse_dates=['time_end'])
    
    # Identify observed and prediction columns
    observed_col = [col for col in df.columns if col.startswith('observed_')]
    pred_cols = [col for col in df.columns if col.startswith('pred_')]
    
    if len(observed_col) != 1:
        raise ValueError(f"Expected exactly 1 'observed_*' column, found {len(observed_col)}")
    if len(pred_cols) == 0:
        raise ValueError("No 'pred_*' columns found in CSV")
    
    target_name = observed_col[0].replace('observed_', '')
    model_names = [col.replace('pred_', '') for col in pred_cols]
    
    print(f"✓ Loaded CSV: {os.path.basename(csv_path)}")
    print(f"  Target: {target_name}")
    print(f"  Models: {', '.join(model_names)}")
    print(f"  Samples: {len(df):,}")
    print()
    
    return df, target_name, model_names


def get_value_formatter(target_name: str) -> tuple[str, int]:
    """Determine appropriate number formatting based on target variable.
    
    Args:
        target_name: Name of target variable
    
    Returns:
        tuple: (format_string, decimal_places)
    """
    # Temperature-related variables
    if any(keyword in target_name.lower() for keyword in ['temperature', 'temp', '_c', '_f']):
        return '%.1f', 1
    
    # Humidity-related variables
    if any(keyword in target_name.lower() for keyword in ['humidity', 'rh', 'moisture']):
        return '%.1f', 1
    
    # CO2 and gas concentrations (typically integers or 1 decimal)
    if any(keyword in target_name.lower() for keyword in ['co2', 'co', 'ppm']):
        return '%.0f', 0
    
    # Particulate matter (typically 1-2 decimals)
    if any(keyword in target_name.lower() for keyword in ['pm', 'pm10', 'pm2.5', 'pm25']):
        return '%.1f', 1
    
    # VOC and chemicals (typically 1 decimal)
    if any(keyword in target_name.lower() for keyword in ['voc', 'tvoc', 'chemical']):
        return '%.1f', 1
    
    # Sound/acoustic levels (typically 1 decimal)
    if any(keyword in target_name.lower() for keyword in ['sound', 'noise', 'db', 'acoustic', 'decibel']):
        return '%.1f', 1
    
    # Light/illuminance (typically integers)
    if any(keyword in target_name.lower() for keyword in ['light', 'lux', 'illuminance', 'luminance']):
        return '%.0f', 0
    
    # Energy/power (typically 1-2 decimals)
    if any(keyword in target_name.lower() for keyword in ['energy', 'power', 'watt', 'kwh']):
        return '%.2f', 2
    
    # Default: 2 decimals
    return '%.2f', 2


def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Calculate comprehensive regression metrics.
    
    Args:
        y_true: Observed values
        y_pred: Predicted values
    
    Returns:
        Dictionary with metric names and values
    """
    residuals = y_true - y_pred
    
    metrics = {
        'R²': r2_score(y_true, y_pred),
        'MAE': mean_absolute_error(y_true, y_pred),
        'MSE': mean_squared_error(y_true, y_pred),
        'RMSE': np.sqrt(mean_squared_error(y_true, y_pred)),
        'Mean Residual': np.mean(residuals),
        'Median Residual': np.median(residuals),
        'Std Residual': np.std(residuals),
        'Max Overestimate': np.max(residuals),
        'Max Underestimate': np.min(residuals),
        'MAPE (%)': np.mean(np.abs(residuals / (y_true + 1e-10))) * 100,
        '95th Percentile Error': np.percentile(np.abs(residuals), 95),
        'IQR Residual': stats.iqr(residuals),
    }
    
    return metrics


def generate_metrics_table(df: pd.DataFrame, target_name: str, model_names: list[str]) -> pd.DataFrame:
    """Generate comprehensive metrics table for all models.
    
    Args:
        df: DataFrame with observed and predicted columns
        target_name: Name of target variable
        model_names: List of model names
    
    Returns:
        DataFrame with metrics for each model
    """
    y_true = df[f'observed_{target_name}'].values
    
    metrics_data = []
    for model_name in model_names:
        y_pred = df[f'pred_{model_name}'].values
        metrics = calculate_metrics(y_true, y_pred)
        metrics['Model'] = model_name
        metrics_data.append(metrics)
    
    metrics_df = pd.DataFrame(metrics_data)
    metrics_df = metrics_df[['Model'] + [col for col in metrics_df.columns if col != 'Model']]
    
    return metrics_df


def plot_residual_distributions(df: pd.DataFrame, target_name: str, model_names: list[str], output_dir: Path):
    """Plot residual distributions for all models.
    
    Args:
        df: DataFrame with observed and predicted columns
        target_name: Name of target variable
        model_names: List of model names
        output_dir: Directory to save plots
    """
    y_true = df[f'observed_{target_name}'].values
    
    fig, axes = plt.subplots(2, len(model_names), figsize=(5 * len(model_names), 10))
    if len(model_names) == 1:
        axes = axes.reshape(-1, 1)
    
    for idx, model_name in enumerate(model_names):
        y_pred = df[f'pred_{model_name}'].values
        residuals = y_true - y_pred
        
        # Histogram with KDE
        ax1 = axes[0, idx]
        ax1.hist(residuals, bins=50, alpha=0.7, color='steelblue', edgecolor='black', density=True)
        
        # Overlay normal distribution
        mu, sigma = np.mean(residuals), np.std(residuals)
        x = np.linspace(residuals.min(), residuals.max(), 100)
        ax1.plot(x, stats.norm.pdf(x, mu, sigma), 'r-', linewidth=2, label=f'Normal(mean={mu:.3f}, std={sigma:.3f})')
        
        ax1.axvline(0, color='green', linestyle='--', linewidth=2, label='Perfect Prediction')
        ax1.axvline(mu, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label=f'Mean={mu:.3f}')
        ax1.set_xlabel('Residual (Observed - Predicted)', fontsize=11)
        ax1.set_ylabel('Density', fontsize=11)
        ax1.set_title(f'{model_name.upper()} - Residual Distribution', fontsize=12, fontweight='bold')
        ax1.legend(fontsize=9)
        ax1.grid(alpha=0.3)
        
        # Q-Q Plot
        ax2 = axes[1, idx]
        stats.probplot(residuals, dist="norm", plot=ax2)
        ax2.set_title(f'{model_name.upper()} - Q-Q Plot', fontsize=12, fontweight='bold')
        ax2.grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / f'{target_name}_residual_distributions.png', dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {target_name}_residual_distributions.png")
    plt.close()


def plot_predicted_vs_observed(df: pd.DataFrame, target_name: str, model_names: list[str], output_dir: Path):
    """Plot predicted vs observed scatter plots for all models.
    
    Args:
        df: DataFrame with observed and predicted columns
        target_name: Name of target variable
        model_names: List of model names
        output_dir: Directory to save plots
    """
    y_true = df[f'observed_{target_name}'].values
    
    fig, axes = plt.subplots(1, len(model_names), figsize=(6 * len(model_names), 5))
    if len(model_names) == 1:
        axes = [axes]
    
    for idx, model_name in enumerate(model_names):
        y_pred = df[f'pred_{model_name}'].values
        
        ax = axes[idx]
        
        # Scatter plot with density coloring
        h = ax.hexbin(y_true, y_pred, gridsize=50, cmap='Blues', mincnt=1)
        
        # Perfect prediction line
        min_val = min(y_true.min(), y_pred.min())
        max_val = max(y_true.max(), y_pred.max())
        ax.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2, label='Perfect Prediction')
        
        # Calculate and display metrics
        r2 = r2_score(y_true, y_pred)
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        
        ax.text(0.05, 0.95, f'R² = {r2:.4f}\nMAE = {mae:.4f}\nRMSE = {rmse:.4f}',
                transform=ax.transAxes, fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        ax.set_xlabel(f'Observed {target_name}', fontsize=11)
        ax.set_ylabel(f'Predicted {target_name}', fontsize=11)
        ax.set_title(f'{model_name.upper()}', fontsize=12, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        ax.set_aspect('equal', adjustable='box')
        
        # Add colorbar
        plt.colorbar(h, ax=ax, label='Count')
    
    plt.tight_layout()
    plt.savefig(output_dir / f'{target_name}_predicted_vs_observed.png', dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {target_name}_predicted_vs_observed.png")
    plt.close()


def plot_residuals_over_time(df: pd.DataFrame, target_name: str, model_names: list[str], output_dir: Path):
    """Plot residuals over time to identify temporal patterns.
    
    Args:
        df: DataFrame with observed and predicted columns
        target_name: Name of target variable
        model_names: List of model names
        output_dir: Directory to save plots
    """
    y_true = df[f'observed_{target_name}'].values
    
    fig, axes = plt.subplots(len(model_names), 1, figsize=(14, 4 * len(model_names)))
    if len(model_names) == 1:
        axes = [axes]
    
    for idx, model_name in enumerate(model_names):
        y_pred = df[f'pred_{model_name}'].values
        residuals = y_true - y_pred
        
        ax = axes[idx]
        ax.scatter(df['time_end'], residuals, alpha=0.5, s=10, color='steelblue')
        ax.axhline(0, color='red', linestyle='--', linewidth=2, label='Zero Residual')
        ax.axhline(np.mean(residuals), color='orange', linestyle='--', linewidth=1.5, 
                   alpha=0.7, label=f'Mean={np.mean(residuals):.3f}')
        
        # Add rolling mean
        if len(df) > 50:
            rolling_window = min(100, len(df) // 10)
            rolling_mean = pd.Series(residuals).rolling(window=rolling_window, center=True).mean()
            ax.plot(df['time_end'], rolling_mean, color='green', linewidth=2, 
                   label=f'Rolling Mean (window={rolling_window})')
        
        ax.set_xlabel('Time', fontsize=11)
        ax.set_ylabel('Residual', fontsize=11)
        ax.set_title(f'{model_name.upper()} - Residuals Over Time', fontsize=12, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / f'{target_name}_residuals_over_time.png', dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {target_name}_residuals_over_time.png")
    plt.close()


def plot_error_by_magnitude(df: pd.DataFrame, target_name: str, model_names: list[str], output_dir: Path):
    """Plot absolute error vs observed value magnitude to identify bias patterns.
    
    Args:
        df: DataFrame with observed and predicted columns
        target_name: Name of target variable
        model_names: List of model names
        output_dir: Directory to save plots
    """
    y_true = df[f'observed_{target_name}'].values
    
    # Get appropriate formatter for this target
    fmt_str, decimals = get_value_formatter(target_name)
    
    # Calculate grid: 2 columns, as many rows as needed
    n_models = len(model_names)
    n_cols = 2
    n_rows = (n_models + 1) // 2  # Ceiling division
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(12, 5 * n_rows))
    
    # Handle single row case
    if n_rows == 1:
        axes = axes.reshape(1, -1)
    
    # Flatten axes for easier iteration
    axes_flat = axes.flatten()
    
    for idx, model_name in enumerate(model_names):
        y_pred = df[f'pred_{model_name}'].values
        abs_error = np.abs(y_true - y_pred)
        
        ax = axes_flat[idx]
        ax.hexbin(y_true, abs_error, gridsize=50, cmap='Reds', mincnt=1)
        
        # Add rolling median
        sorted_idx = np.argsort(y_true)
        window = min(100, len(y_true) // 10)
        if window > 10:
            rolling_median = pd.Series(abs_error[sorted_idx]).rolling(window=window, center=True).median()
            ax.plot(y_true[sorted_idx], rolling_median, color='blue', linewidth=2, 
                   label=f'Rolling Median (window={window})')
        
        # Format tick labels based on target type
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: fmt_str % x))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: fmt_str % x))
        
        ax.set_xlabel(f'Observed {target_name}', fontsize=11)
        ax.set_ylabel('Absolute Error', fontsize=11)
        ax.set_title(f'{model_name.upper()} - Error vs Magnitude', fontsize=12, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        
        plt.colorbar(ax.collections[0], ax=ax, label='Count')
    
    # Hide unused subplots if odd number of models
    for idx in range(n_models, len(axes_flat)):
        axes_flat[idx].set_visible(False)
    
    plt.tight_layout()
    plt.savefig(output_dir / f'{target_name}_error_by_magnitude.png', dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {target_name}_error_by_magnitude.png")
    plt.close()


def plot_metrics_comparison_bar(metrics_df: pd.DataFrame, target_name: str, output_dir: Path):
    """Create bar charts comparing key metrics across models.
    
    Args:
        metrics_df: DataFrame with metrics for each model
        target_name: Name of target variable
        output_dir: Directory to save plots
    """
    key_metrics = ['R²', 'MAE', 'RMSE', 'Mean Residual', 'Std Residual', '95th Percentile Error']
    
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    axes = axes.flatten()
    
    for idx, metric in enumerate(key_metrics):
        ax = axes[idx]
        
        values = metrics_df[metric].values
        models = metrics_df['Model'].values
        colors = plt.cm.viridis(np.linspace(0, 1, len(models)))
        
        bars = ax.bar(models, values, color=colors, edgecolor='black', linewidth=1.5)
        
        # Highlight best model (highest R², lowest for others)
        if metric == 'R²':
            best_idx = np.argmax(values)
        else:
            best_idx = np.argmin(np.abs(values)) if 'Residual' in metric else np.argmin(values)
        
        bars[best_idx].set_edgecolor('red')
        bars[best_idx].set_linewidth(3)
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.4f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
        
        ax.set_ylabel(metric, fontsize=11)
        ax.set_title(f'{metric} Comparison', fontsize=12, fontweight='bold')
        ax.grid(alpha=0.3, axis='y')
        ax.tick_params(axis='x', rotation=45)
    
    plt.suptitle(f'Model Performance Metrics - {target_name}', fontsize=14, fontweight='bold', y=1.00)
    plt.tight_layout()
    plt.savefig(output_dir / f'{target_name}_metrics_comparison.png', dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {target_name}_metrics_comparison.png")
    plt.close()


def plot_residual_percentiles(df: pd.DataFrame, target_name: str, model_names: list[str], output_dir: Path):
    """Plot residual percentile distributions to compare model reliability.
    
    Args:
        df: DataFrame with observed and predicted columns
        target_name: Name of target variable
        model_names: List of model names
        output_dir: Directory to save plots
    """
    y_true = df[f'observed_{target_name}'].values
    
    percentiles = np.arange(0, 101, 5)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    for model_name in model_names:
        y_pred = df[f'pred_{model_name}'].values
        residuals = y_true - y_pred
        abs_residuals = np.abs(residuals)
        
        residual_percentiles = np.percentile(residuals, percentiles)
        abs_residual_percentiles = np.percentile(abs_residuals, percentiles)
        
        ax1.plot(percentiles, residual_percentiles, marker='o', linewidth=2, label=model_name.upper())
        ax2.plot(percentiles, abs_residual_percentiles, marker='o', linewidth=2, label=model_name.upper())
    
    ax1.axhline(0, color='red', linestyle='--', linewidth=2, alpha=0.7)
    ax1.set_xlabel('Percentile', fontsize=11)
    ax1.set_ylabel('Residual Value', fontsize=11)
    ax1.set_title('Residual Percentiles', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(alpha=0.3)
    
    ax2.set_xlabel('Percentile', fontsize=11)
    ax2.set_ylabel('Absolute Residual Value', fontsize=11)
    ax2.set_title('Absolute Error Percentiles', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / f'{target_name}_residual_percentiles.png', dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {target_name}_residual_percentiles.png")
    plt.close()


def generate_summary_report(metrics_df: pd.DataFrame, target_name: str, output_dir: Path):
    """Generate comprehensive markdown summary report.
    
    Args:
        metrics_df: DataFrame with metrics for each model
        target_name: Name of target variable
        output_dir: Directory to save report
    """
    # Rank models by R²
    ranked_df = metrics_df.sort_values('R²', ascending=False).copy()
    ranked_df.insert(0, 'Rank', range(1, len(ranked_df) + 1))
    
    report_lines = [
        f"# Model Comparison Report: {target_name}",
        f"\n**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n**Samples:** {len(pd.read_csv(CSV_PATH)):,}",
        "\n---\n",
        "\n## Executive Summary\n",
        f"**Best Model (R²):** {ranked_df.iloc[0]['Model'].upper()}",
        f"- R² = {ranked_df.iloc[0]['R²']:.6f}",
        f"- MAE = {ranked_df.iloc[0]['MAE']:.6f}",
        f"- RMSE = {ranked_df.iloc[0]['RMSE']:.6f}",
        "\n---\n",
        "\n## Detailed Metrics Table\n",
    ]
    
    # Format metrics table
    report_lines.append(ranked_df.to_markdown(index=False, floatfmt=".6f"))
    
    report_lines.extend([
        "\n---\n",
        "\n## Model Ranking by Key Metrics\n",
    ])
    
    # Rank by different metrics
    key_metrics = ['R²', 'MAE', 'RMSE', 'Std Residual']
    for metric in key_metrics:
        ascending = False if metric == 'R²' else True
        ranked = metrics_df.sort_values(metric, ascending=ascending)
        report_lines.append(f"\n### By {metric}\n")
        ranking_lines = [f"{i+1}. **{row['Model'].upper()}**: {row[metric]:.6f}" 
                        for i, (_, row) in enumerate(ranked.iterrows())]
        report_lines.extend(ranking_lines)
    
    report_lines.extend([
        "\n---\n",
        "\n## Statistical Insights\n",
    ])
    
    # Best/worst performers
    best_r2_model = ranked_df.iloc[0]['Model'].upper()
    worst_r2_model = ranked_df.iloc[-1]['Model'].upper()
    r2_diff = ranked_df.iloc[0]['R²'] - ranked_df.iloc[-1]['R²']
    
    report_lines.extend([
        f"- **R² Spread:** {r2_diff:.6f} ({best_r2_model} vs {worst_r2_model})",
        f"- **Best MAE:** {metrics_df['MAE'].min():.6f} ({metrics_df.loc[metrics_df['MAE'].idxmin(), 'Model'].upper()})",
        f"- **Most Stable (lowest std):** {metrics_df.loc[metrics_df['Std Residual'].idxmin(), 'Model'].upper()} "
        f"(std = {metrics_df['Std Residual'].min():.6f})",
    ])
    
    # Check for bias
    report_lines.append("\n### Bias Analysis (Mean Residual)\n")
    for _, row in metrics_df.iterrows():
        mean_res = row['Mean Residual']
        bias_type = "overestimates" if mean_res < 0 else "underestimates" if mean_res > 0 else "unbiased"
        report_lines.append(f"- **{row['Model'].upper()}**: {mean_res:.6f} ({bias_type})")
    
    report_lines.extend([
        "\n---\n",
        "\n## Generated Plots\n",
        f"1. `{target_name}_metrics_comparison.png` - Key metrics bar charts",
        f"2. `{target_name}_residual_distributions.png` - Residual histograms and Q-Q plots",
        f"3. `{target_name}_predicted_vs_observed.png` - Scatter plots",
        f"4. `{target_name}_residuals_over_time.png` - Temporal residual patterns",
        f"5. `{target_name}_error_by_magnitude.png` - Error vs observed value magnitude",
        f"6. `{target_name}_residual_percentiles.png` - Percentile distributions",
        "\n---\n",
        "\n## Recommendations\n",
        f"Based on the analysis, **{best_r2_model}** is recommended for production use with:",
        f"- Highest explained variance (R² = {ranked_df.iloc[0]['R²']:.6f})",
        f"- Mean absolute error of {ranked_df.iloc[0]['MAE']:.6f}",
        "\nConsider ensemble methods if multiple models show similar performance.",
    ])
    
    report_path = output_dir / f'{target_name}_comparison_report.md'
    report_path.write_text('\n'.join(report_lines), encoding='utf-8')
    print(f"✓ Saved: {target_name}_comparison_report.md")


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def main():
    """Main execution function."""
    print("="*80)
    print(" MODEL COMPARISON ANALYSIS")
    print("="*80)
    print()
    
    # Load data
    try:
        df, target_name, model_names = load_and_validate_csv(CSV_PATH)
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")
        return
    
    # Calculate metrics
    print("Calculating metrics...")
    metrics_df = generate_metrics_table(df, target_name, model_names)
    print("✓ Metrics calculated\n")
    
    # Display metrics
    print("METRICS SUMMARY")
    print("="*80)
    print(metrics_df.to_string(index=False))
    print("\n")
    
    # Save metrics to CSV
    metrics_path = OUTPUT_DIR / f'{target_name}_metrics.csv'
    metrics_df.to_csv(metrics_path, index=False)
    print(f"✓ Saved metrics to: {metrics_path}\n")
    
    # Generate plots
    print("Generating visualizations...")
    plot_metrics_comparison_bar(metrics_df, target_name, OUTPUT_DIR)
    plot_residual_distributions(df, target_name, model_names, OUTPUT_DIR)
    plot_predicted_vs_observed(df, target_name, model_names, OUTPUT_DIR)
    plot_residuals_over_time(df, target_name, model_names, OUTPUT_DIR)
    plot_error_by_magnitude(df, target_name, model_names, OUTPUT_DIR)
    plot_residual_percentiles(df, target_name, model_names, OUTPUT_DIR)
    print()
    
    # Generate summary report
    print("Generating summary report...")
    generate_summary_report(metrics_df, target_name, OUTPUT_DIR)
    print()
    
    print("="*80)
    print(f"✓ ANALYSIS COMPLETE - Results saved to: {OUTPUT_DIR}")
    print("="*80)


if __name__ == "__main__":
    main()
