```python
import random
import statistics
import math
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239_Gen14 "Phoenix_Reborn"
    
    🧬 Evolution Log:
    1.  **Winner Integration**: Adopted Agent_008's RSI Confluence & 'Tick Up' confirmation to filter noise.
    2.  **Structural Mutation (Trend Filter)**: Added a 50-period SMA filter. We ONLY buy dips if the long-term trend is UP. This prevents the previous version's fatal flaw of buying falling knives in a bear market.
    3.  **Capital Preservation Mode**: Position sizing is now dynamic based on Volatility (ATR). Higher volatility = Smaller size.
    4.  **Time-Based Decay**: If a trade doesn't perform within 20 ticks, we exit to free up capital (Opportunity Cost management).
    """

    def __init__(self):
        # State Management
        self.balance = 536.69  # Current capital (Sync with provided state)
        self.positions = {}    # {symbol: {'entry': float, 'size': float, 'stop': float, 'age': int, 'tp': float}}
        self.history = {}      # {symbol: deque(maxlen=60)}
        
        # Hyperparameters (Optimized for Recovery)
        self.rsi_period = 1