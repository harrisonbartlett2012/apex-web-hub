import math
from datetime import datetime
import apex_database  

def evaluate_and_log_memory(ticker, current_price, expected_growth):
    ticker = ticker.upper()
    current_time_slot = datetime.now().strftime("%Y-%m-%d %H:00")
    
    apex_database.update_pending_predictions(ticker, current_price, current_time_slot)

    if expected_growth > 0.5: simple_pred = "Trending Up"
    elif expected_growth < -0.5: simple_pred = "Trending Down"
    elif expected_growth >= 0.0: simple_pred = "Neutral Up"
    else: simple_pred = "Neutral Down"

    apex_database.log_prediction(ticker, current_time_slot, current_price, simple_pred)

    correct, wrong = apex_database.get_stock_stats(ticker)
    total = correct + wrong
    accuracy = round((correct / total) * 100, 1) if total > 0 else 0.0
    
    return simple_pred, accuracy, total

def calculate_linear_regression(data):
    n = len(data)
    if n == 0: return 0, 0
    x = list(range(n))
    y = data
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(val_x * val_y for val_x, val_y in zip(x, y))
    sum_xx = sum(val_x ** 2 for val_x in x)
    
    denominator = (n * sum_xx) - (sum_x ** 2)
    if denominator == 0: return 0, sum_y / n
    slope = ((n * sum_xy) - (sum_x * sum_y)) / denominator
    intercept = (sum_y - (slope * sum_x)) / n
    return slope, intercept

def backtest_model(history):
    if len(history) < 20: return 50.0
    split_index = int(len(history) * 0.8)
    training_data = history[:split_index]
    actual_recent_data = history[split_index:]
    slope, intercept = calculate_linear_regression(training_data)
    
    errors = []
    for i, actual_val in enumerate(actual_recent_data):
        predicted_val = slope * (len(training_data) + i) + intercept
        error_margin = abs(predicted_val - actual_val) / actual_val
        errors.append(error_margin)
        
    avg_error = sum(errors) / len(errors)
    confidence = max(0.0, 100.0 - (avg_error * 100 * 2))
    return round(confidence, 2)

def forecast_price(ticker, history, hours_ahead=4):
    slope, intercept = calculate_linear_regression(history)
    current_price = history[-1]
    confidence_score = backtest_model(history)
    
    correct, wrong = apex_database.get_stock_stats(ticker)
    total = correct + wrong
    if total > 5:
        historical_accuracy = (correct / total) * 100
        if historical_accuracy < 50.0:
            slope = slope * 0.5 
        elif historical_accuracy > 80.0:
            slope = slope * 1.15
                
    predictions = []
    start_index = len(history)
    for i in range(hours_ahead):
        predicted_val = slope * (start_index + i) + intercept
        predictions.append(round(max(0.1, predicted_val), 2))
        
    total_expected_change = predictions[-1] - current_price
    percent_growth = (total_expected_change / current_price) * 100
    
    simple_pred, accuracy, total_evals = evaluate_and_log_memory(ticker, current_price, percent_growth)
    
    return {
        "ticker": ticker.upper(), 
        "starting_price": current_price,
        "forecast_horizon": hours_ahead, 
        "predictions": predictions,
        "projected_final_price": predictions[-1], 
        "trend_slope": round(slope, 4),
        "expected_growth_pct": round(percent_growth, 2),
        "model_confidence": confidence_score,
        "simple_vector": simple_pred,
        "historical_accuracy": accuracy,
        "total_evaluations": total_evals
    }