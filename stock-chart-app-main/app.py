from flask import Flask, render_template, request, after_this_request
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from mplfinance.original_flavor import candlestick_ohlc
import pandas as pd
import os
from datetime import datetime, timedelta
import numpy as np
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
import io
import base64
import time

app = Flask(__name__)

# Ensure templates folder exists
os.makedirs('templates', exist_ok=True)

@app.after_request
def add_no_cache(response):
    """Add no-cache headers to prevent stale responses."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def get_valid_date(symbol, date_str):
    date = datetime.strptime(date_str, '%Y-%m-%d')
    while True:
        end_date = (date + timedelta(days=1)).strftime('%Y-%m-%d')
        stock_data = yf.download(symbol, start=date.strftime('%Y-%m-%d'), end=end_date, progress=False)
        if isinstance(stock_data.columns, pd.MultiIndex):
            stock_data.columns = [col[0] for col in stock_data.columns]
        if not stock_data.empty and 'Close' in stock_data.columns and len(stock_data) > 0:
            return date.strftime('%Y-%m-%d')
        date = date - timedelta(days=1)

def get_custom_date_range_gain(symbol, start_date, end_date):
    data = yf.download(symbol, start=start_date, end=end_date, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] for col in data.columns]
    if data.empty or len(data) < 2 or 'Close' not in data.columns:
        return np.nan
    close_prices = data['Close']
    if close_prices.empty or pd.isna(close_prices.iloc[0]) or pd.isna(close_prices.iloc[-1]):
        return np.nan
    gain = ((close_prices.iloc[-1] - close_prices.iloc[0]) / close_prices.iloc[0]) * 100
    return gain

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/candle', methods=['GET', 'POST'])
def candle():
    if request.method == 'POST':
        ticker = request.form['ticker'].upper()
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        
        # Fetch stock data (progress=False for faster)
        data = yf.download(ticker, start=start_date, end=end_date, progress=False)
        
        if data.empty:
            return render_template('candle.html', error=f"No data found for {ticker}")
        
        # Prepare data for candlestick chart
        data = data.reset_index()
        data['Date'] = mdates.date2num(data['Date'])  # Convert dates to matplotlib numbers
        ohlc = data[['Date', 'Open', 'High', 'Low', 'Close']].values
        
        # Create the plot
        fig, ax = plt.subplots(figsize=(12, 6))
        candlestick_ohlc(ax, ohlc, width=0.6, colorup='g', colordown='r', alpha=0.8)
        
        # Format the x-axis
        ax.xaxis_date()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator())
        plt.xticks(rotation=45)
        plt.title(f'{ticker} Candlestick Chart')
        plt.xlabel('Date')
        plt.ylabel('Price')
        plt.tight_layout()
        
        # Save the plot to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plot_b64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close()
        
        # Base64 data URI without query param (browsers handle caching via headers)
        plot_url = f"data:image/png;base64,{plot_b64}"
        return render_template('candle.html', plot_url=plot_url, ticker=ticker)
    
    return render_template('candle.html')

def analyze_indices(indices, index_names, route_name):
    def get_percentage_return(stock_symbol, reference_date, durations):
        data = yf.download(stock_symbol, start=reference_date - timedelta(days=max(durations)), end=reference_date, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        returns = {}
        for duration in durations:
            end_date = reference_date
            start_date = end_date - timedelta(days=duration)
            filtered_data = data[(data.index >= start_date) & (data.index <= end_date)]
            if len(filtered_data) > 1 and 'Close' in filtered_data.columns:
                percentage_return = ((filtered_data['Close'].iloc[-1] / filtered_data['Close'].iloc[0]) - 1) * 100
                returns[duration] = percentage_return
            else:
                returns[duration] = None
        return returns

    reference_date = datetime.utcnow()
    durations = [30, 60, 90]

    result_df_all = pd.DataFrame(columns=durations)

    for stock_symbol in indices:
        returns = get_percentage_return(stock_symbol, reference_date, durations)
        returns_df = pd.DataFrame([returns], index=[stock_symbol])
        result_df_all = pd.concat([result_df_all, returns_df], axis=0)

    result_df_all['Name'] = [index_names.get(idx, idx) for idx in result_df_all.index]
    result_df_all = result_df_all.astype({col: float for col in durations})

    no_nan_df = result_df_all.dropna(subset=durations)
    nan_df = result_df_all[result_df_all[durations].isna().any(axis=1)]

    rank_df_all = no_nan_df[durations].rank(axis=0, ascending=False, method='min')

    for duration in durations:
        no_nan_df[f'Rank_{duration} days'] = rank_df_all[duration]

    no_nan_df['Sum of Ranks'] = no_nan_df[[f'Rank_{d} days' for d in durations]].sum(axis=1)

    no_nan_sorted = no_nan_df.sort_values(by='Sum of Ranks', ascending=True)

    result_df_all_sorted = pd.concat([no_nan_sorted, nan_df])

    lowest_three_stocks = no_nan_sorted.head(3)
    index_3 = list(lowest_three_stocks.index)
    index_n = [index_names.get(i, i) for i in index_3]

    # Generate plot
    fig, ax = plt.subplots(figsize=(10, 8))
    bar_width = 0.2
    bar_positions = np.arange(len(lowest_three_stocks))

    for i, duration in enumerate(durations):
        bars = ax.bar(bar_positions + i * bar_width, lowest_three_stocks[duration], bar_width, label=f'{duration} days')
        for j, value in enumerate(lowest_three_stocks[duration]):
            ax.text(
                bar_positions[j] + i * bar_width,
                value,
                f'{value:.2f}%',
                ha='center',
                va='bottom' if value >= 0 else 'top',
                fontsize=14
            )

    ax.set_xticks(bar_positions + bar_width * (len(durations) - 1) / 2)
    ax.set_xticklabels(index_n, fontsize=16, rotation=45, ha='right')
    ax.legend(title='Duration')
    if route_name == 'nse':
        ax.set_title('Performance of Top 3 NSE Indices', fontsize=20)
    else:
        ax.set_title('Performance of top 3 indices worldwide', fontsize=20)
    ax.set_xlabel('Indices', fontsize=14)
    ax.set_ylabel('Percentage Return', fontsize=14)

    plt.tight_layout()

    # Save plot to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plot_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()

    plot_url = f"data:image/png;base64,{plot_b64}"

    # Prepare table HTML
    result_df_all_sorted_display = result_df_all_sorted.copy()
    result_df_all_sorted_display.insert(0, 'Name', result_df_all_sorted_display.pop('Name'))
    result_df_all_sorted_display = result_df_all_sorted_display[['Name'] + [col for col in result_df_all_sorted_display.columns if col != 'Name']]
    table_html = result_df_all_sorted_display.to_html(classes='table table-striped table-bordered', escape=False, na_rep='N/A')

    return table_html, plot_url

@app.route('/nse', methods=['GET', 'POST'])
def nse():
    if request.method == 'POST':
        try:
            indices = ['^NSEI', '^CNXIT', '^CNXREALTY', '^CNXINFRA', '^CNXAUTO',
                       '^CNXMETAL', '^CNXCMDT', '^CNXPSUBANK', '^NSEBANK',
                       'NIFTY_PVT_BANK.NS', '^CNXPSE', '^CNXENERGY',
                       '^CNXMNC', '^CNXFMCG', 'NIFTY_FIN_SERVICE.NS', '^CNXMEDIA', '^CNXCONSUM',
                       '^CNXSERVICE', 'NIFTY_MIDCAP_100.NS', 'BSE-SMLCAP.BO','^CNXSC','^CNXPHARMA']

            index_names = {
                '^NSEI': 'Nifty 50',
                '^CNXIT': 'Nifty IT',
                '^CNXREALTY': 'Nifty Realty',
                '^CNXINFRA': 'Nifty Infrastructure',
                '^CNXAUTO': 'Nifty Auto',
                '^CNXMETAL': 'Nifty Metal',
                '^CNXCMDT': 'Nifty Commodities',
                '^CNXPSUBANK': 'Nifty PSU Bank',
                '^NSEBANK': 'Nifty Bank',
                'NIFTY_PVT_BANK.NS': 'Nifty Private Bank',
                '^CNXPSE': 'Nifty PSE',
                '^CNXENERGY': 'Nifty Energy',
                '^CNXMNC': 'Nifty MNC',
                '^CNXFMCG': 'Nifty FMCG',
                'NIFTY_FIN_SERVICE.NS': 'Nifty Financial Services',
                '^CNXMEDIA': 'Nifty Media',
                '^CNXCONSUM': 'Nifty Consumption',
                '^CNXSERVICE': 'Nifty Services Sector',
                'NIFTY_MIDCAP_100.NS': 'Nifty Midcap 100',
                'BSE-SMLCAP.BO': 'BSE SmallCap',
                '^CNXSC': 'Nifty Smallcap',
                '^CNXPHARMA': 'Nifty Pharma'
            }

            table_html, plot_url = analyze_indices(indices, index_names, 'nse')

            return render_template('nse.html', table=table_html, plot_url=plot_url)
        
        except Exception as e:
            return render_template('nse.html', error=f"Error generating NSE Indices analysis: {str(e)}")
    
    return render_template('nse.html', message="Click 'Run NSE Analysis' to generate results.")

@app.route('/world', methods=['GET', 'POST'])
def world():
    if request.method == 'POST':
        try:
            indices = ['^NSEI', '^HSI','^DJI', '^IXIC', '^FTSE','^GDAXI', '^FCHI', '^STOXX50E','^N225', 
                       '^JKSE', '^KLSE', '^KS11', '^TWII','^BVSP', '^MXX', '^TA125.TA','^STI','PSEI.PS','^BSESN','^GSPTSE']

            index_names = {'^NSEI': 'Nifty 50', '^HSI': 'Hang Seng','^DJI': 'Dow Jones', '^IXIC': 'Nasdaq', '^FTSE': 'FTSE 100 UK',
                           '^GDAXI': 'DAX Germany', '^FCHI': 'CAC 40 France', '^STOXX50E': 'EURO STOXX 50',
                           '^N225': 'Nikkei 225 Japan', 
                           '^JKSE': 'JKSE Indonesia', '^KLSE': 'KLSE Malaysia', '^KS11': 'KOSPI South Korea', '^TWII': 'TSEC Taiwan',
                           '^BVSP': 'BOVESPA Brazil', '^MXX': 'MXX Mexico', '^TA125.TA': 'TA125 Tel Aviv','^STI':'STI Singapore',
                           'PSEI.PS':'PSEI Philippines','^BSESN':'Sensex','^GSPTSE':'S&P/TSX Canada'}

            table_html, plot_url = analyze_indices(indices, index_names, 'world')

            return render_template('world.html', table=table_html, plot_url=plot_url)
        
        except Exception as e:
            return render_template('world.html', error=f"Error generating World Indices analysis: {str(e)}")
    
    return render_template('world.html', message="Click 'Run World Indices Analysis' to generate results.")

@app.route('/seasonality', methods=['GET', 'POST'])
def seasonality():
    if request.method == 'POST':
        ticker = request.form['ticker'].upper()
        year = int(request.form.get('year', 30))  # Default 30 years
        
        try:
            end_date = datetime.utcnow()  # Use datetime, not date, for compatibility
            start_date = end_date - timedelta(days=year * 365)
            
            # Download historical data
            data = yf.download(ticker, start=start_date, end=end_date, interval="1mo", auto_adjust=True, progress=False)
            
            # Handle MultiIndex columns
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]  # Flatten to first level (e.g., 'Close')
            
            # Fix: Remove timezone from index if present
            if data.index.tz is not None:
                data.index = data.index.tz_localize(None)
            
            if data.empty:
                return render_template('seasonality.html', error=f"No data retrieved for {ticker}. Please check the ticker or internet connection.")
            
            # Verify 'Close' column exists
            if 'Close' not in data.columns:
                return render_template('seasonality.html', error=f"'Close' column not found. Available columns: {data.columns.tolist()}")
            
            # Calculate monthly returns
            data['Returns'] = data['Close'].pct_change()
            
            # Verify 'Returns' column exists
            if 'Returns' not in data.columns:
                return render_template('seasonality.html', error=f"'Returns' column not created. Available columns: {data.columns.tolist()}")
            
            # Remove rows with NaN returns
            data = data.dropna(subset=['Returns'])
            
            # Check if data is empty after dropping NaN
            if data.empty:
                return render_template('seasonality.html', error="Data is empty after dropping NaN values.")
            
            # Extract year and month from index
            data['Year'] = data.index.year
            data['Month'] = data.index.month
            
            # Calculate actual number of years
            actual_year = len(data['Year'].unique())
            
            # Create Positive and Negative columns
            data['Positive'] = data['Returns'] > 0
            data['Negative'] = data['Returns'] < 0
            
            # Count positive and negative returns for each month
            monthly_counts = data.groupby('Month')[['Positive', 'Negative']].sum()
            
            # Calculate average positive returns and total average returns (arithmetic) for each month
            monthly_avg_positive = data[data['Returns'] > 0].groupby('Month')['Returns'].mean()
            monthly_avg_total = data.groupby('Month')['Returns'].mean()
            
            # Calculate geometric mean returns for each month
            def geometric_mean(returns):
                returns_plus_one = 1 + returns
                if len(returns) == 0:
                    return np.nan
                return (np.prod(returns_plus_one)) ** (1 / len(returns)) - 1
            
            monthly_geo_mean = data.groupby('Month')['Returns'].apply(geometric_mean)
            
            # Prepare monthly summary DataFrame
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            summary_data = []
            for month in range(1, 13):
                pos_count = int(monthly_counts.loc[month, 'Positive']) if month in monthly_counts.index else 0
                neg_count = int(monthly_counts.loc[month, 'Negative']) if month in monthly_counts.index else 0
                avg_pos = monthly_avg_positive.loc[month] if month in monthly_avg_positive.index else np.nan
                avg_total = monthly_avg_total.loc[month] if month in monthly_avg_total.index else np.nan
                geo_mean = monthly_geo_mean.loc[month] if month in monthly_geo_mean.index else np.nan
                summary_data.append({
                    'Month': month_names[month-1],
                    'Positive': pos_count,
                    'Negative': neg_count,
                    'Avg Positive Return': f"{avg_pos:.2%}" if not pd.isna(avg_pos) else 'N/A',
                    'Avg Total Return': f"{avg_total:.2%}" if not pd.isna(avg_total) else 'N/A',
                    'Geo Mean Return': f"{geo_mean:.2%}" if not pd.isna(geo_mean) else 'N/A'
                })
            summary_df = pd.DataFrame(summary_data)
            summary_html = summary_df.to_html(classes='table table-striped table-bordered', escape=False)
            
            # Group by year and month to calculate average returns for heatmap
            monthly_avg = data.groupby(['Year', 'Month'])['Returns'].mean().unstack()
            
            # Create custom colormap: darker pink for negative, darker green for positive
            colors = ['#C71585', '#DB7093', '#FFFFFF', '#228B22', '#006400']  # Deep pink, medium pink, white, dark green, darker green
            cmap = LinearSegmentedColormap.from_list('dark_cmap', colors, N=256)
            
            # Plot heatmap
            plt.figure(figsize=(12, 10))
            sns.heatmap(monthly_avg, annot=True, fmt=".2%", cmap=cmap, center=0, 
                        cbar_kws={'label': 'Average Monthly Returns'})
            plt.title(f"Monthly Seasonality of {ticker} Returns (Last {actual_year} Years)")
            plt.xlabel("Month")
            plt.ylabel("Year")
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            plt.xticks(ticks=range(12), labels=month_names, rotation=45)
            plt.yticks(rotation=0)
            plt.tight_layout()
            
            # Save the plot to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plot_b64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close()
            
            # Base64 data URI without query param (browsers handle caching via headers)
            plot_url = f"data:image/png;base64,{plot_b64}"
            return render_template('seasonality.html', summary_table=summary_html, plot_url=plot_url, ticker=ticker, actual_year=actual_year)
        
        except Exception as e:
            return render_template('seasonality.html', error=f"Error generating seasonality analysis for {ticker}: {str(e)}")
    
    return render_template('seasonality.html')

@app.route('/custom', methods=['GET', 'POST'])
def custom():
    if request.method == 'POST':
        try:
            start_str = request.form['start_date']
            end_str = request.form['end_date']
            start_dt = datetime.strptime(start_str, '%Y-%m-%d')
            end_dt = datetime.strptime(end_str, '%Y-%m-%d')

            index_names = {'^NSEI': 'Nifty 50', '^HSI': 'Hang Seng','^DJI': 'Dow Jones', '^IXIC': 'Nasdaq', '^FTSE': 'FTSE 100 UK',
                           '^GDAXI': 'DAX Germany', '^FCHI': 'CAC 40 France', '^STOXX50E': 'EURO STOXX 50',
                           '^N225': 'Nikkei 225 Japan', 
                           '^JKSE': 'JKSE Indonesia', '^KLSE': 'KLSE Malaysia', '^KS11': 'KOSPI South Korea', '^TWII': 'TSEC Taiwan',
                           '^BVSP': 'BOVESPA Brazil', '^MXX': 'MXX Mexico', '^TA125.TA': 'TA125 Tel Aviv','^STI':'STI Singapore',
                           'PSEI.PS':'PSEI Philippines','^BSESN':'Sensex','^GSPTSE':'S&P/TSX Canada'}
            indices = list(index_names.keys())

            index_start_dates = []
            for ind in indices:
                start_date = get_valid_date(ind, start_str)
                index_start_dates.append(start_date)

            end_yf = (end_dt + timedelta(days=1)).strftime('%Y-%m-%d')

            gains = []
            for i, ind in enumerate(indices):
                gain = get_custom_date_range_gain(ind, index_start_dates[i], end_yf)
                gains.append(gain)

            tickers = [index_names[ind] for ind in indices]

            # Create DataFrame for table
            df = pd.DataFrame({'Index': tickers, 'Gain (%)': gains})
            df = df.sort_values('Gain (%)', ascending=False).reset_index(drop=True)
            df['Gain (%)'] = df['Gain (%)'].round(2)
            table_html = df.to_html(classes='table table-striped table-bordered', escape=False, na_rep='N/A', float_format='%.2f')

            # Plot
            fig, ax = plt.subplots(figsize=(12, 8))
            fig.patch.set_facecolor('black')
            ax.set_facecolor('black')

            # Filter out NaN for plotting
            valid_mask = pd.notna(df['Gain (%)'])
            valid_df = df[valid_mask]
            if valid_df.empty:
                raise ValueError("No valid data for plotting")
            combined = list(zip(valid_df['Index'], valid_df['Gain (%)']))
            sorted_combined = sorted(combined, key=lambda x: x[1], reverse=True)
            sorted_tickers, sorted_gains = zip(*sorted_combined)

            bar_colors = ['green' if g > 0 else 'red' for g in sorted_gains]
            bars = ax.bar(sorted_tickers, sorted_gains, color=bar_colors)

            ax.set_xlabel('Indices', fontsize=20, color='white')
            ax.set_ylabel('Gain (%)', fontsize=20, color='white')
            s_formatted = start_dt.strftime('%d-%m-%Y')
            e_formatted = end_dt.strftime('%d-%m-%Y')
            ax.set_title(f'Performance of equity indices of various countries from {s_formatted} to {e_formatted}', fontsize=30, color='white')

            ax.tick_params(axis='x', colors='white', rotation=45, labelsize=15)
            ax.tick_params(axis='y', colors='white', labelsize=20)
            plt.setp(ax.get_xticklabels(), ha='right')

            for bar, gain in zip(bars, sorted_gains):
                height = bar.get_height()
                va = 'bottom' if height > 0 else 'top'
                ax.text(bar.get_x() + bar.get_width() / 2, height, f'{gain:.2f}%', ha='center', va=va, fontsize=15, color='white')

            ax.grid(axis='y', linestyle='--', alpha=0.7)
            ax.grid(axis='x', linestyle='--', alpha=0.7)
            plt.tight_layout()

            # Save the plot to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', facecolor='black')
            buf.seek(0)
            plot_b64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close()

            # Base64 data URI
            plot_url = f"data:image/png;base64,{plot_b64}"

            return render_template('custom.html', plot_url=plot_url, table=table_html, start_date=start_str, end_date=end_str)
        except Exception as e:
            return render_template('custom.html', error=f"Error generating analysis: {str(e)}")
    
    return render_template('custom.html')

@app.route('/nifty50', methods=['GET', 'POST'])
def nifty50():
    if request.method == 'POST':
        try:
            start_str = request.form['start_date']
            end_str = request.form['end_date']
            live = 'live' in request.form
            start_dt = datetime.strptime(start_str, '%Y-%m-%d')
            end_dt = datetime.strptime(end_str, '%Y-%m-%d')

            # Load Nifty 50 CSV (place ind_nifty50list.csv in the app root directory)
            file_path = 'ind_nifty50list.csv'  # Adjust path if needed
            df_csv = pd.read_csv(file_path)
            symbols = [f"{x}.NS" for x in df_csv['Symbol'].tolist()]  # Assuming 'Symbol' column
            stock_names = df_csv['Symbol'].tolist()

            index_start_dates = []
            for ind in symbols:
                start_date = get_valid_date(ind, start_str)
                index_start_dates.append(start_date)

            end_yf = (end_dt + timedelta(days=1)).strftime('%Y-%m-%d')

            gains = []
            for i, ind in enumerate(symbols):
                gain = get_custom_date_range_gain(ind, index_start_dates[i], end_yf)
                gains.append(gain)

            # Create DataFrame for table
            df = pd.DataFrame({'Stock': stock_names, 'Gain (%)': gains})
            df = df.sort_values('Gain (%)', ascending=False).reset_index(drop=True)
            df['Gain (%)'] = df['Gain (%)'].round(2)
            table_html = df.to_html(classes='table table-striped table-bordered', escape=False, na_rep='N/A', float_format='%.2f')

            # Heatmap Plot: 10x5 matrix
            fig, ax = plt.subplots(figsize=(15, 20))
            fig.patch.set_facecolor('black')
            ax.set_facecolor('black')

            # Filter out NaN for plotting
            valid_mask = pd.notna(df['Gain (%)'])
            valid_df = df[valid_mask]
            if len(valid_df) == 0:
                raise ValueError("No valid data for plotting")
            
            # Pad to 50 if less, but assume 50
            while len(valid_df) < 50:
                valid_df = pd.concat([valid_df, pd.DataFrame({'Stock': [f'Empty_{len(valid_df)}'], 'Gain (%)': [np.nan]})], ignore_index=True)
            
            # Sort by gain descending
            valid_df = valid_df.sort_values('Gain (%)', ascending=False).reset_index(drop=True)
            
            # Reshape gains to 10x5 (rows x cols)
            gains_array = valid_df['Gain (%)'].values.reshape(10, 5)
            
            # Create annotation array with stock name and gain
            annotations = np.empty((10, 5), dtype=object)
            for i in range(10):
                for j in range(5):
                    idx = i * 5 + j
                    if idx < len(valid_df) and not pd.isna(valid_df.iloc[idx]['Gain (%)']):
                        stock = valid_df.iloc[idx]['Stock']
                        gain = valid_df.iloc[idx]['Gain (%)']
                        annotations[i, j] = f"{stock}\n{gain:.1f}%"
                    else:
                        annotations[i, j] = ""
            
            # Custom colormap: red to green
            cmap = LinearSegmentedColormap.from_list('rg', ['red', 'white', 'green'], N=256)
            
            # Create heatmap
            sns.heatmap(gains_array, annot=annotations, fmt='', cmap=cmap, center=0, ax=ax,
                        annot_kws={'fontsize': 12, 'ha': 'center', 'va': 'center', 'color': 'black'},
                        cbar_kws={'label': 'Gain (%)', 'shrink': 0.8},
                        linewidths=0.5, linecolor='white')
            
            # Set labels (simple row/col numbers since individual stocks in annot)
            col_labels = [str(j+1) for j in range(5)]
            row_labels = [str(i+1) for i in range(10)]
            ax.set_xticklabels(col_labels, color='white', fontsize=12, rotation=0)
            ax.set_yticklabels(row_labels, color='white', fontsize=12, rotation=0)
            ax.set_xlabel('Column', fontsize=14, color='white')
            ax.set_ylabel('Row (1=Top Performers)', fontsize=14, color='white')
            s_formatted = start_dt.strftime('%d-%m-%Y')
            e_formatted = end_dt.strftime('%d-%m-%Y')
            ax.set_title(f'Nifty 50 Stocks Performance Heatmap from {s_formatted} to {e_formatted}\n(Sorted by Gain; Green: Positive, Red: Negative)', 
                         fontsize=16, color='white', pad=20)
            
            plt.tight_layout()

            # Save the plot to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', facecolor='black')
            buf.seek(0)
            plot_b64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close()

            # Base64 data URI
            plot_url = f"data:image/png;base64,{plot_b64}"

            return render_template('nifty50.html', plot_url=plot_url, table=table_html, start_date=start_str, end_date=end_str, live=live)
        except Exception as e:
            return render_template('nifty50.html', error=f"Error generating analysis: {str(e)}")
    
    return render_template('nifty50.html')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
