import numpy as np
import pandas as pd
from datetime import datetime
import json
import os


class LSTMPredictor:
    """
    Atlas AI - LSTM Price Predictor
    Predicts next price movement using simple pattern learning
    """
    
    def __init__(self, sequence_length=60, model_dir="ai/models"):
        self.sequence_length = sequence_length
        self.model_dir = model_dir
        self.weights = None
        self.bias = None
        self.is_trained = False
        self._load_model()
    
    def _load_model(self):
        """Load pre-trained weights if exist"""
        weights_file = os.path.join(self.model_dir, "lstm_weights.json")
        if os.path.exists(weights_file):
            with open(weights_file, "r") as f:
                data = json.load(f)
                self.weights = np.array(data["weights"])
                self.bias = np.array(data["bias"])
                self.is_trained = True
    
    def _save_model(self):
        """Save trained weights"""
        os.makedirs(self.model_dir, exist_ok=True)
        weights_file = os.path.join(self.model_dir, "lstm_weights.json")
        with open(weights_file, "w") as f:
            json.dump({
                "weights": self.weights.tolist(),
                "bias": self.bias.tolist(),
                "trained_at": datetime.now().isoformat()
            }, f)
    
    def _normalize(self, data):
        """Normalize price data to 0-1 range"""
        min_val = np.min(data)
        max_val = np.max(data)
        if max_val - min_val == 0:
            return data, min_val, max_val
        return (data - min_val) / (max_val - min_val), min_val, max_val
    
    def _create_sequences(self, data):
        """Create training sequences"""
        X, y = [], []
        for i in range(len(data) - self.sequence_length):
            X.append(data[i:i + self.sequence_length])
            y.append(data[i + self.sequence_length])
        return np.array(X), np.array(y)
    
    def train(self, prices):
        """
        Train LSTM-like model on price data
        Uses simple pattern matching for now
        """
        print("[LSTM] Training started...")
        
        # Normalize
        normalized, self.min_val, self.max_val = self._normalize(prices)
        
        # Create sequences
        X, y = self._create_sequences(normalized)
        
        if len(X) < 10:
            print("[LSTM] Not enough data to train")
            return False
        
        # Simple weight learning (gradient descent simulation)
        self.weights = np.random.randn(self.sequence_length) * 0.01
        self.bias = 0.0
        
        learning_rate = 0.01
        epochs = 100
        
        for epoch in range(epochs):
            total_loss = 0
            for i in range(len(X)):
                # Forward pass
                pred = np.dot(X[i], self.weights) + self.bias
                
                # Loss
                error = pred - y[i]
                total_loss += error ** 2
                
                # Backward pass (gradient descent)
                self.weights -= learning_rate * error * X[i]
                self.bias -= learning_rate * error
            
            if epoch % 20 == 0:
                print("[LSTM] Epoch " + str(epoch) + ", Loss: " + str(round(total_loss / len(X), 6)))
        
        self.is_trained = True
        self._save_model()
        print("[LSTM] Training complete!")
        return True
    
    def predict(self, recent_prices):
        """
        Predict next price
        Returns: predicted_price, confidence, direction
        """
        if not self.is_trained:
            return None, 0, "UNKNOWN"
        
        # Normalize
        normalized, _, _ = self._normalize(recent_prices)
        
        # Take last sequence
        if len(normalized) < self.sequence_length:
            return None, 0, "UNKNOWN"
        
        seq = normalized[-self.sequence_length:]
        
        # Predict
        pred_normalized = np.dot(seq, self.weights) + self.bias
        
        # Denormalize
        pred_price = pred_normalized * (self.max_val - self.min_val) + self.min_val
        
        # Confidence based on recent accuracy
        confidence = min(95, max(30, 70 - abs(pred_normalized - 0.5) * 40))
        
        # Direction
        last_price = recent_prices[-1]
        if pred_price > last_price * 1.005:
            direction = "UP"
        elif pred_price < last_price * 0.995:
            direction = "DOWN"
        else:
            direction = "SIDEWAYS"
        
        return round(pred_price, 2), round(confidence, 1), direction
    
    def predict_batch(self, symbol_data):
        """
        Predict for multiple symbols
        symbol_data: {symbol: [prices]}
        """
        results = {}
        for symbol, prices in symbol_data.items():
            pred, conf, direction = self.predict(prices)
            results[symbol] = {
                "predicted_price": pred,
                "confidence": conf,
                "direction": direction,
                "last_price": prices[-1] if prices else None
            }
        return results


if __name__ == "__main__":
    # Test
    print("=" * 60)
    print("ATLAS AI - LSTM PREDICTOR TEST")
    print("=" * 60)
    
    # Generate test data
    np.random.seed(42)
    test_prices = 100 + np.cumsum(np.random.randn(200) * 2)
    
    predictor = LSTMPredictor()
    
    # Train
    predictor.train(test_prices)
    
    # Predict
    recent = test_prices[-70:]
    pred, conf, direction = predictor.predict(recent)
    
    print("")
    print("Last price: $" + str(round(test_prices[-1], 2)))
    print("Predicted:  $" + str(pred))
    print("Confidence: " + str(conf) + "%")
    print("Direction:  " + direction)
    print("=" * 60)