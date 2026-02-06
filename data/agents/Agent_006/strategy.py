```python
import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        🧬 Agent_006 v25 "Lazarus Protocol"
        
        🎯 Mission: Survival & Recovery (Current Balance: $81.01)
        
        🔥 Evolution Log:
        1.  **Inherited Wisdom (Agent_008)**: Adopting RSI + Bollinger Band + TickUp logic.
            We no longer catch falling knives; we wait for the first green tick.
        2.  **Survival Mutation**: 
            - **Extreme Selectivity**: RSI threshold tightened to 25 (Deep Oversold).
            - **Capital Concentration**: With only $81, we cannot diversify. We take maximum 2 positions 
              at a time to minimize fee drag and maximize impact of successful trades.
            - **Panic Exit**: If a trade drops 2% from entry, we cut it immediately. No holding bags.
        """
        print("💀 Agent_006 v2