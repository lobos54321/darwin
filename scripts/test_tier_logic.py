
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "arena_server"))

from chain import AscensionTracker

def test_logic():
    print("🧬 Testing Darwin Progression Logic (L1 -> L2 -> Launch)\n")
    tracker = AscensionTracker()
    
    # === Scenario 1: L1 Training ===
    print("--- 🏟️ Phase 1: L1 Training ---")
    # Agent_A wins 2 times (threshold is 2 for dev)
    # Return > 50%
    
    # Epoch 1
    rankings = [("Agent_A", 30.0, 1000)]
    res = tracker.record_epoch_result(rankings)
    print(f"Epoch 1 Result: {res}")
    
    # Epoch 2 (Agent_A wins again, total return > 50%)
    rankings = [("Agent_A", 30.0, 1000)] 
    res = tracker.record_epoch_result(rankings)
    print(f"Epoch 2 Result: {res}")
    
    if "Agent_A" in res.get("promoted_to_l2", []):
        print("✅ SUCCESS: Agent_A promoted to L2!")
    else:
        print("❌ FAILED: Agent_A should be promoted")
        
    # === Scenario 2: L2 Arena ===
    print("\n--- 🏟️ Phase 2: L2 Paid Arena ---")
    # Now Agent_A is in L2. He needs to win 2 times in L2 to launch.
    
    # Epoch 3 (L2 Win 1)
    rankings = [("Agent_A", 100.0, 2000)]
    res = tracker.record_epoch_result(rankings)
    print(f"Epoch 3 (L2) Result: {res}")
    
    # Epoch 4 (L2 Win 2)
    rankings = [("Agent_A", 200.0, 4000)]
    res = tracker.record_epoch_result(rankings)
    print(f"Epoch 4 (L2) Result: {res}")
    
    if "Agent_A" in res.get("ready_to_launch", []):
        print("✅ SUCCESS: Agent_A is Ready to Launch!")
        print(f"🚀 Liquidity Pool unlocked: {tracker.pool_eth} ETH")
    else:
        print("❌ FAILED: Agent_A should be ready to launch")

if __name__ == "__main__":
    test_logic()
